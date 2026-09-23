# Task 6 实现简报：FastAPI 接口

## 目标

按计划 Task 6，以 TDD 提供可供前端后续接入的最小 FastAPI。当前重点是功能跑通，不实现认证、限流、任务队列、审计、复杂异常框架或生产级攻击测试。

## 文件与接口

- `backend/api.py`
- `tests/test_api.py`
- 允许小幅补充 `backend/services.py` / `backend/repository.py` 的公开方法，以支持内存字节查询和按 ID 读取；不要重构已通过主流程。

实现 `create_app(settings=None, encoder=None) -> FastAPI` 与模块级 `app`。为测试事务隔离，可增加可选 `session_factory` 注入参数。

## 核心端点

- `GET /health`：数据库 `SELECT 1`；返回配置中的编码器/模型/权重信息，但不能触发真实模型加载或图片编码。
- `GET /api/library`：稳定列出图片及已有模型身份；无需分页（当前 1 万级验证可后续添加），不要求结构化商品元数据。
- `GET /api/images/{image_id}`：按数据库 ID 返回图库文件；404 表示记录或文件不存在。只需确保最终路径在项目 `data/images` 下，不做额外安全测试矩阵。
- `POST /api/search?top_k=5`：multipart 上传单图，调用 `validate_image_bytes` 和当前编码器检索；不写图库/数据库；返回模型身份、rank/image_id/original_name/image_url/similarity。无当前模型向量时 `results=[]` 并带中文说明。

## 错误与生命周期

- 损坏/不支持图片返回 400；top_k 越界依靠 FastAPI 返回 422；数据库不可用返回 503；其他已知输入错误用简明中文。
- 设置一个简单上传大小上限（例如 20 MiB），不扩展流式上传/恶意 multipart 压测。
- 每请求创建/关闭 Session；应用关闭时 dispose engine。模型对象在 app 生命周期内复用，构造 app 不加载权重。
- 不回显密码、完整数据库 URL 或内部堆栈。

## 测试

- fake encoder，禁止真实下载。
- 覆盖 health 不 encode、图库列表、图片读取、成功搜索排名与 URL、查询不持久化、空结果说明、损坏图 400、top_k 0/51 为 422、数据库错误 503。
- API 测试数据用事务隔离，不删除已有用户记录。
- 所有必要注释用中文；Python 文本读写显式 UTF-8；不派生子智能体。

## 验证与提交

- `.venv\Scripts\python.exe -m pytest tests/test_api.py -v`
- `.venv\Scripts\python.exe -m pytest tests -m "not model" -q`
- `git diff --check`

完成后提交并写 `task-6-report.md`，记录红/绿证据和 SHA。
