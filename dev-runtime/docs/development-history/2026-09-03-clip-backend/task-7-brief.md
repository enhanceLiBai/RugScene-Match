# Task 7 实现简报：真实环境验收与文档

## 目标

完成技术验证阶段收尾：注册 pytest 模型标记、更新 README、使用本机 PostgreSQL 和项目内 OpenCLIP 缓存运行真实命令与 API。功能优先，不增加部署、认证、性能压测或前端改造。

## 文件

- 新增 `pytest.ini`
- 更新 `README.md`
- `.env` 已由主智能体创建并被忽略，不得读取后回显、复制或提交其内容。

## 文档内容

- Windows 项目内 `.venv`/`.cache` 初始化。
- `.env.example` 复制与字段说明，禁止写真实密码。
- Docker PostgreSQL/pgvector 前置条件、`init-db`、单图/目录 import、CLI search、serve 与四个 HTTP 端点。
- 明确当前仅相似度检索、无结构化元数据必填、模型可替换、前端尚未接 API、CPU 首次模型加载较慢。
- 给出用户把同一地毯不同角度图片放到一个测试目录的最短验收步骤。

## 验证

- `init-db` 连续运行两次。
- 非模型全量测试、`pip check`、CLI help。
- `RUN_MODEL_TESTS=1` 的真实 OpenCLIP smoke；确认权重在项目 `.cache/open_clip`，不检查/扫描用户 C目录之外的 C盘缓存。
- 若项目内已有用户图片，执行 CLI import/search；若没有，只记录“等待用户图片”，不得伪造排序结论。
- 启动 API 后先命令行验证 health/library，再由主智能体使用 Edge/浏览器扩展验收页面访问。
- 不实现或修改现有静态前端。

先核对现状，再编辑 README/pytest.ini；运行相关文档/命令检查，提交当前分支并写 task-7-report.md。不得派生子智能体。
