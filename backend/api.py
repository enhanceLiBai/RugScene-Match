"""供后续前端接入的最小 FastAPI 图片检索接口。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
import json
import asyncio
from datetime import datetime, timedelta, timezone
from starlette.concurrency import run_in_threadpool
import threading
from functools import lru_cache
from io import BytesIO
from PIL import Image, ImageOps
from pathlib import Path, PureWindowsPath
from uuid import uuid4
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import text, select
from backend.models import MatchHistory, MatchHistoryImage, MatchFeedback, SceneLabel, UserAccount
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.observability import stage, timed, match_trace
from backend.config import Settings
from backend.access import restrict_management_access
from backend.auth import install_auth, public_user
from backend.conversions import install_conversions
from backend.db import create_session_factory, dispose_session_factory
from backend.encoders.base import EncoderIdentity, ImageEncoder
from backend.encoders.factory import create_encoder
from backend.excel_import import ExcelImportService, cleanup_import_job
from backend.image_assets import InvalidImageError, ValidatedImage, validate_image_bytes
from backend.repository import ImageMetadata, ImageRepository, LibraryRow, SearchRow
from backend.services import ImportStatus, LibraryService
from backend.scene import SceneClient, SceneError, backfill, validate_labels, usable_scene


@lru_cache(maxsize=32)
def preview_bytes(path: str, modified_ns: int) -> bytes:
    """缓存最近查看的预览图；文件修改后自动使用新缓存键。"""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=88, optimize=True)
        return output.getvalue()
from backend.matching import review_conflicts


MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_LIBRARY_PRICE = Decimal("9999999999.99")


class ModelResponse(BaseModel):
    """向调用方公开的模型身份，字段名保持 HTTP 契约稳定。"""

    model_config = ConfigDict(extra="forbid")

    encoder: str
    name: str
    pretrained: str
    dimension: int | None = None


class LibraryImageResponse(BaseModel):
    """图库中的一张已入库图片及其可用模型。"""

    model_config = ConfigDict(extra="forbid")

    id: int
    original_name: str
    image_url: str
    mime_type: str
    width: int
    height: int
    models: list[ModelResponse]
    sku: str | None = None
    product_name: str | None = None
    size: str | None = None
    price: float | None = None
    room: str | None = None
    style: str | None = None
    color: str | None = None
    stock: str | None = None
    selling_point: str | None = None


class LibraryResponse(BaseModel):
    """图库列表响应。"""

    images: list[LibraryImageResponse]


class LibraryImportResponse(BaseModel):
    """单张图库上传的业务结果和最终图片状态。"""

    status: Literal["imported", "duplicate", "embedding_added"]
    message: str
    image: LibraryImageResponse
    scene_labels: dict[str, str] | None = None


class SearchResultResponse(BaseModel):
    """单个相似图片候选的稳定 API 表示。"""

    rank: int
    image_id: int
    original_name: str
    image_url: str
    similarity: float
    sku: str | None = None
    product_name: str | None = None
    size: str | None = None
    price: float | None = None
    room: str | None = None
    style: str | None = None
    color: str | None = None
    stock: str | None = None
    selling_point: str | None = None


class ProductSearchResponse(BaseModel):
    rank: int
    product_id: str | None
    matched_buyer_image_url: str
    product_image_url: str | None
    matched_source_column: str | None
    similarity: float
    scene_labels: dict[str, str] | None = None
    matched_buyer_download_url: str | None = None
    product_download_url: str | None = None
    match_explanation: str | None = None
    buyer_image_id: int | None = None
    style: str | None = None


class SearchResponse(BaseModel):
    """图片检索响应；空结果可附加业务说明。"""

    model: ModelResponse
    results: list[ProductSearchResponse]
    message: str | None = None
    query_scene: dict[str, str] | None = None
    history_id: int | None = None


class FeedbackRequest(BaseModel):
    history_id: int = Field(gt=0)
    helpful: StrictBool
    reason: str = Field(default="", max_length=2000)


def _model_response(identity: EncoderIdentity) -> ModelResponse:
    """集中完成编码器身份到 HTTP 字段名的无损映射。"""
    return ModelResponse(
        encoder=identity.encoder,
        name=identity.model_name,
        pretrained=identity.pretrained,
        dimension=identity.dimension,
    )


def _configured_model_response(settings: Settings) -> ModelResponse:
    """健康检查仅展示配置，不能读取可能触发模型加载的 encoder.identity。"""
    return ModelResponse(
        encoder=settings.image_encoder,
        name=settings.clip_model_name,
        pretrained=settings.clip_pretrained,
    )


def _optional_text(value: str | None) -> str | None:
    """将表单空串和纯空白统一为未提供。"""
    cleaned = value.strip() if value is not None else ""
    return cleaned or None


def _optional_price(value: str | None) -> Decimal | None:
    """解析非负且最多两位小数的参考价，持久层继续使用 Decimal。"""
    cleaned = _optional_text(value)
    if cleaned is None:
        return None
    try:
        price = Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError("参考价必须是非负且最多两位小数的数字。") from error
    if (
        not price.is_finite()
        or price < 0
        or price > MAX_LIBRARY_PRICE
        or price.as_tuple().exponent < -2
    ):
        raise ValueError("参考价必须是非负且最多两位小数的数字。")
    return price


def _metadata_response(row: LibraryRow | SearchRow) -> dict[str, str | float | None]:
    """集中映射九个商品字段，避免图库、上传和搜索响应各自漂移。"""
    return {
        "sku": row.sku,
        "product_name": row.product_name,
        "size": row.size,
        "price": float(row.price) if row.price is not None else None,
        "room": row.room,
        "style": row.style,
        "color": row.color,
        "stock": row.stock,
        "selling_point": row.selling_point,
    }


def _library_image_response(row: LibraryRow) -> LibraryImageResponse:
    """将仓库图库行统一映射为 HTTP 图片表示。"""
    return LibraryImageResponse(
        id=row.image_id,
        original_name=row.original_name,
        image_url=f"/api/images/{row.image_id}",
        mime_type=row.mime_type,
        width=row.width,
        height=row.height,
        models=[_model_response(identity) for identity in row.models],
        **_metadata_response(row),
    )


def create_app(
    settings: Settings | None = None,
    encoder: ImageEncoder | None = None,
    *,
    session_factory: sessionmaker[Session] | Callable[[], Session] | None = None,
    import_runner: Callable[[str, Path], None] | None = None,
    frontend_root: Path | None = None,
) -> FastAPI:
    """创建 API 应用；注入项仅用于测试或嵌入式调用，不会提前加载模型。"""
    application_settings = settings or Settings.load()
    application_encoder = encoder or create_encoder(application_settings)
    scene_client = SceneClient(application_settings.project_root)
    application_frontend_root = frontend_root if frontend_root is not None else Path(__file__).resolve().parent.parent
    owns_session_factory = session_factory is None
    application_session_factory = session_factory or create_session_factory(application_settings)
    application_import_runner = import_runner or ExcelImportService(
        application_settings, application_encoder, application_session_factory
    ).run
    # 模型推理和批量入库共享本机 GPU/CPU；限制重任务并发，避免少量客服同时操作拖垮服务。
    search_semaphore = asyncio.Semaphore(8)
    import_lock = threading.Lock()
    def run_import_serialized(job_id: str, path: Path) -> None:
        with import_lock:
            application_import_runner(job_id, path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owns_session_factory and isinstance(application_session_factory, sessionmaker):
                dispose_session_factory(application_session_factory)

    app = FastAPI(title="地毯图片相似检索 API", lifespan=lifespan)
    install_auth(app, application_session_factory, application_frontend_root)
    install_conversions(app, application_session_factory)
    app.middleware('http')(restrict_management_access)

    @timed("history_save")
    def save_match(payload: SearchResponse, customer_image: ValidatedImage, user_id: int) -> SearchResponse:
        """单独事务保存快照，记录故障不丢失本次检索结果。"""
        try:
            with application_session_factory() as session:
                record = MatchHistory(payload_json=payload.model_dump_json(), user_id=user_id)
                session.add(record)
                session.flush()
                payload.history_id = record.id
                record.payload_json = payload.model_dump_json()
                session.add(MatchHistoryImage(history_id=record.id,
                    content=customer_image.raw_bytes, mime_type=customer_image.mime_type))
                session.commit()
        except SQLAlchemyError:
            payload.history_id = None
            payload.message = (payload.message or '') + ' 本次历史记录保存失败，请保留当前结果。'
        return payload

    @app.post('/api/feedback', status_code=201)
    def submit_feedback(feedback: FeedbackRequest, request: Request):
        reason = feedback.reason.strip()
        if not feedback.helpful and not reason:
            raise HTTPException(status_code=422, detail='请填写不合适的原因。')
        try:
            with application_session_factory() as session:
                history = session.get(MatchHistory, feedback.history_id)
                if history is None:
                    raise HTTPException(status_code=404, detail='匹配记录不存在，请重新匹配后提交。')
                if request.state.user['role'] != 'admin' and history.user_id != request.state.user['id']:
                    raise HTTPException(status_code=403, detail='只能为自己的匹配记录提交反馈。')
                record = MatchFeedback(history_id=feedback.history_id, helpful=feedback.helpful, reason=reason,
                                       submitted_by=request.state.user['id'])
                session.add(record)
                session.flush()
                feedback_id = record.id
                session.commit()
                return {'id': feedback_id, 'history_id': feedback.history_id}
        except SQLAlchemyError:
            raise HTTPException(status_code=503, detail='反馈保存失败，请稍后重试。') from None

    @app.get('/api/feedback')
    def list_feedback(before: int | None = Query(None, ge=1), helpful: bool | None = None):
        try:
            with application_session_factory() as session:
                stmt = select(MatchFeedback).order_by(MatchFeedback.id.desc()).limit(21)
                if before is not None:
                    stmt = stmt.where(MatchFeedback.id < before)
                if helpful is not None:
                    stmt = stmt.where(MatchFeedback.helpful == helpful)
                rows = list(session.scalars(stmt))
                users = {user.id: public_user(user) for user in session.scalars(select(UserAccount).where(
                    UserAccount.id.in_([row.submitted_by for row in rows[:20] if row.submitted_by])))}
                items = [{'id': row.id, 'history_id': row.history_id, 'helpful': row.helpful,
                          'reason': row.reason, 'created_at': row.created_at.isoformat(),
                          'submitted_by': users.get(row.submitted_by)} for row in rows[:20]]
                return {'items': items, 'next_before': items[-1]['id'] if len(rows) > 20 else None}
        except SQLAlchemyError:
            raise HTTPException(status_code=503, detail='反馈记录暂不可用，请稍后重试。') from None

    @app.get('/api/history')
    def match_history(before: int | None = Query(None, ge=1),
                      period: Literal['all', 'today', '3d', '7d', '30d'] = 'all'):
        try:
            with application_session_factory() as session:
                stmt = select(MatchHistory).order_by(MatchHistory.id.desc()).limit(21)
                if period != 'all':
                    days = {'today': 1, '3d': 3, '7d': 7, '30d': 30}[period]
                    today = datetime.now(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=0, microsecond=0)
                    stmt = stmt.where(MatchHistory.created_at >= today - timedelta(days=days - 1))
                if before is not None:
                    stmt = stmt.where(MatchHistory.id < before)
                rows = list(session.scalars(stmt))
                image_ids = set(session.scalars(select(MatchHistoryImage.history_id).where(
                    MatchHistoryImage.history_id.in_([row.id for row in rows[:20]]))))
                items = []
                users = {user.id: public_user(user) for user in session.scalars(select(UserAccount).where(
                    UserAccount.id.in_([row.user_id for row in rows[:20] if row.user_id])))}
                for row in rows[:20]:
                    payload = json.loads(row.payload_json)
                    items.append({'id':row.id, 'created_at':row.created_at.isoformat(),
                                  'user': users.get(row.user_id),
                                  'query_image_url':f'/api/history/{row.id}/image' if row.id in image_ids else None,
                                  'query_scene':payload.get('query_scene'),
                                  'result_count':len(payload.get('results',[]))})
                return {'items':items,'next_before':items[-1]['id'] if len(rows)>20 else None}
        except SQLAlchemyError:
            raise HTTPException(status_code=503,detail='历史记录暂不可用。') from None

    @app.get('/api/history/{history_id}')
    def match_history_detail(history_id: int):
        try:
            with application_session_factory() as session:
                row = session.get(MatchHistory,history_id)
                if row is None:
                    raise HTTPException(status_code=404,detail='历史记录不存在。')
                has_image = session.scalar(select(MatchHistoryImage.history_id).where(MatchHistoryImage.history_id == row.id))
                user = session.get(UserAccount, row.user_id) if row.user_id else None
                return {'id':row.id,'created_at':row.created_at.isoformat(),'payload':json.loads(row.payload_json),
                        'user': public_user(user) if user else None,
                        'query_image_url':f'/api/history/{row.id}/image' if has_image else None}
        except SQLAlchemyError:
            raise HTTPException(status_code=503,detail='历史记录暂不可用。') from None

    @app.get('/api/history/{history_id}/image')
    def match_history_image(history_id: int):
        try:
            with application_session_factory() as session:
                stored = session.get(MatchHistoryImage, history_id)
                if stored is None:
                    raise HTTPException(status_code=404, detail='该记录未保存客户照片。')
                return Response(content=stored.content, media_type=stored.mime_type,
                                headers={'Cache-Control': 'private, no-store'})
        except SQLAlchemyError:
            raise HTTPException(status_code=503, detail='历史照片暂不可用。') from None

    @app.post('/api/scene-labels/backfill')
    def label_existing(background_tasks: BackgroundTasks):
        job_id = uuid4().hex
        with application_session_factory() as session:
            ImageRepository(session).create_import_job(job_id,'场景标签补充')
            session.commit()
        background_tasks.add_task(backfill,application_settings,application_session_factory,scene_client,job_id)
        return {'job_id':job_id}

    def get_session() -> Iterator[Session]:
        """每个请求独立获取并关闭会话，连接创建失败统一转为服务不可用。"""
        try:
            session = application_session_factory()
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试。") from error
        try:
            yield session
        finally:
            session.close()

    def get_repository(session: Session = Depends(get_session)) -> ImageRepository:
        """将请求会话包装为仓库，路由不直接依赖持久层模型。"""
        return ImageRepository(session)

    @app.post("/api/imports")
    async def import_workbook(
        background_tasks: BackgroundTasks,
        workbook: UploadFile = File(...),
        session: Session = Depends(get_session),
    ) -> dict[str, str]:
        """分块保存 XLSX，提交任务状态后交由后台线程处理。"""
        job_id = uuid4().hex
        try:
            original_name = PureWindowsPath(workbook.filename or "").name
            if Path(original_name).suffix.lower() != ".xlsx":
                raise HTTPException(status_code=400, detail="仅支持上传 .xlsx 工作簿。")
            job_dir = application_settings.import_job_dir / job_id
            job_dir.mkdir(parents=True, exist_ok=False)
            workbook_path = job_dir / "workbook.xlsx"
            with workbook_path.open("wb") as output:
                while chunk := await workbook.read(1024 * 1024):
                    output.write(chunk)
            repository = ImageRepository(session)
            repository.create_import_job(job_id, original_name)
            repository.update_import_job(job_id, status="parsing")
            session.commit()
            background_tasks.add_task(run_import_serialized, job_id, workbook_path)
            return {"job_id": job_id, "status": "parsing"}
        except HTTPException:
            cleanup_import_job(application_settings, job_id)
            raise
        except Exception as error:
            session.rollback()
            cleanup_import_job(application_settings, job_id)
            raise HTTPException(status_code=503, detail="上传失败，服务暂不可用，请稍后重试。") from error
        finally:
            await workbook.close()

    @app.get("/api/imports/{job_id}")
    def import_status(job_id: str, repository: ImageRepository = Depends(get_repository)) -> dict[str, object]:
        """返回后台持久化状态及 JSON 汇总，不向客户端暴露文件路径。"""
        try:
            job = repository.find_import_job(job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="导入任务不存在。")
            summary = json.loads(job.summary_json) if job.summary_json else {}
        except (SQLAlchemyError, ValueError) as error:
            raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试。") from error
        return {
            "job_id": job.job_id, "status": job.status,
            "processed": job.processed, "total": job.total,
            "summary": summary, "error": job.error_message,
        }

    @app.get("/health")
    def health(session: Session = Depends(get_session)) -> dict[str, object]:
        """检测数据库连接且仅返回配置模型，保持真实权重惰性加载。"""
        try:
            session.execute(text("SELECT 1")).scalar_one()
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试。") from error
        return {"database": "ok", "model": _configured_model_response(application_settings).model_dump()}

    @app.get("/api/library", response_model=LibraryResponse)
    def library(repository: ImageRepository = Depends(get_repository)) -> LibraryResponse:
        """返回稳定排序的图库图片及可用模型身份。"""
        try:
            rows = repository.list_library()
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试。") from error
        return LibraryResponse(images=[_library_image_response(row) for row in rows])

    @app.post("/api/library", response_model=LibraryImportResponse)
    async def upload_library_image(
        image: UploadFile = File(...),
        sku: str | None = Form(None),
        product_name: str | None = Form(None),
        size: str | None = Form(None),
        price: str | None = Form(None),
        room: str | None = Form(None),
        style: str | None = Form(None),
        color: str | None = Form(None),
        stock: str | None = Form(None),
        selling_point: str | None = Form(None),
        repository: ImageRepository = Depends(get_repository),
    ) -> LibraryImportResponse:
        """校验并导入单张图库图片，重复内容可增量补充非空商品字段。"""
        try:
            data = await image.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=400, detail="上传图片不能超过 20 MiB。")
            parsed_price = _optional_price(price)
            validated = validate_image_bytes(data, image.filename or "uploaded.png")
            validated.image.close()
            metadata = ImageMetadata(
                sku=_optional_text(sku),
                product_name=_optional_text(product_name),
                size=_optional_text(size),
                price=parsed_price,
                room=_optional_text(room),
                style=_optional_text(style),
                color=_optional_text(color),
                stock=_optional_text(stock),
                selling_point=_optional_text(selling_point),
            )
            service = ExcelImportService(application_settings, application_encoder, application_session_factory)
            imported, encoded = service.import_single(data, image.filename or "uploaded.png", metadata)
            record = repository.find_by_sha256(validated.sha256)
            row = next((item for item in repository.list_library() if item.image_id == record.id), None)
            if row is None:
                raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试。")
            from backend.scene import VERSION
            with application_session_factory() as label_session:
                label = label_session.get(SceneLabel, record.id)
                labels = json.loads(label.labels_json) if label and label.model == scene_client.model and label.version == VERSION else None
        except (InvalidImageError, ValueError) as error:
            raise HTTPException(status_code=400, detail="图片或商品信息无效，请检查后重试。") from error
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试。") from error
        finally:
            await image.close()

        return LibraryImportResponse(
            status="imported" if imported else "embedding_added" if encoded else "duplicate",
            message="图片已入库，场景标签已就绪。" if labels else "图片已入库，但场景标签未生成；请点击补充已有买家秀场景标签后再测试场景检索。",
            image=_library_image_response(row),
            scene_labels=labels,
        )

    @app.get("/api/images/{image_id}")
    def image(image_id: int, download: int = Query(0, ge=0, le=1), preview: int = Query(0, ge=0, le=1)) -> Response:
        """按数据库记录读取图库文件，拒绝越出 data/images 的历史坏路径。"""
        try:
            with application_session_factory() as session:
                record = ImageRepository(session).find_by_id(image_id)
                if record is None:
                    raise HTTPException(status_code=404, detail="图片不存在。")
                stored_name, mime_type, original_name = record.stored_path, record.mime_type, record.original_name
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试。") from error
        if record is None:
            raise HTTPException(status_code=404, detail="图片不存在。")

        image_root = application_settings.image_dir.resolve()
        stored_path = (application_settings.project_root / stored_name).resolve()
        if not stored_path.is_relative_to(image_root):
            raise HTTPException(status_code=400, detail="图片存储路径无效。")
        if not stored_path.is_file():
            raise HTTPException(status_code=404, detail="图片不存在。")
        if preview and not download:
            return Response(preview_bytes(str(stored_path), stored_path.stat().st_mtime_ns),
                            media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
        return FileResponse(stored_path, media_type=mime_type, filename=original_name if download else None, content_disposition_type="attachment" if download else "inline")

    @app.delete("/api/library/{image_id}")
    def delete_library_image(image_id: int, repository: ImageRepository = Depends(get_repository)) -> dict[str, object]:
        """删除图库图片及向量、标签和商品关联；历史结果快照保持不变。"""
        try:
            record = repository.find_by_id(image_id)
            if record is None:
                raise HTTPException(status_code=404, detail="图库图片不存在。")
            path = (application_settings.project_root / record.stored_path).resolve()
            if not path.is_relative_to(application_settings.image_dir.resolve()):
                raise HTTPException(status_code=400, detail="图片存储路径无效。")
            # 场景标签表的外键没有级联删除，先清理关联记录再删除图片。
            repository._session.query(SceneLabel).filter(SceneLabel.image_id == image_id).delete(synchronize_session=False)
            repository._session.delete(record)
            repository._session.commit()
            if path.is_file():
                path.unlink()
            return {"deleted": True, "image_id": image_id}
        except HTTPException:
            raise
        except (SQLAlchemyError, OSError):
            repository._session.rollback()
            raise HTTPException(status_code=503, detail="图片删除失败，请稍后重试。") from None

    @match_trace
    def execute_search(data, filename, confirmed_scene, top_k, user_id):
        with application_session_factory() as session:
            return search_sync(data, filename, confirmed_scene, top_k, ImageRepository(session), user_id)

    def search_sync(data, filename, confirmed_scene, top_k, repository, user_id):
        try:
            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=400, detail="上传图片不能超过 20 MiB。")
            with stage("image_validation"):
                validated = validate_image_bytes(data, filename)
            with stage("model_load"):
                identity = application_encoder.identity
            with stage("encode_including_gpu_wait"):
                query = application_encoder.encode(validated.image)
            if confirmed_scene is not None:
                try:
                    scene_labels = validate_labels(json.loads(confirmed_scene))
                except (ValueError, TypeError):
                    raise HTTPException(status_code=400, detail='手动确认的场景标签格式无效。') from None
            else:
                try:
                    scene_labels = scene_client.identify(validated.image)
                except SceneError:
                    scene_labels = None
            if not usable_scene(scene_labels):
                return save_match(SearchResponse(model=_model_response(identity), results=[], message='场景识别不可用或关键属性无法确认，请在下方手动确认空间、沙发与地板后重新匹配。本次未放宽筛选。', query_scene=scene_labels), validated, user_id)
            rows = repository.search_products(identity, query, top_k=top_k, scene_labels=scene_labels, scene_model=scene_client.model)
            review_notes = {}
            review_count = review_failures = 0
            # 人工明确确认的标签保持硬约束，不由二次模型覆盖。
            if confirmed_scene is None:
                visual_candidates = repository.search_products(identity, query, top_k=20,
                    scene_labels=scene_labels, scene_model=scene_client.model, filter_scene=False)
                rows, review_notes, review_count, review_failures = review_conflicts(
                    application_settings, repository, scene_client, validated.image, scene_labels,
                    rows, visual_candidates, top_k)
        except InvalidImageError as error:
            raise HTTPException(status_code=400, detail="图片无效或格式不受支持。") from error
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试。") from error

        results = [
            ProductSearchResponse(
                rank=rank,
                product_id=row.product_id,
                matched_buyer_image_url=f"/api/images/{row.buyer_image_id}",
                buyer_image_id=row.buyer_image_id,
                style=_optional_text(row.style),
                product_image_url=f"/api/images/{row.product_image_id}" if row.product_image_id else None,
                matched_source_column=row.source_column,
                similarity=row.similarity_percent,
                scene_labels=row.scene_labels,
                matched_buyer_download_url=f"/api/images/{row.buyer_image_id}?download=1",
                product_download_url=f"/api/images/{row.product_image_id}?download=1" if row.product_image_id else None,
                match_explanation=review_notes.get(row.buyer_image_id),
            )
            for rank, row in enumerate(rows, start=1)
        ]
        message = '按空间、沙发与地板属性筛选，同灰色系允许深浅差异，通过后按图片相似度排序。' if results else '暂无通过属性筛选或双图复核的买家秀；请核对标签或补充图库。'
        if review_count:
            message += f' 已对 {review_count} 张高相似度冲突候选进行双图复核。'
        if review_failures:
            message += f' 其中 {review_failures} 张复核未完成，未将其放行；可重试。'
        return save_match(SearchResponse(model=_model_response(identity), results=results, message=message, query_scene=scene_labels), validated, user_id)

    @app.post("/api/search", response_model=SearchResponse)
    async def search(
        request: Request,
        image: UploadFile = File(...),
        confirmed_scene: str | None = Form(None),
        top_k: int = Query(5, ge=1, le=50),
    ) -> SearchResponse:
        """最多八个匹配并行，完整同步流程在线程中执行。"""
        try:
            async with search_semaphore:
                data = await image.read(MAX_UPLOAD_BYTES + 1)
                return await run_in_threadpool(
                    execute_search, data, image.filename or "uploaded.png", confirmed_scene, top_k, request.state.user['id'])
        finally:
            await image.close()

    @app.get("/", include_in_schema=False)
    def frontend_index() -> FileResponse:
        """仅公开固定前端入口，不挂载整个项目目录。"""
        return FileResponse(application_frontend_root / "index.html", media_type="text/html")

    @app.get("/styles.css", include_in_schema=False)
    def frontend_styles() -> FileResponse:
        return FileResponse(application_frontend_root / "styles.css", media_type="text/css")

    @app.get("/admin", include_in_schema=False)
    @app.get("/feedback", include_in_schema=False)
    def feedback_page() -> FileResponse:
        return FileResponse(application_frontend_root / "feedback.html", media_type="text/html")

    @app.get("/admin.js", include_in_schema=False)
    def admin_script() -> FileResponse:
        return FileResponse(application_frontend_root / "admin.js", media_type="text/javascript")

    @app.get("/feedback.js", include_in_schema=False)
    def feedback_script() -> FileResponse:
        return FileResponse(application_frontend_root / "feedback.js", media_type="text/javascript")

    @app.get("/feedback.css", include_in_schema=False)
    def feedback_styles() -> FileResponse:
        return FileResponse(application_frontend_root / "feedback.css", media_type="text/css")

    @app.get("/matcher-core.js", include_in_schema=False)
    def frontend_matcher_core() -> FileResponse:
        return FileResponse(application_frontend_root / "matcher-core.js", media_type="text/javascript")

    @app.get("/api-client.js", include_in_schema=False)
    def frontend_api_client() -> FileResponse:
        return FileResponse(application_frontend_root / "api-client.js", media_type="text/javascript")

    @app.get("/app.js", include_in_schema=False)
    def frontend_app() -> FileResponse:
        return FileResponse(application_frontend_root / "app.js", media_type="text/javascript")

    @app.get('/orders.js', include_in_schema=False)
    def order_script():
        return FileResponse(application_frontend_root / 'orders.js', media_type='text/javascript')

    return app


app = create_app()
