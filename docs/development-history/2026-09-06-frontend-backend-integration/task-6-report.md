# Task 6 报告：文档、全量验证与真实同源冒烟

## 变更

- 更新 `README.md`：后端同源页面成为唯一正式启动方式，移除了双击 `index.html`、IndexedDB 和九宫格本地匹配说明。
- 文档写明 `init-db`、`serve`、访问地址、图片与数据库存储位置，以及商品元数据选填且不影响向量排序。

## 验证记录

工作目录：`D:\电商ai应用\.worktrees\frontend-backend-integration`。Python 命令使用父环境 `D:\电商ai应用\.venv\Scripts\python.exe`，并设置 `PYTHONIOENCODING=utf-8`。

| 命令或步骤 | 结果 |
| --- | --- |
| `node --check api-client.js` | 退出码 0 |
| `node --check matcher-core.js` | 退出码 0 |
| `node --check app.js` | 退出码 0 |
| `$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pip check` | 退出码 0；`No broken requirements found.` |
| `node --test tests\api-client.test.js tests\matcher-core.test.js` | 退出码 0；9 passed、0 failed |
| `$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests -m "not model" -q --basetemp .superpowers\tmp\task-6-pytest` | 退出码 0；116 passed、1 deselected、2 warnings（Starlette/httpx 弃用警告） |
| `init-db`（首次） | 退出码 0；`数据库和表结构已初始化。` |
| `init-db`（重复运行） | 退出码 0；`数据库和表结构已初始化。` |
| 后台 `serve` 后请求 `GET /` | 200；页面包含同源 `api-client.js` 与 `app.js` |
| `GET /styles.css` | 200 |
| `GET /api/library` | 200；数据库图库响应正常，当前图片数为 0 |
| `GET /health` | 200；数据库状态为 `ok` |
| `git diff --check` | 退出码 0 |

后台服务使用 `Start-Process -WindowStyle Hidden` 启动，验证后仅停止了本次启动的精确进程（PID 26980）。未删除任何图片、数据库记录或用户数据。

## 自审

- README 与实际 `backend.cli init-db`、`backend.cli serve`、同源静态资源路由和 API 契约一致。
- 本任务只变更文档，未新增代码注释；现有关键逻辑的简体中文注释未被改动，未发现过量或与实现不一致的新增注释。
- 自动化验证使用 fake encoder，未触发 OpenCLIP 下载。

## 顾虑

- 未执行真实 OpenCLIP 图片上传/查询冒烟：该路径可能首次下载模型权重，而任务要求不触发网络下载。非模型自动化契约已通过。
- pytest 有 2 个第三方 Starlette/httpx 弃用警告，未影响本次结果。
