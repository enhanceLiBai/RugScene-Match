# 前后端图库与图片检索集成 Implementation Plan

> 状态：已在 `codex/frontend-backend-integration` 分支实施完成，当前等待合并。
> 执行说明：下方复选框仅保留原始计划，不表示当前待办。除非用户明确要求重新实施，否则不得据此重复编码、补测、运行全量验证或继续寻找边缘缺陷。

> 历史执行方式：实施阶段曾按任务使用 subagent-driven-development / executing-plans；该要求现已结束。下方 checkbox 仅保留当时的计划格式。

**Goal:** 让客服通过 FastAPI 同源页面把买家秀及选填元数据写入后端、查看数据库图库，并上传客户图片执行 OpenCLIP/pgvector 相似检索。

**Architecture:** FastAPI 固定路由托管无构建步骤的前端，并提供幂等图库上传接口。图片元数据以 `images` 表的可空列保存，`LibraryService` 统一协调 CLI 与 HTTP 入库的校验、去重、文件落盘、向量生成和事务边界；前端通过独立 UMD API 客户端访问相对 `/api` 路径。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、PostgreSQL 16、pgvector、Pillow、OpenCLIP、原生 JavaScript、Node.js 内置测试运行器、pytest。

**Spec:** `docs/superpowers/specs/2026-09-06-frontend-backend-integration-design.md`

## Global Constraints

- 所有 Python 文件操作必须显式 `encoding="utf-8"`；PowerShell 跑 Python 前设置 `$env:PYTHONIOENCODING='utf-8'`。
- 新增或修改的必要代码注释使用简体中文，解释业务边界与关键取舍，不逐行复述代码。
- 图片仅保存到 `data/images/`，查询图不写文件或数据库。
- 九个商品元数据字段全部选填，且不参与当前向量相似度排序。
- 已有 PostgreSQL 数据必须通过幂等增量 schema 升级保留。
- HTTP 响应与日志不得暴露密码、数据库 URL、模型内部异常或本地绝对路径。
- 前端通过 FastAPI 同源访问，不增加 CORS，不新增 JavaScript 构建工具或包管理器。
- 不实现用户权限、编辑、删除、批量清空或反馈持久化。

## File Structure

- Modify: `backend/models.py` — 声明图片选填元数据列和价格约束。
- Modify: `backend/db.py` — 为已有 `images` 表幂等补列与约束。
- Modify: `backend/repository.py` — 定义元数据值对象、持久化更新并把元数据投影到图库和搜索行。
- Modify: `backend/services.py` — 新增内存上传入库用例并统一文件/事务清理。
- Modify: `backend/api.py` — 新增图库上传、扩展响应、固定静态路由。
- Create: `api-client.js` — 封装浏览器与 Node 共用的 HTTP API 客户端。
- Modify: `matcher-core.js` — 删除本地排序，保留纯展示与话术规则。
- Modify: `app.js` — 使用后端完成初始化、入库和搜索 DOM 流程。
- Modify: `index.html` — 加载 API 客户端并移除本地演示/清空入口。
- Modify: `styles.css` — 增加请求状态、错误和重试控件样式。
- Modify: `README.md` — 记录同源启动和后端数据边界。
- Modify: `tests/test_repository.py`、`tests/test_services.py`、`tests/test_api.py` — 覆盖持久层、服务和 HTTP 行为。
- Create: `tests/api-client.test.js` — 覆盖 FormData、路径和错误转换。
- Modify: `tests/matcher-core.test.js` — 覆盖后端响应的展示规则。

---

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

---

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

---

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

### Task 4: 前端 HTTP 客户端与展示契约

**Files:**
- Create: `api-client.js`
- Modify: `matcher-core.js`
- Create: `tests/api-client.test.js`
- Modify: `tests/matcher-core.test.js`

**Interfaces:**
- Produces: `CarpetApiClient.create({ fetchImpl, FormDataImpl })`。
- Produces: `listLibrary() -> Promise<LibraryResponse>`。
- Produces: `uploadLibraryImage(file, metadata) -> Promise<LibraryUploadResponse>`。
- Produces: `searchSimilar(file, topK = 5) -> Promise<SearchResponse>`。
- Produces: `CarpetMatcherCore.buildPresentation(item)` 和 `buildRecommendationScript(item)`，消费后端 snake_case 字段。

- [ ] **Step 1: 写 API 客户端请求测试**

在 `tests/api-client.test.js` 使用最小 fake fetch 和 Node 自带 `FormData`/`Blob`，断言：

```javascript
test('图库上传只发送图片和非空元数据', async () => {
  const calls = [];
  const client = createClient(async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ status: 'imported', image: { id: 1 } });
  });
  await client.uploadLibraryImage(new Blob(['image']), {
    product_name: '云朵地毯', sku: '', room: '客厅',
  });

  assert.equal(calls[0].url, '/api/library');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.body.get('product_name'), '云朵地毯');
  assert.equal(calls[0].options.body.has('sku'), false);
});
```

另测 `GET /api/library`、`POST /api/search?top_k=5`、JSON 错误 detail 和非 JSON 错误的中文转换。

- [ ] **Step 2: 运行 JavaScript 测试并确认 RED**

Run: `node --test tests\api-client.test.js tests\matcher-core.test.js`

Expected: FAIL，原因是 `api-client.js` 不存在，且展示函数仍消费 camelCase/本地特征。

- [ ] **Step 3: 实现 UMD API 客户端**

`api-client.js` 使用与 `matcher-core.js` 一致的 UMD 形式。请求助手必须先检查 `response.ok`，仅在响应 content-type 为 JSON 时解析 `detail`，其他失败统一抛出：

```javascript
class ApiError extends Error {}

async function requestJson(fetchImpl, url, options) {
  const response = await fetchImpl(url, options);
  const isJson = (response.headers.get('content-type') || '').includes('application/json');
  const payload = isJson ? await response.json() : null;
  if (!response.ok) throw new ApiError(payload?.detail || '服务响应异常，请稍后重试。');
  if (!isJson) throw new ApiError('服务响应异常，请稍后重试。');
  return payload;
}
```

上传 FormData 不手工设置 `Content-Type`，由浏览器生成 multipart boundary。

- [ ] **Step 4: 更新纯展示函数**

删除 `visualScore()` 和 `rankBySimilarity()`；`buildPresentation()` 使用 `product_name`、`original_name`、`selling_point` 等后端字段，价格使用服务端返回值直接展示。推荐理由改为“OpenCLIP 图片向量相似”。

- [ ] **Step 5: 运行 JavaScript 测试并确认 GREEN**

Run: `node --test tests\api-client.test.js tests\matcher-core.test.js`

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add api-client.js matcher-core.js tests/api-client.test.js tests/matcher-core.test.js
git commit -m "feat: add frontend api client"
```

---

### Task 5: 页面迁移到后端数据源

**Files:**
- Modify: `index.html`
- Modify: `app.js`
- Modify: `styles.css`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `CarpetApiClient.create()` 与 `CarpetMatcherCore` 展示函数。
- Produces: 页面初始化、图库上传、图库刷新和图片检索的完整 DOM 流程。

- [ ] **Step 1: 扩展页面契约测试并确认 RED**

在 `tests/test_api.py::test_root_serves_frontend_and_only_registered_assets` 增加 HTML 断言：

```python
html = client.get("/").text
assert '<script src="api-client.js"></script>' in html
assert 'id="seedButton"' not in html
assert 'id="clearButton"' not in html
assert 'id="entryStatus"' in html
assert 'id="reloadLibraryButton"' in html
```

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_api.py::test_root_serves_frontend_and_only_registered_assets -q`

Expected: FAIL，原因是页面仍含本地演示/清空控件且缺少状态元素。

- [ ] **Step 2: 修改页面结构**

移除“载入演示数据”和“清空本机数据”。在 `app.js` 前加载 `api-client.js`；为图库重试、入库状态和按钮忙碌文案增加稳定 ID。保留九个字段的现有输入 ID，提交时映射到后端 snake_case。

- [ ] **Step 3: 重写 `app.js` 数据流**

删除 IndexedDB、`makeFeature()`、seed 和 clear 逻辑。实现以下小函数并保持中文业务注释：

```javascript
async function refreshLibrary() {}
function renderLibrary(images) {}
function renderResults(payload) {}
function readEntryMetadata() {}
function setBusy(button, busy, busyText) {}
function showEntryStatus(message, kind) {}
```

初始化时调用 `refreshLibrary()`；入库提交调用 `api.uploadLibraryImage()`；匹配按钮调用 `api.searchSimilar(queryFile, 5)`。所有后端文本通过 `textContent` 写入 DOM，不拼接进 `innerHTML`。

- [ ] **Step 4: 增加忙碌、错误和重试样式**

在 `styles.css` 增加 `.status-message`、`.status-message.error`、`.retry-button`、`button:disabled`，并确保移动端按钮仍为整行布局。

- [ ] **Step 5: 验证静态语法与页面契约**

Run: `node --check app.js`

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_api.py::test_root_serves_frontend_and_only_registered_assets -q`

Expected: 两条命令均 PASS。

- [ ] **Step 6: 提交**

```powershell
git add index.html app.js styles.css tests/test_api.py
git commit -m "feat: connect web ui to backend"
```

---

### Task 6: 文档、全量验证与真实同源冒烟

**Files:**
- Modify: `README.md`

**Interfaces:**
- Produces: 用户可直接执行的初始化、启动、入库、检索和验证说明。

- [ ] **Step 1: 更新 README**

删除“双击 `index.html`”、IndexedDB 和九宫格本地匹配说明。明确执行：

```powershell
.venv\Scripts\python.exe -m backend.cli init-db
.venv\Scripts\python.exe -m backend.cli serve
```

然后访问 `http://127.0.0.1:8000/`。说明元数据选填、不影响向量排序，图片和数据分别保存于 `data/images` 与 PostgreSQL。

- [ ] **Step 2: 运行快速静态与依赖验证**

Run: `node --check api-client.js`

Run: `node --check matcher-core.js`

Run: `node --check app.js`

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pip check`

Expected: 所有命令退出码为 0。

- [ ] **Step 3: 运行全量自动化测试**

Run: `node --test tests\api-client.test.js tests\matcher-core.test.js`

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests -m "not model" -q`

Expected: 全部 PASS；模型测试仅因 marker 表达式正常跳过。

- [ ] **Step 4: 初始化升级后的真实 schema**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m backend.cli init-db`

Expected: 输出“数据库和表结构已初始化。”；重复运行结果相同。

- [ ] **Step 5: 启动服务并完成 HTTP 同源冒烟**

在后台运行 `.venv\Scripts\python.exe -m backend.cli serve`，依次请求：

```text
GET /
GET /styles.css
GET /api/library
GET /health
```

Expected: 均返回 2xx；根页面引用同源 `api-client.js` 和 `app.js`，图库响应为数据库数据。

如项目内已有适合的非敏感测试图片，通过页面上传一张买家秀并执行一次查询；不得把用户现有图片或数据库记录作为清理目标。若真实 OpenCLIP 首次加载需要下载而当前环境无网络，只报告模型冒烟未执行，不影响已通过的 fake encoder 自动化契约。

- [ ] **Step 6: 检查变更与中文注释**

Run: `git diff --check`

人工确认新增关键逻辑使用必要的简体中文注释，且不存在过量、过期或与实现不一致的注释。

- [ ] **Step 7: 提交**

```powershell
git add README.md
git commit -m "docs: document integrated web workflow"
```
