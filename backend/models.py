"""PostgreSQL 中图片元数据和 pgvector 向量的 SQLAlchemy 模型。"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import BigInteger, CHAR, CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """本项目持久层模型的共同元数据。"""


class ImageRecord(Base):
    """保存图片文件元数据；原始图片二进制仅保存在项目图库目录。"""

    __tablename__ = "images"
    __table_args__ = (
        CheckConstraint("width > 0", name="ck_images_width_positive"),
        CheckConstraint("height > 0", name="ck_images_height_positive"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_images_sha256_lower_hex"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    embeddings: Mapped[list["ImageEmbedding"]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ImageEmbedding(Base):
    """保存某一模型为图片产生的向量，禁止跨模型空间比较。"""

    __tablename__ = "image_embeddings"
    __table_args__ = (
        UniqueConstraint("image_id", "encoder", "model_name", "pretrained", name="uq_embedding_model_identity"),
        CheckConstraint("dimension > 0", name="ck_image_embeddings_dimension_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
    )
    encoder: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    pretrained: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[object] = mapped_column(VECTOR(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    image: Mapped[ImageRecord] = relationship(back_populates="embeddings")
