# Task 5 实现简报：建库/搜索服务与 CLI

## 目标

按计划 Task 5，以 TDD 把图片资产、可替换编码器和仓库组合成可用的导入/检索服务，并提供四个 argparse 子命令。当前是 8 人、1 万级技术验证，优先清晰的主流程，不增加队列、后台任务、重试框架或批处理优化。

## 文件与接口

- `backend/services.py`
- `backend/cli.py`
- `tests/test_services.py`
- 可按需新增 `tests/conftest.py`，但不要大规模重构已通过模块。

实现计划中的 `ImportStatus`、`ImportResult`、`SearchResult`、`LibraryService.import_path()`、`LibraryService.search()` 与 `backend.cli.main()`。

## 服务规则

- 文件或目录导入；目录递归扫描四类支持扩展，大小写不敏感，按规范化路径稳定排序。传入不存在路径/非文件目录要给中文明确错误。
- 每张图独立事务：新图片+当前模型向量=`IMPORTED`；图片和当前模型向量均已有=`DUPLICATE`；图片已有但当前模型向量缺失=`EMBEDDING_ADDED`；单图异常=`FAILED` 且继续。
- Repository 若缺少“当前身份向量是否存在”等最小方法，可小幅补充并测试；保持其不 commit 的边界。
- 新复制的图库文件若后续编码或数据库事务失败才删除；绝不删除源图、既有图库文件或其他事务创建的文件。
- 查询只校验并编码内存中的图片，不调用 `store_image`、不写数据库；默认排除完全相同 SHA，保留不同角度；`top_k` 只接受 1–50 的非布尔整数。
- 服务只依赖 `ImageEncoder` 协议，不导入/判断 OpenCLIP 类型；不涉及结构化元数据或“同商品”阈值。

## CLI 规则

- `init-db`、`import`、`search`、`serve` 四子命令；输出中文，失败非零；不得打印密码/完整 URL。
- `init-db` 不应加载模型；`--help` 不应连接数据库或加载模型。
- `serve` 仅做清晰的 uvicorn 启动委托；FastAPI 具体路由留给 Task 6。
- 可提供依赖构建小函数方便测试；不要引入 DI 框架。

## 测试

- fake encoder + 事务数据库或轻量 fake repository，覆盖四种导入状态、目录单文件失败继续、稳定顺序、重复导入、补向量、失败文件回收、搜索不持久化/排除同 SHA/top_k 边界、模型可替换。
- CLI 覆盖 help 四命令、init-db 不创建 encoder、失败码/中文输出；不要调用真实模型下载。
- 所有 Python 文本文件操作显式 UTF-8，必要注释使用中文；不显示 `.env` 内容；不派生子智能体。

## 验证与提交

- `.venv\Scripts\python.exe -m pytest tests/test_services.py -v`
- `.venv\Scripts\python.exe -m backend.cli --help`
- `.venv\Scripts\python.exe -m pytest tests -m "not model" -q`
- `git diff --check`

完成后提交当前分支，并写 `task-5-report.md`，包含红/绿证据、提交 SHA、自审结论。
