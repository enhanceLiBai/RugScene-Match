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
