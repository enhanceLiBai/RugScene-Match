### Task 1: 可空元数据模型与增量 schema

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/db.py`
- Modify: `backend/repository.py`
- Test: `tests/test_repository.py`

**Interfaces:**
- Produces: `ImageMetadata`，字段为 `sku`、`product_name`、`size`、`price`、`room`、`style`、`color`、`stock`、`selling_point`。
- Produces: `ImageRepository.update_metadata(image: ImageRecord, metadata: ImageMetadata) -> None`。
- Produces: 带同名元数据字段的 `LibraryRow` 与 `SearchRow`。

- [ ] **Step 1: 写元数据持久化和空值保留测试**

在 `tests/test_repository.py` 新增：

```python
from decimal import Decimal
from backend.repository import ImageMetadata


def test_repository_persists_optional_metadata_and_blank_update_keeps_existing(repository):
    image = add_test_image(repository)
    repository.update_metadata(
        image,
        ImageMetadata(product_name="云朵地毯", price=Decimal("899.00"), room="客厅"),
    )
    repository.update_metadata(image, ImageMetadata(product_name=None, room="卧室"))

    row = repository.list_library()[0]
    assert row.product_name == "云朵地毯"
    assert row.price == Decimal("899.00")
    assert row.room == "卧室"
    assert row.sku is None
```

同时扩展现有 search fixture，断言 `SearchRow` 返回相同元数据。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_repository.py -q`

Expected: FAIL，原因是 `ImageMetadata` 或 `update_metadata` 尚不存在。

- [ ] **Step 3: 实现 ORM 列和值对象**

在 `backend/models.py` 使用 `Numeric(12, 2)` 和可空 `Text` 列，并添加：

```python
CheckConstraint("price IS NULL OR price >= 0", name="ck_images_price_nonnegative")
```

在 `backend/repository.py` 定义：

```python
@dataclass(frozen=True)
class ImageMetadata:
    sku: str | None = None
    product_name: str | None = None
    size: str | None = None
    price: Decimal | None = None
    room: str | None = None
    style: str | None = None
    color: str | None = None
    stock: str | None = None
    selling_point: str | None = None
```

`update_metadata()` 只给值不为 `None` 的字段赋值；`LibraryRow`、`SearchRow` 及其查询映射包含全部字段。

- [ ] **Step 4: 实现幂等旧库升级**

在 `backend/db.py` 增加 `_upgrade_image_metadata_columns(connection)`，逐条执行固定 SQL：

```sql
ALTER TABLE images ADD COLUMN IF NOT EXISTS sku TEXT;
ALTER TABLE images ADD COLUMN IF NOT EXISTS product_name TEXT;
ALTER TABLE images ADD COLUMN IF NOT EXISTS size TEXT;
ALTER TABLE images ADD COLUMN IF NOT EXISTS price NUMERIC(12, 2);
ALTER TABLE images ADD COLUMN IF NOT EXISTS room TEXT;
ALTER TABLE images ADD COLUMN IF NOT EXISTS style TEXT;
ALTER TABLE images ADD COLUMN IF NOT EXISTS color TEXT;
ALTER TABLE images ADD COLUMN IF NOT EXISTS stock TEXT;
ALTER TABLE images ADD COLUMN IF NOT EXISTS selling_point TEXT;
```

检查约束不存在且现有价格均合法后，再添加 `ck_images_price_nonnegative`。从 `create_database_and_schema()` 调用升级函数。

- [ ] **Step 5: 运行仓库测试并确认 GREEN**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_repository.py -q`

Expected: PASS；重复 schema 初始化不丢失既有图片记录。

- [ ] **Step 6: 提交**

```powershell
git add backend/models.py backend/db.py backend/repository.py tests/test_repository.py
git commit -m "feat: persist optional library metadata"
```
