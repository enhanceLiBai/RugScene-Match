# Task 6 完成报告：FastAPI 接口

## 提交

- 实现提交：`840013bf439efbc065b6d368d329b8d7d5959118`（`feat: add FastAPI image search API`）

## 红灯证据

在实现 `backend.api` 前运行：

```text
.venv\Scripts\python.exe -m pytest tests\test_api.py::test_health_checks_database_without_encoding_an_image -v
ModuleNotFoundError: No module named 'backend.api'
```

初始 API 实现后，测试发现嵌套依赖被 FastAPI 误解析为必填 `session` 查询参数，8 个端点行为测试返回 422。将路由和内部依赖改为 `parameter: Type = Depends(...)` 后，测试转绿。

## 绿灯证据

```text
.venv\Scripts\python.exe -m pytest tests\test_api.py -v
10 passed, 2 warnings

.venv\Scripts\python.exe -m pytest tests -m "not model" -q
103 passed, 1 deselected, 2 warnings

git diff --check
退出码 0
```

两条 warning 来自已安装 FastAPI/Starlette TestClient 的弃用提示，不影响 API 行为；测试全程注入 fake encoder，未加载或下载 OpenCLIP 权重。

## 自审结论

- `GET /health` 执行 `SELECT 1`，但只返回配置模型信息，不读取会触发真实模型加载的 `encoder.identity`。
- `GET /api/library` 稳定列出图片和全部已持久化模型身份；仓库新增按 ID 查询和单次 join 的图库读取接口。
- `GET /api/images/{image_id}` 只按数据库 ID 读取，解析后验证文件仍位于 `data/images`，记录或文件缺失均返回 404。
- `POST /api/search` 在内存中做字节校验和编码，限制上传为 20 MiB，查询不复制图片也不写入数据库；无当前模型向量时返回空数组和中文说明。
- 已覆盖损坏图片 400、`top_k` 越界 422、数据库错误 503 且不回显连接凭据。API 测试使用外层数据库事务回滚，未删除已有用户数据。
- 未添加认证、限流、队列、审计、并发攻击测试或真实模型下载流程。
