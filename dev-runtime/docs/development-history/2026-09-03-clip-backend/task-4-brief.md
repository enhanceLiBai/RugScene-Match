# Task 4 实现简报：PostgreSQL/pgvector 数据模型与仓库

## 目标

按计划 Task 4，以 TDD 实现数据库初始化、SQLAlchemy 模型和只负责持久化的仓库。使用 Docker 中现有 PostgreSQL 16/pgvector，新库名 `carpet_matcher`。不实现服务、CLI 或 API。

## 文件与接口

- `backend/db.py`
- `backend/models.py`
- `backend/repository.py`
- `tests/test_repository.py`

接口遵守计划：`create_database_and_schema`、`create_session_factory`、`ImageRepository.find_by_sha256`、图片新增/列举/计数、模型向量查询/upsert/计数、`search`、`SearchRow`、`cosine_distance_to_percent`。

## Schema 与事务规则

- `images` 与 `image_embeddings` 字段、外键/级联/唯一约束严格对应设计规格；增加数据库级宽高、dimension 正数检查。
- `embedding` 使用不固定维度 `VECTOR()`；技术验证阶段不得创建 HNSW/IVFFlat。
- 搜索必须先过滤 `encoder/model_name/pretrained/dimension`，再计算余弦距离；排除指定 SHA-256；按距离升序并用稳定次级键消除并列不确定性。
- `cosine_distance_to_percent` 对范围夹紧到 0–100 并四舍五入两位；拒绝非有限距离。
- Repository 方法不得擅自 commit/rollback；只 `add/flush/execute`，事务边界交给服务层。
- 存储路径必须是相对项目根目录的 POSIX/可移植文本，仓库不读取本地图片文件。
- upsert 只覆盖同一 image+完整模型身份的向量；写入前再次校验 shape/dtype/有限值/维度匹配，不能依赖调用者可信。
- 查询结果包括后续 CLI/API 所需的 image id、原名、stored_path、sha256、MIME、尺寸、模型身份、距离和百分比。

## 数据库初始化安全

- 管理连接使用 `postgres` 数据库和 autocommit；参数化检查目标库是否存在，`CREATE DATABASE` 只能用 `psycopg.sql.Identifier`。
- 目标库中幂等执行 `CREATE EXTENSION IF NOT EXISTS vector` 和 `metadata.create_all()`。
- 异常和日志不得打印密码或完整数据库 URL。
- `.env` 已在项目内、被 Git 忽略，仅供 `Settings.load()`/集成测试使用；不要展示、复制、提交其中内容。

## 测试纪律

- 先写缺失模块红测试并实际运行。
- 集成测试可初始化 `carpet_matcher`，但每个测试插入的数据必须在测试事务中回滚；不得 truncate/drop 表、删除既有记录或重建用户数据库。
- 使用唯一随机 SHA/名称，断言只针对本测试记录，避免受未来用户数据影响。
- 至少覆盖：幂等初始化、多模型/多维共存、同身份 upsert、完整身份与维度过滤、余弦排序、同 SHA 排除、百分比边界、约束与回滚。
- 必要注释使用中文，所有 Python 文本文件操作显式 UTF-8；不派生子智能体。

## 验证与提交

- `.venv\Scripts\python.exe -m pytest tests/test_repository.py -v`
- `.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_image_assets.py tests/test_encoder_contract.py tests/test_repository.py -q`
- `git diff --check`

完成后提交当前分支，并写 `.superpowers/sdd/2026-09-03-clip-backend/task-4-report.md`，记录红/绿证据、数据库版本/扩展可用性（不得含密码或完整 URL）、提交 SHA 和自审结论。
