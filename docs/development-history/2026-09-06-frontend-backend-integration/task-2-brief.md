### Task 2: 统一内存图片入库服务

**Files:**
- Modify: `backend/services.py`
- Test: `tests/test_services.py`

**Interfaces:**
- Consumes: `validate_image_bytes(data: bytes, original_name: str) -> ValidatedImage`。
- Consumes: `ImageMetadata`、`ImageRepository.update_metadata()`。
- Produces: `LibraryService.import_bytes(data: bytes, original_name: str, metadata: ImageMetadata) -> ImportResult`。
- Produces: `ImportResult.image_id: int | None`，失败时为 `None`。

- [ ] **Step 1: 写新图与重复图服务测试**

新增真实 PNG 字节用例：

```python
def test_import_bytes_persists_metadata_and_duplicate_updates_nonblank_fields(service, repository):
    data = png_bytes("red")
    first = service.import_bytes(data, "buyer.png", ImageMetadata(product_name="云朵", sku="CT-1"))
    second = service.import_bytes(data, "buyer.png", ImageMetadata(room="客厅"))

    assert first.status is ImportStatus.IMPORTED
    assert second.status is ImportStatus.DUPLICATE
    assert first.image_id == second.image_id
    image = repository.find_by_id(first.image_id)
    assert image.product_name == "云朵"
    assert image.sku == "CT-1"
    assert image.room == "客厅"
```

再断言编码失败时数据库回滚，且仅删除本次创建的图库文件。

- [ ] **Step 2: 运行测试并确认 RED**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_services.py -q`

Expected: FAIL，原因是 `import_bytes` 或 `ImportResult.image_id` 不存在。

- [ ] **Step 3: 实现共享 `_import_validated` 工作单元**

把 `_import_one()` 的核心逻辑提取为：

```python
def _import_validated(
    self,
    validated: ValidatedImage,
    source_label: Path,
    metadata: ImageMetadata,
) -> ImportResult:
    ...
```

`import_path()` 传入空 `ImageMetadata()`；`import_bytes()` 在事务捕获范围外调用 `validate_image_bytes()`，让 `InvalidImageError` 保持可识别，再进入相同工作单元。重复图片必须先更新非空元数据，再根据当前模型向量是否存在决定 `DUPLICATE` 或 `EMBEDDING_ADDED`，最后统一提交。

- [ ] **Step 4: 运行服务测试并确认 GREEN**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_services.py -q`

Expected: PASS，CLI 的既有导入、目录容错和检索行为保持通过。

- [ ] **Step 5: 提交**

```powershell
git add backend/services.py tests/test_services.py
git commit -m "feat: import uploaded library images"
```
