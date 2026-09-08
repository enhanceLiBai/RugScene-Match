### Task 3: 图库上传、元数据响应与同源静态路由

**Files:**
- Modify: `backend/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `POST /api/library` multipart 接口。
- Produces: 带九个可空元数据字段的 `LibraryImageResponse` 与 `SearchResultResponse`。
- Produces: `create_app(..., frontend_root: Path | None = None) -> FastAPI`，以及固定 `/`、`/styles.css`、`/matcher-core.js`、`/api-client.js`、`/app.js` 静态路由。

- [ ] **Step 1: 写图库上传和重复补充元数据测试**

在 `tests/test_api.py` 新增：

```python
def test_library_upload_persists_image_vector_and_optional_metadata(client, repository):
    response = client.post(
        "/api/library",
        files={"image": ("buyer.png", png_bytes(), "image/png")},
        data={"product_name": "云朵地毯", "price": "899.00", "room": "客厅"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "imported"
    assert response.json()["image"]["product_name"] == "云朵地毯"
    assert repository.image_count() == 1
    assert repository.embedding_count() == 1
```

第二次上传相同字节、只提供 `style`，断言状态为 `duplicate`、图片数不增长、原有字段保留且 `style` 被补充。

- [ ] **Step 2: 写扩展列表、搜索和静态入口测试**

扩展现有断言以覆盖九个字段，并新增：

```python
def test_root_serves_frontend_and_only_registered_assets(client):
    assert client.get("/").status_code == 200
    assert "api-client.js" in client.get("/").text
    assert client.get("/styles.css").headers["content-type"].startswith("text/css")
    assert client.get("/not-registered.env").status_code == 404
```

另测 20 MiB 超限、损坏图片和负价格返回 400，且响应不含底层错误。

- [ ] **Step 3: 运行 API 测试并确认 RED**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_api.py -q`

Expected: FAIL，原因是上传端点、元数据响应字段和根页面尚不存在。

- [ ] **Step 4: 实现请求规范化与响应模型**

使用 FastAPI `Form` 接收可空字符串，集中规范化：

```python
def _optional_text(value: str | None) -> str | None:
    cleaned = value.strip() if value is not None else ""
    return cleaned or None


def _optional_price(value: str | None) -> Decimal | None:
    cleaned = _optional_text(value)
    if cleaned is None:
        return None
    price = Decimal(cleaned)
    if price < 0 or price.as_tuple().exponent < -2:
        raise ValueError("参考价必须是非负且最多两位小数的数字。")
    return price
```

所有图片响应通过集中映射函数生成，避免上传、列表和搜索字段漂移。响应中的 `price` 类型固定为 `float | None`，持久层仍使用 `Decimal` 保持两位小数约束。

- [ ] **Step 5: 实现上传端点和静态路由**

`POST /api/library` 复用每请求 session 构造 `LibraryService`，读取最多 `MAX_UPLOAD_BYTES + 1`，调用 `import_bytes()`。图片和价格在进入服务事务前完成校验，校验异常映射为 400；服务工作单元返回 `FAILED` 时映射为 503。静态路由默认从 `backend/api.py` 的父项目目录读取；`frontend_root` 仅供测试或嵌入式调用显式注入，图库目录仍独立使用 `Settings.project_root`，避免测试临时图库改变静态资产根目录。

- [ ] **Step 6: 运行 API 及全部 Python 测试**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests -m "not model" -q`

Expected: PASS，无未处理异常或警告。

- [ ] **Step 7: 提交**

```powershell
git add backend/api.py tests/test_api.py
git commit -m "feat: expose library upload and web frontend"
```

---
