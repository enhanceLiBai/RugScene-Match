# Review package Task 1

Base: d69a772d776fefe94d2da51b6d54051f4053ba42
Head: 54b21b5

## Commits

```
54b21b5 feat: add product image associations

```

## Stat

```
 backend/models.py        | 48 ++++++++++++++++++++++++++-
 backend/repository.py    | 84 ++++++++++++++++++++++++++++++++++++++++++++++--
 tests/test_repository.py | 72 +++++++++++++++++++++++++++++++++++++++++
 3 files changed, 201 insertions(+), 3 deletions(-)

```

## Diff

```diff
diff --git a/backend/models.py b/backend/models.py
index 2f42a8f..9b69b0e 100644
--- a/backend/models.py
+++ b/backend/models.py
@@ -1,18 +1,18 @@
 """PostgreSQL 中图片元数据和 pgvector 向量的 SQLAlchemy 模型。"""

 from __future__ import annotations

 from datetime import datetime

 from pgvector.sqlalchemy import VECTOR
-from sqlalchemy import BigInteger, CHAR, CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
+from sqlalchemy import BigInteger, Boolean, CHAR, CheckConstraint, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
 from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


 class Base(DeclarativeBase):
     """本项目持久层模型的共同元数据。"""


 class ImageRecord(Base):
     """保存图片文件元数据；原始图片二进制仅保存在项目图库目录。"""

@@ -29,20 +29,25 @@ class ImageRecord(Base):
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
+    product_images: Mapped[list["ProductImage"]] = relationship(
+        back_populates="image",
+        cascade="all, delete-orphan",
+        passive_deletes=True,
+    )


 class ImageEmbedding(Base):
     """保存某一模型为图片产生的向量，禁止跨模型空间比较。"""

     __tablename__ = "image_embeddings"
     __table_args__ = (
         UniqueConstraint("image_id", "encoder", "model_name", "pretrained", name="uq_embedding_model_identity"),
         CheckConstraint("dimension > 0", name="ck_image_embeddings_dimension_positive"),
     )
@@ -53,10 +58,51 @@ class ImageEmbedding(Base):
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
+
+
+class ProductImage(Base):
+    """关联商品与原始图片，保留主图历史并标记当前启用主图。"""
+
+    __tablename__ = "product_images"
+    __table_args__ = (
+        UniqueConstraint("product_id", "image_id", "image_role", name="uq_product_image_role"),
+        CheckConstraint("image_role IN ('product_main', 'buyer_sofa')", name="ck_product_images_role"),
+        CheckConstraint("source_column IN ('K', 'L', 'M', 'N')", name="ck_product_images_source_column"),
+    )
+
+    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
+    product_id: Mapped[str] = mapped_column(Text, nullable=False)
+    image_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("images.id", ondelete="CASCADE"), nullable=False)
+    image_role: Mapped[str] = mapped_column(Text, nullable=False)
+    source_column: Mapped[str] = mapped_column(CHAR(1), nullable=False)
+    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
+    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
+    image: Mapped[ImageRecord] = relationship(back_populates="product_images")
+
+
+class ImportJob(Base):
+    """保存 Excel 导入的进度、结果汇总与错误信息。"""
+
+    __tablename__ = "import_jobs"
+
+    job_id: Mapped[str] = mapped_column(CHAR(32), primary_key=True)
+    original_name: Mapped[str] = mapped_column(Text, nullable=False)
+    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="uploading")
+    processed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
+    total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
+    summary_json: Mapped[str | None] = mapped_column(Text)
+    error_message: Mapped[str | None] = mapped_column(Text)
+    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
+    updated_at: Mapped[datetime] = mapped_column(
+        DateTime(timezone=True),
+        nullable=False,
+        server_default=func.now(),
+        onupdate=func.now(),
+    )
diff --git a/backend/repository.py b/backend/repository.py
index d110fe9..fab89c4 100644
--- a/backend/repository.py
+++ b/backend/repository.py
@@ -1,26 +1,26 @@
 """图片与模型向量的持久化仓库，不负责事务提交或回滚。"""

 from __future__ import annotations

 from dataclasses import dataclass
 from pathlib import PurePosixPath, PureWindowsPath
 import re
 from typing import Final

 import numpy as np
-from sqlalchemy import func, select
+from sqlalchemy import func, select, update
 from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.orm import Session

 from backend.encoders.base import EncoderIdentity
-from backend.models import ImageEmbedding, ImageRecord
+from backend.models import ImageEmbedding, ImageRecord, ImportJob, ProductImage


 @dataclass(frozen=True)
 class SearchRow:
     """相似度查询的完整结果，供后续 CLI 和 API 直接映射输出。"""

     image_id: int
     original_name: str
     stored_path: str
     sha256: str
@@ -125,20 +125,100 @@ class ImageRepository:
         return record

     def list_images(self) -> list[ImageRecord]:
         """按主键稳定列出图片，方便后续图库接口分页扩展。"""
         return list(self._session.scalars(select(ImageRecord).order_by(ImageRecord.id.asc())))

     def find_by_id(self, image_id: int) -> ImageRecord | None:
         """按主键查找图片元数据，供受控图库文件读取使用。"""
         return self._session.get(ImageRecord, image_id)

+    def link_product_image(
+        self,
+        product_id: str,
+        image: ImageRecord,
+        image_role: str,
+        source_column: str,
+    ) -> ProductImage:
+        """幂等关联商品与图片，重复导入复用已有关联记录。"""
+        statement = insert(ProductImage).values(
+            product_id=product_id,
+            image_id=image.id,
+            image_role=image_role,
+            source_column=source_column,
+        )
+        statement = statement.on_conflict_do_nothing(
+            index_elements=(ProductImage.product_id, ProductImage.image_id, ProductImage.image_role)
+        )
+        self._session.execute(statement)
+        self._session.flush()
+        link = self._session.scalar(
+            select(ProductImage).where(
+                ProductImage.product_id == product_id,
+                ProductImage.image_id == image.id,
+                ProductImage.image_role == image_role,
+            )
+        )
+        if link is None:
+            raise RuntimeError("商品图片关联写入后未找到记录。")
+        return link
+
+    def set_current_product_main(
+        self,
+        product_id: str,
+        image: ImageRecord,
+        source_column: str = "K",
+    ) -> ProductImage:
+        """将指定图片设为当前主图，同时停用该商品此前所有主图。"""
+        link = self.link_product_image(product_id, image, "product_main", source_column)
+        self._session.execute(
+            update(ProductImage)
+            .where(
+                ProductImage.product_id == product_id,
+                ProductImage.image_role == "product_main",
+            )
+            .values(is_active=False)
+        )
+        self._session.execute(update(ProductImage).where(ProductImage.id == link.id).values(is_active=True))
+        self._session.flush()
+        return link
+
+    def list_product_images(self, product_id: str) -> list[ProductImage]:
+        """按关联创建顺序读取一个商品的全部主图和买家秀。"""
+        statement = select(ProductImage).where(ProductImage.product_id == product_id).order_by(ProductImage.id.asc())
+        return list(self._session.scalars(statement))
+
+    def create_import_job(self, job_id: str, original_name: str) -> ImportJob:
+        """新建处于上传状态的 Excel 导入任务。"""
+        job = ImportJob(job_id=job_id, original_name=original_name)
+        self._session.add(job)
+        self._session.flush()
+        return job
+
+    def find_import_job(self, job_id: str) -> ImportJob | None:
+        """按任务标识读取导入状态，供轮询接口使用。"""
+        return self._session.get(ImportJob, job_id)
+
+    def update_import_job(self, job_id: str, **values: object) -> ImportJob:
+        """更新导入任务的受控状态字段，拒绝改写任务身份和原始文件名。"""
+        allowed_fields = {"status", "processed", "total", "summary_json", "error_message"}
+        invalid_fields = set(values) - allowed_fields
+        if invalid_fields:
+            raise ValueError("导入任务包含不允许更新的字段。")
+        job = self.find_import_job(job_id)
+        if job is None:
+            raise ValueError("导入任务不存在。")
+        for field, value in values.items():
+            setattr(job, field, value)
+        self._session.flush()
+        return job
+
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
diff --git a/tests/test_repository.py b/tests/test_repository.py
index 8972057..ecdcbc5 100644
--- a/tests/test_repository.py
+++ b/tests/test_repository.py
@@ -295,20 +295,92 @@ def test_embedding_count_uses_database_count_query() -> None:
     """向量统计不应加载全部向量对象。"""
     session = MagicMock()
     session.scalar.return_value = 3

     count = ImageRepository(session).embedding_count(image_id=123)

     assert count == 3
     session.scalars.assert_not_called()


+def test_product_image_links_share_product_and_ignore_duplicate_association(repository: ImageRepository) -> None:
+    """重复导入同一单元格图片不能重复关联，且四张图片归属同一商品。"""
+    product_id = "SKU-1001"
+    main_image = add_test_image(repository, "main.jpg")
+    sofa_images = [add_test_image(repository, f"sofa-{index}.jpg") for index in range(1, 4)]
+
+    main_link = repository.link_product_image(product_id, main_image, "product_main", "K")
+    sofa_links = [
+        repository.link_product_image(product_id, image, "buyer_sofa", column)
+        for image, column in zip(sofa_images, ("L", "M", "N"), strict=True)
+    ]
+    duplicate_link = repository.link_product_image(product_id, sofa_images[0], "buyer_sofa", "L")
+
+    links = repository.list_product_images(product_id)
+
+    assert duplicate_link.id == sofa_links[0].id
+    assert [(link.product_id, link.image_id, link.image_role, link.source_column) for link in links] == [
+        (product_id, main_image.id, "product_main", "K"),
+        (product_id, sofa_images[0].id, "buyer_sofa", "L"),
+        (product_id, sofa_images[1].id, "buyer_sofa", "M"),
+        (product_id, sofa_images[2].id, "buyer_sofa", "N"),
+    ]
+    assert main_link.is_active is True
+
+
+def test_set_current_product_main_disables_previous_main(repository: ImageRepository) -> None:
+    """导入新主图时，旧主图必须保留关联但不再参与当前商品展示。"""
+    product_id = "SKU-1002"
+    old_main = add_test_image(repository, "old-main.jpg")
+    new_main = add_test_image(repository, "new-main.jpg")
+
+    old_link = repository.set_current_product_main(product_id, old_main)
+    new_link = repository.set_current_product_main(product_id, new_main)
+    links = repository.list_product_images(product_id)
+
+    assert old_link.is_active is False
+    assert new_link.is_active is True
+    assert [(link.image_id, link.is_active) for link in links if link.image_role == "product_main"] == [
+        (old_main.id, False),
+        (new_main.id, True),
+    ]
+
+
+def test_import_job_can_be_created_updated_and_found(repository: ImageRepository) -> None:
+    """导入进度和汇总结果必须在同一任务记录中持续可读。"""
+    job_id = uuid.uuid4().hex
+
+    created = repository.create_import_job(job_id, "catalog.xlsx")
+    updated = repository.update_import_job(
+        job_id,
+        status="completed",
+        processed=4,
+        total=4,
+        summary_json='{"linked": 4}',
+        error_message=None,
+    )
+    found = repository.find_import_job(job_id)
+
+    assert created.status == "uploading"
+    assert created.processed == 0
+    assert created.total == 0
+    assert updated.status == "completed"
+    assert (updated.processed, updated.total, updated.summary_json, updated.error_message) == (
+        4,
+        4,
+        '{"linked": 4}',
+        None,
+    )
+    assert found is not None
+    assert found.job_id == job_id
+
+
 def test_cosine_distance_percentage_clamps_rounds_and_rejects_non_finite_values() -> None:
     """对 pgvector 返回值统一裁剪，避免边界浮点误差传递给 API。"""
     assert cosine_distance_to_percent(-0.1) == 100.0
     assert cosine_distance_to_percent(0.292893218) == 70.71
     assert cosine_distance_to_percent(2.0) == 0.0
     with pytest.raises(ValueError, match="有限"):
         cosine_distance_to_percent(float("nan"))


 def test_database_constraints_and_cascade_apply_inside_rollback_transaction(

```
