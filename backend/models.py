"""PostgreSQL 中图片元数据和 pgvector 向量的 SQLAlchemy 模型。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import BigInteger, Boolean, CHAR, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, Text, UniqueConstraint, func
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
        CheckConstraint("price IS NULL OR price >= 0", name="ck_images_price_nonnegative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    sku: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    size: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    room: Mapped[str | None] = mapped_column(Text, nullable=True)
    style: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    stock: Mapped[str | None] = mapped_column(Text, nullable=True)
    selling_point: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    embeddings: Mapped[list["ImageEmbedding"]] = relationship(
        back_populates="image",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    product_images: Mapped[list["ProductImage"]] = relationship(
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


class ProductImage(Base):
    """关联商品与原始图片，保留主图历史并标记当前启用主图。"""

    __tablename__ = "product_images"
    __table_args__ = (
        UniqueConstraint("product_id", "image_id", "image_role", name="uq_product_image_role"),
        CheckConstraint("image_role IN ('product_main', 'buyer_sofa')", name="ck_product_images_role"),
        CheckConstraint("source_column IN ('K', 'L', 'M', 'N')", name="ck_product_images_source_column"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(Text, nullable=False)
    image_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("images.id", ondelete="CASCADE"), nullable=False)
    image_role: Mapped[str] = mapped_column(Text, nullable=False)
    source_column: Mapped[str] = mapped_column(CHAR(1), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    image: Mapped[ImageRecord] = relationship(back_populates="product_images")


class SceneLabel(Base):
    __tablename__ = "scene_labels"
    image_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("images.id"), primary_key=True)
    model: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    labels_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ImportJob(Base):
    """保存 Excel 导入的进度、结果汇总与错误信息。"""

    __tablename__ = "import_jobs"

    job_id: Mapped[str] = mapped_column(CHAR(32), primary_key=True)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="uploading")
    processed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    summary_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
