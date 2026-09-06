"""供后续前端接入的最小 FastAPI 图片检索接口。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.config import Settings
from backend.db import create_session_factory, dispose_session_factory
from backend.encoders.base import EncoderIdentity, ImageEncoder
from backend.encoders.factory import create_encoder
from backend.image_assets import InvalidImageError, validate_image_bytes
from backend.repository import ImageMetadata, ImageRepository, LibraryRow, SearchRow
from backend.services import ImportStatus, LibraryService


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
    if not price.is_finite() or price < 0 or price.as_tuple().exponent < -2:
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
    frontend_root: Path | None = None,
) -> FastAPI:
    """创建 API 应用；注入项仅用于测试或嵌入式调用，不会提前加载模型。"""
    application_settings = settings or Settings.load()
    application_encoder = encoder or create_encoder(application_settings)
    application_frontend_root = frontend_root if frontend_root is not None else Path(__file__).resolve().parent.parent
    owns_session_factory = session_factory is None
    application_session_factory = session_factory or create_session_factory(application_settings)

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
            service = LibraryService(
                repository=repository,
                encoder=application_encoder,
                image_dir=application_settings.image_dir,
                project_root=application_settings.project_root,
            )
            result = service.import_bytes(data, image.filename or "uploaded.png", metadata)
            if result.status is ImportStatus.FAILED or result.image_id is None:
                raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试。")
            row = next((item for item in repository.list_library() if item.image_id == result.image_id), None)
            if row is None:
                raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试。")
        except (InvalidImageError, ValueError) as error:
            raise HTTPException(status_code=400, detail="图片或商品信息无效，请检查后重试。") from error
        except SQLAlchemyError as error:
            raise HTTPException(status_code=503, detail="服务暂不可用，请稍后重试。") from error
        finally:
            await image.close()

        status_by_result = {
            ImportStatus.IMPORTED: "imported",
            ImportStatus.DUPLICATE: "duplicate",
            ImportStatus.EMBEDDING_ADDED: "embedding_added",
        }
        return LibraryImportResponse(
            status=status_by_result[result.status],
            message=result.message,
            image=_library_image_response(row),
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
                **_metadata_response(row),
            )
            for rank, row in enumerate(rows, start=1)
        ]
        message = None if results else "当前模型没有可用的向量结果。"
        return SearchResponse(model=_model_response(identity), results=results, message=message)

    @app.get("/", include_in_schema=False)
    def frontend_index() -> FileResponse:
        """仅公开固定前端入口，不挂载整个项目目录。"""
        return FileResponse(application_frontend_root / "index.html", media_type="text/html")

    @app.get("/styles.css", include_in_schema=False)
    def frontend_styles() -> FileResponse:
        return FileResponse(application_frontend_root / "styles.css", media_type="text/css")

    @app.get("/matcher-core.js", include_in_schema=False)
    def frontend_matcher_core() -> FileResponse:
        return FileResponse(application_frontend_root / "matcher-core.js", media_type="text/javascript")

    @app.get("/api-client.js", include_in_schema=False)
    def frontend_api_client() -> FileResponse:
        return FileResponse(application_frontend_root / "api-client.js", media_type="text/javascript")

    @app.get("/app.js", include_in_schema=False)
    def frontend_app() -> FileResponse:
        return FileResponse(application_frontend_root / "app.js", media_type="text/javascript")

    return app


app = create_app()
