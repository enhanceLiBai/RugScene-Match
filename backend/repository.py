"""图片与模型向量的持久化仓库，不负责事务提交或回滚。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Final

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.encoders.base import EncoderIdentity
from backend.models import ImageEmbedding, ImageRecord


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


_VECTOR_DTYPE: Final = np.dtype(np.float32)


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
    return values


def _relative_posix_path(stored_path: str) -> str:
    """只接受相对于项目根目录的可移植路径，仓库绝不读取本地文件。"""
    normalized = stored_path.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        raise ValueError("图片存储路径必须是相对于项目根目录的路径。")
    if PureWindowsPath(stored_path).is_absolute():
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

    def image_count(self) -> int:
        """返回当前事务可见的图片数。"""
        return len(self.list_images())

    def embedding_count(self, image_id: int | None = None) -> int:
        """返回当前事务可见的向量数，可按图片过滤。"""
        statement = select(ImageEmbedding)
        if image_id is not None:
            statement = statement.where(ImageEmbedding.image_id == image_id)
        return len(list(self._session.scalars(statement)))

    def upsert_embedding(self, image: ImageRecord, identity: EncoderIdentity, embedding: np.ndarray) -> None:
        """新增或更新指定图片与完整模型身份对应的唯一向量。"""
        vector = _validated_vector(identity, embedding)
        existing = self._session.scalar(
            select(ImageEmbedding).where(
                ImageEmbedding.image_id == image.id,
                ImageEmbedding.encoder == identity.encoder,
                ImageEmbedding.model_name == identity.model_name,
                ImageEmbedding.pretrained == identity.pretrained,
            )
        )
        if existing is None:
            self._session.add(
                ImageEmbedding(
                    image_id=image.id,
                    encoder=identity.encoder,
                    model_name=identity.model_name,
                    pretrained=identity.pretrained,
                    dimension=identity.dimension,
                    embedding=vector,
                )
            )
        else:
            existing.dimension = identity.dimension
            existing.embedding = vector
        self._session.flush()

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
                )
            )
        return results
