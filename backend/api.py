"""供后续前端接入的最小 FastAPI 图片检索接口。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
import json
from pathlib import Path, PureWindowsPath
from uuid import uuid4
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.config import Settings
from backend.db import create_session_factory, dispose_session_factory
from backend.encoders.base import EncoderIdentity, ImageEncoder
from backend.encoders.factory import create_encoder
from backend.excel_import import ExcelImportService, cleanup_import_job
from backend.image_assets import InvalidImageError, validate_image_bytes
from backend.repository import ImageRepository


MAX_UPLOAD_BYTES = 20 * 1024 * 1024


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


class LibraryResponse(BaseModel):
    """图库列表响应。"""

    images: list[LibraryImageResponse]


class SearchResultResponse(BaseModel):
    """单个相似图片候选的稳定 API 表示。"""

    rank: int
    image_id: int
    original_name: str
    image_url: str
    similarity: float


class SearchResponse(BaseModel):
    """图片检索响应；空结果可附加业务说明。"""

    model: ModelResponse
    results: list[SearchResultResponse]
    message: str | None = None


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


def create_app(
    settings: Settings | None = None,
    encoder: ImageEncoder | None = None,
    *,
    session_factory: sessionmaker[Session] | Callable[[], Session] | None = None,
    import_runner: Callable[[str, Path], None] | None = None,
) -> FastAPI:
    """创建 API 应用；注入项仅用于测试或嵌入式调用，不会提前加载模型。"""
    application_settings = settings or Settings.load()
    application_encoder = encoder or create_encoder(application_settings)
    owns_session_factory = session_factory is None
    application_session_factory = session_factory or create_session_factory(application_settings)
    application_import_runner = import_runner or ExcelImportService(
        application_settings, application_encoder, application_session_factory
    ).run

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if owns_session_factory and isinstance(application_session_factory, sessionmaker):
                dispose_session_factory(application_session_factory)

    app = FastAPI(title="地毯图片相似检索 API", lifespan=lifespan)

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
            background_tasks.add_task(application_import_runner, job_id, workbook_path)
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
        return LibraryResponse(
            images=[
                LibraryImageResponse(
                    id=row.image_id,
                    original_name=row.original_name,
                    image_url=f"/api/images/{row.image_id}",
                    mime_type=row.mime_type,
                    width=row.width,
                    height=row.height,
                    models=[_model_response(identity) for identity in row.models],
                )
                for row in rows
            ]
        )

    @app.get("/api/images/{image_id}")
    def image(image_id: int, repository: ImageRepository = Depends(get_repository)) -> FileResponse:
        """按数据库记录读取图库文件，拒绝越出 data/images 的历史坏路径。"""
        try:
            record = repository.find_by_id(image_id)
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试。") from error
        if record is None:
            raise HTTPException(status_code=404, detail="图片不存在。")

        image_root = application_settings.image_dir.resolve()
        stored_path = (application_settings.project_root / record.stored_path).resolve()
        if not stored_path.is_relative_to(image_root):
            raise HTTPException(status_code=400, detail="图片存储路径无效。")
        if not stored_path.is_file():
            raise HTTPException(status_code=404, detail="图片不存在。")
        return FileResponse(stored_path, media_type=record.mime_type, filename=record.original_name)

    @app.post("/api/search", response_model=SearchResponse)
    async def search(
        image: UploadFile = File(...),
        repository: ImageRepository = Depends(get_repository),
        top_k: int = Query(5, ge=1, le=50),
    ) -> SearchResponse:
        """在内存中校验并编码上传图片，查询过程绝不写入图库或数据库。"""
        try:
            data = await image.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=400, detail="上传图片不能超过 20 MiB。")
            validated = validate_image_bytes(data, image.filename or "uploaded.png")
            identity = application_encoder.identity
            query = application_encoder.encode(validated.image)
            rows = repository.search(identity, query, top_k, excluded_sha256=validated.sha256)
        except InvalidImageError as error:
            raise HTTPException(status_code=400, detail="图片无效或格式不受支持。") from error
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试。") from error
        finally:
            await image.close()

        results = [
            SearchResultResponse(
                rank=rank,
                image_id=row.image_id,
                original_name=row.original_name,
                image_url=f"/api/images/{row.image_id}",
                similarity=row.similarity_percent,
            )
            for rank, row in enumerate(rows, start=1)
        ]
        message = None if results else "当前模型没有可用的向量结果。"
        return SearchResponse(model=_model_response(identity), results=results, message=message)

    return app


app = create_app()
