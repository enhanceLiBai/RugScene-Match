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
