# Task 5 报告：页面迁移到后端数据源

## 实现结果

- `index.html` 在 `app.js` 前加载 `api-client.js`，移除演示数据与本机清空入口，并增加图库刷新、图库状态、入库状态和入库提交按钮的稳定 ID。
- `app.js` 删除 IndexedDB、本地图片特征、本地排序、seed/clear 流程；页面初始化、图片入库和相似检索分别调用 `listLibrary()`、`uploadLibraryImage()` 和 `searchSimilar(queryFile, 5)`。
- 九个现有表单字段通过 `readEntryMetadata()` 映射为后端 snake_case；匹配结果使用 `similarity`、`image_url` 以及 `buildPresentation(item).matchReason`。
- 图库和结果的动态文本均使用 DOM 节点及 `textContent`，不再使用 `innerHTML` 拼接后端数据。
- `styles.css` 增加状态、错误、重试和禁用按钮样式；移动端提交、匹配及图库刷新按钮保持整行布局。

## RED 证据

命令：

```powershell
$env:PYTHONIOENCODING='utf-8'; D:\电商ai应用\.venv\Scripts\python.exe -m pytest tests\test_api.py::test_root_serves_frontend_and_only_registered_assets -q --basetemp=.superpowers\tmp\pytest-task5-red
```

结果：`1 failed`。失败发生在新增的 `<script src="api-client.js"></script>` 契约断言；旧首页尚未加载客户端，且仍包含本地演示/清空入口、缺少状态与刷新元素。

## GREEN 证据

- `node --check app.js`：exit code 0。
- 根页面契约：`1 passed, 2 warnings`。
- `node --test tests\api-client.test.js tests\matcher-core.test.js`：`9 passed, 0 failed`。
- 完整 `tests/test_api.py` 回归：`18 passed, 2 warnings`。
- 旧实现扫描：`indexedDB`、`rankBySimilarity`、`makeFeature`、`seedButton`、`clearButton`、`色调`、`构图`、`innerHTML` 均无命中。
- `git diff --check`：exit code 0。

两条 pytest warning 来自现有 Starlette/FastAPI 测试依赖的弃用提示，不是本次改动引入的测试失败。

## 自审

- 数据流边界符合简报：浏览器仅负责预览与 DOM 状态，持久化和向量检索均由后端负责。
- 所有必需小函数均存在，忙碌状态在 `finally` 中恢复，图库加载失败时保留刷新按钮。
- 空图库、无匹配、上传失败和检索失败都有稳定中文反馈；后端返回的错误消息通过 `textContent` 展示。
- 页面契约测试改为复制真实 `index.html`，避免伪造夹具在生产页面修复后仍永久失败。

## 顾虑

- 当前仓库没有浏览器 DOM 测试运行器，因此自动验证覆盖页面契约、API 客户端、展示核心和后端 API，但未自动执行真实浏览器中的点击/上传流程；部署后的人工冒烟测试仍有价值。
- 测试依赖存在两条上游弃用 warning，后续升级 Starlette/FastAPI 测试栈时可单独处理。

## Fix round 1/5（review Important）

### 修复内容

- 图库刷新失败不再调用 `renderLibrary([])`，因此最后一次成功展示的列表和计数保持不变；错误状态和刷新入口仍可见，只有成功返回空数组才展示空图库。
- 搜索点击时捕获本次 `requestedFile`，请求期间禁用查询文件输入并立即隐藏旧结果；成功、空结果或失败后均在 `finally` 恢复输入和按钮。
- 新增 `tests/app.test.js`，使用 Node 内置 `vm` 执行真实浏览器脚本，未引入 jsdom、npm 包或构建工具。三个测试仅覆盖刷新失败保留、搜索中状态/空结果和搜索失败恢复。

### RED 命令与输出

```powershell
node --test tests\app.test.js
```

```text
✖ 图库刷新失败保留上一轮列表和计数并恢复刷新按钮 (6.9108ms)
✖ 搜索期间锁定输入并隐藏旧结果，空结果后恢复按钮和输入 (2.3366ms)
✖ 搜索失败后恢复按钮和输入并显示错误 (3.3193ms)
ℹ tests 3
ℹ suites 0
ℹ pass 0
ℹ fail 3
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 152.4053

首个断言显示旧卡片被空状态节点替换；后两个断言均为请求期间输入实际 `false`、预期 `true`。
```

### GREEN 命令与输出

```powershell
node --test tests\app.test.js tests\api-client.test.js tests\matcher-core.test.js
```

```text
✔ 图库上传只发送图片和非空元数据 (27.7034ms)
✔ 图库列表使用 GET /api/library (1.3116ms)
✔ 相似检索使用 top_k 查询参数并发送图片 (0.6528ms)
✔ JSON 错误优先展示后端 detail (0.8877ms)
✔ 非 JSON 错误转换为稳定中文消息 (0.4427ms)
✔ 图库刷新失败保留上一轮列表和计数并恢复刷新按钮 (3.5967ms)
✔ 搜索期间锁定输入并隐藏旧结果，空结果后恢复按钮和输入 (1.4022ms)
✔ 搜索失败后恢复按钮和输入并显示错误 (0.9037ms)
✔ 展示契约消费后端 snake_case 字段并保留原始文件名兜底 (2.0419ms)
✔ 缺少全部结构化元数据时仍能生成完整展示内容 (0.2863ms)
✔ 缺少商品元数据时生成不包含虚构商品事实的通用话术 (0.2366ms)
✔ 推荐话术只使用后端商品名和成交亮点 (0.1843ms)
ℹ tests 12
ℹ suites 0
ℹ pass 12
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 219.6507
```

```powershell
node --check app.js
```

```text
（无输出，exit code 0）
```

```powershell
$env:PYTHONIOENCODING='utf-8'; D:\电商ai应用\.venv\Scripts\python.exe -m pytest tests\test_api.py::test_root_serves_frontend_and_only_registered_assets -q --basetemp=.superpowers\tmp\pytest-task5-fix1
```

```text
.                                                                        [100%]
============================== warnings summary ===============================
..\..\.venv\Lib\site-packages\fastapi\testclient.py:1
  D:\电商ai应用\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

..\..\.venv\Lib\site-packages\starlette\testclient.py:53
  D:\电商ai应用\.venv\Lib\site-packages\starlette\testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1 passed, 2 warnings in 2.41s
```

### Fix-round 自审与顾虑

- 测试执行的是 `app.js` 的实际函数和 DOMContentLoaded 事件处理器；伪 DOM 只实现本轮行为需要的浏览器接口，没有对假 API 的调用次数做替代性断言。
- 刷新成功空数组仍通过原有 `renderLibrary([])` 生成空状态，失败分支不会触碰图库 DOM。
- 输入锁定与本次文件快照共同约束搜索上下文；旧结果在网络请求发起前即隐藏，失败时不会重新显示。
- 顾虑仍限于没有真实浏览器自动化；按 controller ruling，本轮未扩展 object URL 清理或其他非 review 范围改动。
