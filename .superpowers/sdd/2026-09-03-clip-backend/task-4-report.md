# Task 4：PostgreSQL/pgvector 数据模型与仓库报告

## 范围

- 新增 `backend/db.py`：安全、幂等地创建目标数据库、启用 `vector` 扩展并初始化 schema。
- 新增 `backend/models.py`：`images`、`image_embeddings`、唯一约束、外键级联与正数检查。
- 新增 `backend/repository.py`：图片与向量持久化、模型身份过滤、余弦检索及相似度换算；仓库不提交或回滚事务。
- 新增 `tests/test_repository.py`：16 项真实 PostgreSQL 集成测试；每项写入由外层事务回滚。

## TDD 证据

- 红：缺失 `backend.db` 时，`test_schema_supports_multiple_models_for_one_image` 收集失败，错误为 `ModuleNotFoundError: No module named 'backend.db'`。
- 绿：实现最小数据库模块、模型和仓库后，该测试通过。
- 红：固定长度 SHA-256 schema 测试确认旧表为 `character varying`，断言失败。
- 绿：初始化增加安全升级（只在所有现有哈希均为 64 位时升级为 `char(64)`）后，该测试通过。

## 验证结果

- `tests/test_repository.py -v`：16 passed。
- `tests/test_config.py tests/test_image_assets.py tests/test_encoder_contract.py tests/test_repository.py -q`：70 passed。
- `git diff --check`：退出码 0。
- PostgreSQL：16.15。
- pgvector：0.8.6。

## 安全与自审

- 管理库连接使用 `postgres` 与 autocommit；数据库存在性查询参数化，创建数据库名使用 `psycopg.sql.Identifier`。
- 未输出、复制或提交数据库密码或完整连接 URL。
- 未创建 HNSW/IVFFlat 索引；图片二进制不进入数据库。
- 测试不执行 drop、truncate 或删除既有数据；级联删除只针对当前测试事务新建记录并在结束时回滚。
- 查询同时过滤 encoder、model、权重和维度，距离排序用图片 ID 作为稳定次级键。

## 提交

最终提交 SHA 由本任务交付消息提供。

## 审查修复（追加）

- 初始化使用 PostgreSQL advisory lock：管理库 session lock 串行化数据库创建，目标库 transaction lock 串行化扩展与 schema DDL；双连接并发初始化测试通过。
- 向量写入改为 PostgreSQL `INSERT ... ON CONFLICT ... DO UPDATE`，不再先查询后写入；ORM 状态在 Core UPSERT 后统一过期。
- 持久化边界增加有限 L2 单位向量验证，路径拒绝 Windows drive/UNC，SHA-256 限制为 64 位小写十六进制。
- 数据库为 SHA-256 增加命名 CHECK；既有 schema 仅在数据合法时幂等补齐，否则给出不包含敏感信息的中文错误。
- `image_count()` 改为数据库 `COUNT(*)`；session factory 增加显式 dispose 生命周期，测试 fixture 结束时释放连接池。
- 审查新增先行测试红灯：零范数/非单位向量、drive-relative 路径、错误 SHA 和全表计数共 7 项失败；修复后全部转绿。
- 审查后 `tests/test_repository.py -v`：28 passed。

## 规模化简化（追加）

- 当前仅 8 人并发、约 1 万张图片，移除低频人工 `init-db` 的 advisory lock 和对应并发测试，保持初始化路径直接易读。
- 不添加数据库级向量维度 CHECK；仓库层已在写入/查询前校验向量 shape、float32、有限值与单位范数。
- `embedding_count()` 改为 SQL `COUNT(*)`，避免读取全部向量对象。
