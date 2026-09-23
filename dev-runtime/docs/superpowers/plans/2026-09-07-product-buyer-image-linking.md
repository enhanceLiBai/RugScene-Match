# 商品主图与买家秀关联检索 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 复用现有前后端，实现腾讯文档 Excel 增量导入、商品主图与买家秀沙发图关联、场景检索及按商品 ID 去重展示。

**Architecture:** 使用标准库 `zipfile` 与流式 XML 解析器直接读取腾讯文档导出的 XLSX 图片锚点，不加载完整工作簿或转码图片。现有图片表和向量表继续负责文件与向量，新关联表连接商品 ID、主图和买家秀，技术任务表保存后台导入进度；搜索只召回买家秀并按商品 ID 聚合。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、PostgreSQL、pgvector、Pillow、OpenCLIP、原生 HTML/CSS/JavaScript、pytest。

**Spec:** `docs/superpowers/specs/2026-09-07-product-buyer-image-linking-design.md`

## Global Constraints

- 只处理“地毯图片”工作表的 F、K、L、M、N 列；J 与 O–Q 不进入推荐链路。
- F 为商品 ID，K 为 `product_main`，L–N 为 `buyer_sofa`。
- 客户查询图只在内存中处理，不持久化。
- 前端必须复用现有 `index.html`、`app.js`、`styles.css` 和推荐卡片，不引入前端框架。
- XLSX 上传必须流式写入 `data/import_jobs/<job_id>/`，任务结束后删除临时 Excel。
- 图片必须按工作簿内原始字节保存，不截图、不转码。
- 重复图片按 SHA-256 复用；旧买家秀不因新版 Excel 缺失而自动删除。
- 最终结果按商品 ID 去重，每个商品只保留相似度最高的买家秀。
- 所有 Python 文件操作显式使用 `encoding='utf-8'`；运行 Python 前设置 `PYTHONIOENCODING=utf-8`。
- 只运行本功能直接相关的最小测试，不执行完整回归、压力测试或探索性缺陷搜索。

---

### Task 1: 商品图片关联与导入任务持久层

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/repository.py`
- Test: `tests/test_repository.py`

**Interfaces:**
- Produces: `ProductImage`, `ImportJob` SQLAlchemy 模型。
- Produces: `ImageRepository.link_product_image(...) -> ProductImage`。
- Produces: `ImageRepository.set_current_product_main(...) -> ProductImage`。
- Produces: `ImageRepository.create_import_job(job_id: str, original_name: str) -> ImportJob`。
- Produces: `ImageRepository.update_import_job(job_id: str, **values: object) -> ImportJob`。

- [ ] **Step 1: 写数据库行为测试**

在 `tests/test_repository.py` 增加测试，创建同一商品的一张主图和三张买家秀，断言四条关联共享同一 `product_id`；再次关联相同图片不会产生重复记录；更换主图后只有新主图的 `is_active=True`；任务状态和计数可以创建、更新并按 ID 读取。

```python
def test_product_images_link_one_main_and_multiple_buyer_images(repository):
    main = add_test_image(repository, "main.jpg")
    buyers = [add_test_image(repository, f"buyer-{i}.jpg") for i in range(3)]
    repository.set_current_product_main("714161460085", main, "K")
    for column, image in zip(("L", "M", "N"), buyers, strict=True):
        repository.link_product_image("714161460085", image, "buyer_sofa", column)
    repository._session.flush()
    links = repository.list_product_images("714161460085")
    assert [(link.image_role, link.source_column) for link in links] == [
        ("product_main", "K"), ("buyer_sofa", "L"),
        ("buyer_sofa", "M"), ("buyer_sofa", "N"),
    ]
```

- [ ] **Step 2: 运行新增持久层测试并确认失败**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_repository.py -k "product_image or import_job" -q`

Expected: FAIL，原因是模型和仓库接口尚不存在。

- [ ] **Step 3: 实现最小模型**

在 `backend/models.py` 新增：

```python
class ProductImage(Base):
    __tablename__ = "product_images"
    __table_args__ = (
        UniqueConstraint("product_id", "image_id", "image_role", name="uq_product_image_role"),
        CheckConstraint("image_role IN ('product_main', 'buyer_sofa')", name="ck_product_images_role"),
        CheckConstraint("source_column IN ('K', 'L', 'M', 'N')", name="ck_product_images_source_column"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), nullable=False)
    image_role: Mapped[str] = mapped_column(Text, nullable=False)
    source_column: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

class ImportJob(Base):
    __tablename__ = "import_jobs"
    job_id: Mapped[str] = mapped_column(CHAR(32), primary_key=True)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
```

在仓库中以 PostgreSQL `ON CONFLICT DO NOTHING` 幂等创建关联；更新主图时先停用该商品旧 `product_main`，再启用新关联。任务更新只允许既定字段。

- [ ] **Step 4: 运行持久层目标测试**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_repository.py -k "product_image or import_job" -q`

Expected: PASS。

- [ ] **Step 5: 提交持久层改动**

```powershell
git add backend/models.py backend/repository.py tests/test_repository.py
git commit -m "feat: add product image associations"
```

---

### Task 2: 腾讯文档 XLSX 流式结构解析器

**Files:**
- Create: `backend/tencent_excel.py`
- Create: `tests/test_tencent_excel.py`

**Interfaces:**
- Produces: `WorkbookImage(product_id: str, role: str, source_column: str, filename: str, data: bytes)`。
- Produces: `iter_product_images(path: Path) -> Iterator[WorkbookImage]`。
- Produces: `WorkbookStructureError(ValueError)`，用于缺少工作表、关系文件或图片目标时给出可读错误。

- [ ] **Step 1: 创建最小 XLSX 测试夹具与失败测试**

测试使用 `zipfile.ZipFile` 在 `tmp_path` 生成只包含必要 XML、关系文件和四个小 PNG 的 XLSX，不使用 1.28 GB 真实文件。断言解析器只返回 K–N 图片、忽略 J/O，并将同一行 F 列值映射到四张图片。

```python
def test_iter_product_images_maps_same_row_and_selected_columns(tmp_path):
    workbook = make_tencent_xlsx(tmp_path, product_id="714161460085")
    rows = list(iter_product_images(workbook))
    assert [(row.product_id, row.role, row.source_column) for row in rows] == [
        ("714161460085", "product_main", "K"),
        ("714161460085", "buyer_sofa", "L"),
        ("714161460085", "buyer_sofa", "M"),
        ("714161460085", "buyer_sofa", "N"),
    ]
    assert all(row.data.startswith(b"\x89PNG") for row in rows)
```

另测目标工作表不存在时抛出 `WorkbookStructureError("找不到工作表：地毯图片")`，缺少 F 值的行不产生图片。

- [ ] **Step 2: 运行解析器测试并确认失败**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_tencent_excel.py -q`

Expected: FAIL，原因是 `backend.tencent_excel` 尚不存在。

- [ ] **Step 3: 实现针对腾讯导出结构的流式解析器**

`backend/tencent_excel.py` 使用 `zipfile.ZipFile`、`xml.etree.ElementTree.iterparse` 和关系文件完成以下步骤：

```python
@dataclass(frozen=True)
class WorkbookImage:
    product_id: str
    role: Literal["product_main", "buyer_sofa"]
    source_column: Literal["K", "L", "M", "N"]
    filename: str
    data: bytes

def iter_product_images(path: Path) -> Iterator[WorkbookImage]:
    """逐图读取目标工作表，单次只将一张图片解压到内存。"""
```

先读取小型的 `workbook.xml`、共享字符串和关系文件；再从目标 sheet 获取 F 列商品 ID，从 drawing 的 `oneCellAnchor/from` 获取图片行列，以 `blip r:embed` 解析图片关系。对每个 K–N 锚点只在 yield 前调用 `archive.read(media_path)`，不得一次读取全部媒体文件。

- [ ] **Step 4: 运行解析器目标测试**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_tencent_excel.py -q`

Expected: PASS。

- [ ] **Step 5: 提交解析器改动**

```powershell
git add backend/tencent_excel.py tests/test_tencent_excel.py
git commit -m "feat: parse Tencent workbook images"
```

---

### Task 3: Excel 增量导入服务与后台任务 API

**Files:**
- Modify: `.gitignore`
- Modify: `backend/config.py`
- Modify: `backend/image_assets.py`
- Create: `backend/excel_import.py`
- Modify: `backend/api.py`
- Create: `tests/test_excel_import.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `iter_product_images(path)`、Task 1 仓库接口。
- Produces: `store_image_bytes(data, original_name, image_dir) -> tuple[ValidatedImage, Path]`。
- Produces: `ExcelImportService.run(job_id: str, workbook_path: Path) -> None`。
- Produces: `POST /api/imports`，响应 `{"job_id": str, "status": "parsing"}`。
- Produces: `GET /api/imports/{job_id}`，返回状态、进度、摘要或错误。

- [ ] **Step 1: 写图片原字节保存和增量导入失败测试**

测试注入假解析器、假编码器和临时图库，断言：主图保存但不编码；三张买家秀保存并编码；重复运行只复用记录和向量；新 K 图停用旧主图；单张坏图被计入跳过但下一张继续。

```python
def test_excel_import_links_images_and_embeds_only_buyer_sofa(service, repository):
    service.run("a" * 32, fixture_workbook)
    assert repository.active_main("714161460085").source_column == "K"
    assert len(repository.active_buyers("714161460085")) == 3
    assert fake_encoder.encode_calls == 3
```

另测 `store_image_bytes()` 保存后的文件字节与输入严格相等。

- [ ] **Step 2: 写 API 上传与任务查询失败测试**

在 `tests/test_api.py` 注入同步执行的测试任务启动器，上传小 XLSX，断言接口创建 32 位任务 ID、文件位于临时任务目录、处理完成后临时目录删除；查询未知任务返回 404；非 `.xlsx` 返回 400。

- [ ] **Step 3: 运行导入相关测试并确认失败**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_excel_import.py tests\test_api.py -k "import" -q`

Expected: FAIL，原因是导入服务和接口尚不存在。

- [ ] **Step 4: 实现流式上传、后台任务和清理**

在 `Settings` 增加：

```python
@property
def import_job_dir(self) -> Path:
    return self.project_root / "data" / "import_jobs"
```

在 API 中使用 1 MiB 分块写入，不调用 `await upload.read()` 无参数版本：

```python
while chunk := await workbook.read(1024 * 1024):
    output.write(chunk)
```

文件写入完成后创建 `ImportJob`，通过 FastAPI `BackgroundTasks` 启动同步导入函数。`ExcelImportService.run()` 在 `finally` 中删除本任务的临时目录；每张图片单独提交，使坏图不回滚此前成功图片。错误摘要使用固定业务文案，不回传文件系统、数据库连接或模型内部异常。

在 `.gitignore` 增加 `data/import_jobs/`。

- [ ] **Step 5: 运行导入相关目标测试**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_excel_import.py tests\test_api.py -k "import" -q`

Expected: PASS。

- [ ] **Step 6: 提交导入服务与 API**

```powershell
git add .gitignore backend/config.py backend/image_assets.py backend/excel_import.py backend/api.py tests/test_excel_import.py tests/test_api.py
git commit -m "feat: import product images from Excel"
```

---

### Task 4: 关联商品的场景检索与去重

**Files:**
- Modify: `backend/repository.py`
- Modify: `backend/api.py`
- Modify: `tests/test_repository.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Produces: `ProductSearchRow(product_id, buyer_image_id, buyer_original_name, product_image_id, cosine_distance, similarity_percent, source_column)`。
- Produces: `ImageRepository.search_products(identity, query, *, top_k: int, candidate_limit: int = 30) -> list[ProductSearchRow]`。
- Modifies: `POST /api/search` 的结果项，增加 `product_id`、`matched_buyer_image_url`、`product_image_url`、`matched_source_column`。

- [ ] **Step 1: 写按商品 ID 去重的失败测试**

预置商品 A 的两张高分买家秀和商品 B 的一张买家秀，断言结果只有两个商品，商品 A 只保留最高分图片，并且两条结果都带当前主图。

```python
rows = repository.search_products(identity, unit([1, 0, 0]), top_k=5)
assert [row.product_id for row in rows] == ["A", "B"]
assert rows[0].buyer_image_id == highest_buyer.id
assert rows[0].product_image_id == current_main.id
```

另测没有启用主图的商品不返回，以及查询图片不会写入图库。

- [ ] **Step 2: 运行搜索目标测试并确认失败**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_repository.py tests\test_api.py -k "search_product or associated_product" -q`

Expected: FAIL，原因是商品搜索接口尚不存在。

- [ ] **Step 3: 实现候选召回和稳定去重**

仓库查询只联接启用的 `buyer_sofa`、其当前模型向量和同商品启用的 `product_main`。先按余弦距离、买家秀图片 ID 排序并限制 30 条，再在 Python 中按 `product_id` 保留首条，直到得到 `top_k` 个商品。这样行为明确且符合当前最多 8 人内部使用规模。

API 结果形状：

```python
class SearchResultResponse(BaseModel):
    rank: int
    product_id: str
    matched_buyer_image_id: int
    matched_buyer_image_url: str
    product_image_id: int
    product_image_url: str
    matched_source_column: str
    similarity: float
```

- [ ] **Step 4: 运行搜索目标测试**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_repository.py tests\test_api.py -k "search_product or associated_product" -q`

Expected: PASS。

- [ ] **Step 5: 提交搜索改动**

```powershell
git add backend/repository.py backend/api.py tests/test_repository.py tests/test_api.py
git commit -m "feat: return deduplicated product recommendations"
```

---

### Task 5: 复用现有前端接入真实 API

**Files:**
- Modify: `index.html`
- Modify: `app.js`
- Modify: `styles.css`
- Modify: `matcher-core.js`
- Modify: `tests/matcher-core.test.js`

**Interfaces:**
- Consumes: `POST /api/imports`、`GET /api/imports/{job_id}`、`POST /api/search`、`GET /api/images/{id}`。
- Produces: 现有“买家秀图库”页面内的 Excel 导入面板。
- Produces: 现有推荐卡片内并排的买家秀、商品主图、商品 ID、相似度和复制按钮。

- [ ] **Step 1: 写前端结果映射失败测试**

在 `matcher-core.js` 增加无 DOM 的纯函数 `buildApiPresentation(result)`，测试字段映射和缺图占位文案：

```javascript
const view = core.buildApiPresentation({
  product_id: '714161460085', similarity: 91.2,
  matched_buyer_image_url: '/api/images/2',
  product_image_url: '/api/images/1', matched_source_column: 'M'
});
assert.equal(view.productId, '714161460085');
assert.equal(view.similarity, '91.2%');
assert.equal(view.sourceLabel, '买家秀 M 列');
```

- [ ] **Step 2: 运行前端核心测试并确认失败**

Run: `node --test tests\matcher-core.test.js`

Expected: FAIL，原因是 `buildApiPresentation` 尚不存在。

- [ ] **Step 3: 扩展现有 HTML 与样式**

在“买家秀图库”中加入 Excel 文件选择、导入按钮、原生 `<progress>`、阶段文案和摘要容器。保留现有导航和视觉变量。将现有结果模板的单图改为 `.result-images` 内两张图，分别标注“相似买家秀”和“商品主图”，并增加商品 ID 复制按钮。

- [ ] **Step 4: 将现有匹配流程改接后端**

`app.js` 使用 `FormData` 上传查询图和 Excel。Excel 上传用 `XMLHttpRequest.upload.onprogress` 显示真实上传进度；拿到任务 ID 后每 1 秒查询状态，完成或失败即停止。搜索结果直接渲染 API 数据，不再调用浏览器 `makeFeature()` 排序。保留现有图片预览、Tab 切换和推荐网格。

网络失败、导入失败和空结果都写入现有提示区域，不用浏览器内部错误替代业务提示。

- [ ] **Step 5: 运行前端核心目标测试**

Run: `node --test tests\matcher-core.test.js`

Expected: PASS。

- [ ] **Step 6: 提交前端改动**

```powershell
git add index.html app.js styles.css matcher-core.js tests/matcher-core.test.js
git commit -m "feat: show linked product recommendations"
```

---

### Task 6: 文档更新与最小业务验证

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: 前五个任务的最终接口和页面行为。
- Produces: 管理员导入、数据库初始化和客服检索的实际启动说明。

- [ ] **Step 1: 更新实际使用说明**

README 写明：先运行 `init-db` 创建新增表；启动 API；在“买家秀图库”上传 Excel；等待任务完成；在“智能匹配”上传客户图查看买家秀、主图和商品 ID。说明只读取 F/K/L/M/N，查询图不保存，重复导入为增量同步。用户现有未跟踪的 `启动方式.md` 不在本次范围内，不读取、不修改、不暂存。

- [ ] **Step 2: 运行一次后端直接相关测试**

Run: `$env:PYTHONIOENCODING='utf-8'; .venv\Scripts\python.exe -m pytest tests\test_tencent_excel.py tests\test_excel_import.py tests\test_repository.py tests\test_api.py -k "product_image or import_job or excel or import or search_product or associated_product" -q`

Expected: PASS。不要扩大为全量 pytest。

- [ ] **Step 3: 运行一次前端直接相关测试**

Run: `node --test tests\matcher-core.test.js`

Expected: PASS。

- [ ] **Step 4: 检查文档和工作区范围**

Run: `git diff --check`

Expected: 无空白错误；`git status --short` 中不包含 Excel、临时导入文件、提取图片或用户原有未跟踪文件的暂存改动。

- [ ] **Step 5: 提交文档**

```powershell
git add README.md
git commit -m "docs: explain Excel product image import"
```
