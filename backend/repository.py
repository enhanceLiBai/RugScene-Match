"""图片与模型向量的持久化仓库，不负责事务提交或回滚。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Final

import numpy as np
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.encoders.base import EncoderIdentity
from backend.models import ImageEmbedding, ImageRecord, ImportJob, ProductImage


@dataclass(frozen=True)
class ImageMetadata:
    """图片的九个选填商品字段；更新时 None 表示不覆盖已有值。"""

    sku: str | None = None
    product_name: str | None = None
    size: str | None = None
    price: Decimal | None = None
    room: str | None = None
    style: str | None = None
    color: str | None = None
    stock: str | None = None
    selling_point: str | None = None


@dataclass(frozen=True)
class SearchRow:
    """相似度查询的完整结果，供后续 CLI 和 API 直接映射输出。"""

    image_id: int
    original_name: str
    stored_path: str
    sha256: str
    mime_type: str
    width: int
    height: int
    encoder: str
    model_name: str
    pretrained: str
    dimension: int
    cosine_distance: float
    similarity_percent: float
    sku: str | None = None
    product_name: str | None = None
    size: str | None = None
    price: Decimal | None = None
    room: str | None = None
    style: str | None = None
    color: str | None = None
    stock: str | None = None
    selling_point: str | None = None


@dataclass(frozen=True)
class LibraryRow:
    """图库接口所需的一张图片及其已持久化的模型身份。"""

    image_id: int
    original_name: str
    stored_path: str
    mime_type: str
    width: int
    height: int
    models: tuple[EncoderIdentity, ...]
    sku: str | None = None
    product_name: str | None = None
    size: str | None = None
    price: Decimal | None = None
    room: str | None = None
    style: str | None = None
    color: str | None = None
    stock: str | None = None
    selling_point: str | None = None


_VECTOR_DTYPE: Final = np.dtype(np.float32)
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")


def cosine_distance_to_percent(distance: float) -> float:
    """将余弦距离稳定转换为 0–100 的两位小数百分比。"""
    value = float(distance)
    if not np.isfinite(value):
        raise ValueError("余弦距离必须为有限数值。")
    return round(max(0.0, min(100.0, (1.0 - value) * 100.0)), 2)


def _validated_vector(identity: EncoderIdentity, values: np.ndarray) -> np.ndarray:
    """在持久化边界复核编码器输出，防止错误维度或数值污染索引空间。"""
    if not isinstance(values, np.ndarray) or values.dtype != _VECTOR_DTYPE:
        raise ValueError("图片编码向量必须是一维 float32 NumPy 数组。")
    if values.ndim != 1:
        raise ValueError("图片编码向量必须是一维数组。")
    if values.size != identity.dimension:
        raise ValueError("图片编码向量维度与编码器身份不一致。")
    if not np.isfinite(values).all():
        raise ValueError("图片编码向量不能包含 NaN 或 Infinity。")
    norm = float(np.linalg.norm(values))
    if not np.isfinite(norm) or not np.isclose(norm, 1.0, rtol=1e-4, atol=1e-5):
        raise ValueError("图片编码向量必须是有限的 L2 单位向量。")
    return values


def _relative_posix_path(stored_path: str) -> str:
    """只接受相对于项目根目录的可移植路径，仓库绝不读取本地文件。"""
    normalized = stored_path.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        raise ValueError("图片存储路径必须是相对于项目根目录的路径。")
    windows_path = PureWindowsPath(stored_path)
    if windows_path.drive or windows_path.root:
        raise ValueError("图片存储路径必须是相对于项目根目录的路径。")
    return path.as_posix()


class ImageRepository:
    """只封装图片和向量的数据库操作；提交与回滚由上层服务负责。"""

    def __init__(self, session: Session) -> None:
        """绑定调用方提供的 SQLAlchemy 会话。"""
        self._session = session

    def find_by_sha256(self, sha256: str) -> ImageRecord | None:
        """按精确文件哈希查找已入库图片。"""
        return self._session.scalar(select(ImageRecord).where(ImageRecord.sha256 == sha256))

    def lock_sha256(self, sha256: str) -> None:
        """在当前 PostgreSQL 事务内串行化同一原始文件哈希的完整入库工作单元。"""
        if not _SHA256_PATTERN.fullmatch(sha256):
            raise ValueError("图片 SHA-256 必须是 64 位小写十六进制文本。")
        key = int(sha256[:16], 16)
        if key >= 1 << 63:
            key -= 1 << 64
        self._session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})

    def add_image(
        self,
        *,
        original_name: str,
        stored_path: str,
        sha256: str,
        mime_type: str,
        width: int,
        height: int,
    ) -> ImageRecord:
        """新增一条图片元数据，并刷新主键但不提交事务。"""
        if not _SHA256_PATTERN.fullmatch(sha256):
            raise ValueError("图片 SHA-256 必须是 64 位小写十六进制文本。")
        record = ImageRecord(
            original_name=original_name,
            stored_path=_relative_posix_path(stored_path),
            sha256=sha256,
            mime_type=mime_type,
            width=width,
            height=height,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def list_images(self) -> list[ImageRecord]:
        """按主键稳定列出图片，方便后续图库接口分页扩展。"""
        return list(self._session.scalars(select(ImageRecord).order_by(ImageRecord.id.asc())))

    def update_metadata(self, image: ImageRecord, metadata: ImageMetadata) -> None:
        """只更新非 None 字段，支持重复入库时逐步补充商品资料。"""
        for field in (
            "sku",
            "product_name",
            "size",
            "price",
            "room",
            "style",
            "color",
            "stock",
            "selling_point",
        ):
            value = getattr(metadata, field)
            if value is not None:
                setattr(image, field, value)
        self._session.flush()

    def find_by_id(self, image_id: int) -> ImageRecord | None:
        """按主键查找图片元数据，供受控图库文件读取使用。"""
        return self._session.get(ImageRecord, image_id)

    def link_product_image(
        self,
        product_id: str,
        image: ImageRecord,
        image_role: str,
        source_column: str,
    ) -> ProductImage:
        """幂等关联商品与图片，重复导入复用已有关联记录。"""
        statement = insert(ProductImage).values(
            product_id=product_id,
            image_id=image.id,
            image_role=image_role,
            source_column=source_column,
        )
        statement = statement.on_conflict_do_nothing(
            index_elements=(ProductImage.product_id, ProductImage.image_id, ProductImage.image_role)
        )
        self._session.execute(statement)
        self._session.flush()
        link = self._session.scalar(
            select(ProductImage).where(
                ProductImage.product_id == product_id,
                ProductImage.image_id == image.id,
                ProductImage.image_role == image_role,
            )
        )
        if link is None:
            raise RuntimeError("商品图片关联写入后未找到记录。")
        return link

    def set_current_product_main(
        self,
        product_id: str,
        image: ImageRecord,
        source_column: str = "K",
    ) -> ProductImage:
        """将指定图片设为当前主图，同时停用该商品此前所有主图。"""
        link = self.link_product_image(product_id, image, "product_main", source_column)
        self._session.execute(
            update(ProductImage)
            .where(
                ProductImage.product_id == product_id,
                ProductImage.image_role == "product_main",
            )
            .values(is_active=False)
        )
        self._session.execute(update(ProductImage).where(ProductImage.id == link.id).values(is_active=True))
        self._session.flush()
        return link

    def list_product_images(self, product_id: str) -> list[ProductImage]:
        """按关联创建顺序读取一个商品的全部主图和买家秀。"""
        statement = select(ProductImage).where(ProductImage.product_id == product_id).order_by(ProductImage.id.asc())
        return list(self._session.scalars(statement))

    def create_import_job(self, job_id: str, original_name: str) -> ImportJob:
        """新建处于上传状态的 Excel 导入任务。"""
        job = ImportJob(job_id=job_id, original_name=original_name)
        self._session.add(job)
        self._session.flush()
        return job

    def find_import_job(self, job_id: str) -> ImportJob | None:
        """按任务标识读取导入状态，供轮询接口使用。"""
        return self._session.get(ImportJob, job_id)

    def update_import_job(self, job_id: str, **values: object) -> ImportJob:
        """更新导入任务的受控状态字段，拒绝改写任务身份和原始文件名。"""
        allowed_fields = {"status", "processed", "total", "summary_json", "error_message"}
        invalid_fields = set(values) - allowed_fields
        if invalid_fields:
            raise ValueError("导入任务包含不允许更新的字段。")
        job = self.find_import_job(job_id)
        if job is None:
            raise ValueError("导入任务不存在。")
        for field, value in values.items():
            setattr(job, field, value)
        self._session.flush()
        return job

    def list_library(self) -> list[LibraryRow]:
        """稳定列出图片及全部已有模型身份，避免 API 逐图查询向量。"""
        statement = (
            select(ImageRecord, ImageEmbedding)
            .outerjoin(ImageEmbedding, ImageEmbedding.image_id == ImageRecord.id)
            .order_by(
                ImageRecord.id.asc(),
                ImageEmbedding.encoder.asc(),
                ImageEmbedding.model_name.asc(),
                ImageEmbedding.pretrained.asc(),
                ImageEmbedding.dimension.asc(),
            )
        )
        records: dict[int, LibraryRow] = {}
        for image, embedding in self._session.execute(statement):
            existing = records.get(image.id)
            if existing is None:
                existing = LibraryRow(
                    image_id=image.id,
                    original_name=image.original_name,
                    stored_path=image.stored_path,
                    mime_type=image.mime_type,
                    width=image.width,
                    height=image.height,
                    models=(),
                    sku=image.sku,
                    product_name=image.product_name,
                    size=image.size,
                    price=image.price,
                    room=image.room,
                    style=image.style,
                    color=image.color,
                    stock=image.stock,
                    selling_point=image.selling_point,
                )
            if embedding is not None:
                existing = LibraryRow(
                    image_id=existing.image_id,
                    original_name=existing.original_name,
                    stored_path=existing.stored_path,
                    mime_type=existing.mime_type,
                    width=existing.width,
                    height=existing.height,
                    models=existing.models
                    + (
                        EncoderIdentity(
                            encoder=embedding.encoder,
                            model_name=embedding.model_name,
                            pretrained=embedding.pretrained,
                            dimension=embedding.dimension,
                        ),
                    ),
                    sku=existing.sku,
                    product_name=existing.product_name,
                    size=existing.size,
                    price=existing.price,
                    room=existing.room,
                    style=existing.style,
                    color=existing.color,
                    stock=existing.stock,
                    selling_point=existing.selling_point,
                )
            records[image.id] = existing
        return list(records.values())

    def image_count(self) -> int:
        """返回当前事务可见的图片数。"""
        return int(self._session.scalar(select(func.count(ImageRecord.id))) or 0)

    def embedding_count(self, image_id: int | None = None) -> int:
        """返回当前事务可见的向量数，可按图片过滤。"""
        statement = select(func.count(ImageEmbedding.id))
        if image_id is not None:
            statement = statement.where(ImageEmbedding.image_id == image_id)
        return int(self._session.scalar(statement) or 0)

    def upsert_embedding(self, image: ImageRecord, identity: EncoderIdentity, embedding: np.ndarray) -> None:
        """新增或更新指定图片与完整模型身份对应的唯一向量。"""
        vector = _validated_vector(identity, embedding)
        statement = insert(ImageEmbedding).values(
            image_id=image.id,
            encoder=identity.encoder,
            model_name=identity.model_name,
            pretrained=identity.pretrained,
            dimension=identity.dimension,
            embedding=vector,
        )
        statement = statement.on_conflict_do_update(
            index_elements=(
                ImageEmbedding.image_id,
                ImageEmbedding.encoder,
                ImageEmbedding.model_name,
                ImageEmbedding.pretrained,
            ),
            set_={"dimension": identity.dimension, "embedding": vector},
        )
        self._session.execute(statement)
        self._session.flush()
        # Core UPSERT 不会自动同步已加载的 ORM 行，统一过期以保证后续读取不会使用旧向量。
        self._session.expire_all()

    def search(
        self,
        identity: EncoderIdentity,
        query: np.ndarray,
        top_k: int,
        excluded_sha256: str | None = None,
    ) -> list[SearchRow]:
        """在相同向量空间中按余弦距离检索，必要时排除精确相同文件。"""
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k 必须是正整数。")
        vector = _validated_vector(identity, query)
        distance = ImageEmbedding.embedding.cosine_distance(vector).label("cosine_distance")
        statement = (
            select(ImageRecord, ImageEmbedding, distance)
            .join(ImageEmbedding, ImageEmbedding.image_id == ImageRecord.id)
            .where(
                ImageEmbedding.encoder == identity.encoder,
                ImageEmbedding.model_name == identity.model_name,
                ImageEmbedding.pretrained == identity.pretrained,
                ImageEmbedding.dimension == identity.dimension,
            )
            .order_by(distance.asc(), ImageRecord.id.asc())
            .limit(top_k)
        )
        if excluded_sha256 is not None:
            statement = statement.where(ImageRecord.sha256 != excluded_sha256)

        results: list[SearchRow] = []
        for image, embedding, raw_distance in self._session.execute(statement):
            cosine_distance = float(raw_distance)
            results.append(
                SearchRow(
                    image_id=image.id,
                    original_name=image.original_name,
                    stored_path=image.stored_path,
                    sha256=image.sha256,
                    mime_type=image.mime_type,
                    width=image.width,
                    height=image.height,
                    encoder=embedding.encoder,
                    model_name=embedding.model_name,
                    pretrained=embedding.pretrained,
                    dimension=embedding.dimension,
                    cosine_distance=cosine_distance,
                    similarity_percent=cosine_distance_to_percent(cosine_distance),
                    sku=image.sku,
                    product_name=image.product_name,
                    size=image.size,
                    price=image.price,
                    room=image.room,
                    style=image.style,
                    color=image.color,
                    stock=image.stock,
                    selling_point=image.selling_point,
                )
            )
        return results
