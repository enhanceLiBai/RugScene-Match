# Task 3 报告：图库上传、元数据响应与同源静态路由

## 实现结果

- 新增 `POST /api/library` multipart 上传，九个商品字段均支持空值规范化。
- 图片和价格在进入 `LibraryService` 前验证；20 MiB 超限、坏图、负价格返回 400。
- `ImportStatus` 映射为 lowercase HTTP 状态；`FAILED` 返回 503。
- 图库、上传和搜索复用同一元数据响应映射，`price` 对外为 `float | None`，持久层保持 `Decimal`。
- `create_app` 新增 keyword-only `frontend_root`；默认静态根从 `backend/api.py` 的父项目目录解析，与 `Settings.project_root` 独立。
- 仅注册 `/`、`/styles.css`、`/matcher-core.js`、`/api-client.js`、`/app.js` 五个静态路由。

## RED

命令：

```powershell
$env:PYTHONIOENCODING='utf-8'; D:\电商ai应用\.venv\Scripts\python.exe -m pytest tests\test_api.py -q --basetemp=.superpowers\tmp\task3-red-2
```

结果：`8 failed, 8 passed`。失败原因符合预期：上传返回 405、图库/搜索缺九个元数据字段、根页面返回 404。

补充 mutation RED：把 FAILED 映射临时改为 500、默认静态根临时改为 `Settings.project_root`，运行两条对应测试得到 `2 failed`，证明回归测试能捕获这两类错误。

## GREEN

聚焦命令：

```powershell
$env:PYTHONIOENCODING='utf-8'; D:\电商ai应用\.venv\Scripts\python.exe -m pytest tests\test_api.py -q --basetemp=.superpowers\tmp\task3-api-final
```

结果：`18 passed, 2 warnings in 3.71s`。

非模型全量命令：

```powershell
$env:PYTHONIOENCODING='utf-8'; D:\电商ai应用\.venv\Scripts\python.exe -m pytest tests -m "not model" -q --basetemp=.superpowers\tmp\task3-full
```

结果：`116 passed, 1 deselected, 2 warnings in 6.74s`。

两条 warning 均来自 FastAPI/Starlette TestClient 依赖的既有弃用提示：`httpx` 兼容层和 `anyio.abc.BlockingPortal` 别名。

## 自审

- 逐项核对简报接口、九字段、状态大小写、价格类型、校验码、FAILED 映射和固定静态白名单，均有实现与测试覆盖。
- `git diff --check` 通过；未修改图库服务、仓库或前端文件。
- 图片先在 API 边界验证，再按既定接口调用 `import_bytes()`；当前会重复一次内容验证，但保持服务自身边界完整，且未扩展前置接口。
- 上传成功后重新读取图库行，以确保响应反映重复上传补充后的最终元数据和模型列表。

## 顾虑

- 当前工作树根目录尚无 `api-client.js`；固定路由已经注册，需依赖前端集成任务生成该文件后，默认部署下该资产才能实际返回 200。测试通过显式 `frontend_root` 验证路由行为，并另测默认根与临时图库根解耦。
- 全量测试仍有两条上游弃用 warning，本任务没有升级依赖，避免扩大范围。
