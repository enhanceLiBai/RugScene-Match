# Task 1 实现简报：项目内 Python 环境与配置

## 目标

完成计划 Task 1。现有 `.venv`、依赖、`.gitignore`、`.env.example`、`requirements.in`、`scripts/bootstrap.ps1` 和 `backend/__init__.py` 已由主智能体准备；请核对并只补充必要改动，重点以 TDD 新增 `backend/config.py` 与 `tests/test_config.py`。

## 必须实现的接口

- `Settings.load(project_root: Path | None = None) -> Settings`
- `Settings.cache_environment() -> dict[str, str]`
- `Settings.database_url(database: str | None = None) -> sqlalchemy.URL`

`Settings` 至少包含项目根目录、PostgreSQL 主机/端口/库名/用户/密码、编码器名称、CLIP 模型名/权重名、设备配置；提供可推导的 `.venv` 和图库路径属性。

## 规则

- 环境变量覆盖项目 `.env`；读取 `.env` 时明确使用 UTF-8。
- 数据库 URL 必须使用 `URL.create()`，不要手工拼接密码。
- 默认值适合当前本地验证；缺少数据库密码时给出中文、且不泄露凭据的错误。
- 所有 Python 文本文件操作显式 `encoding="utf-8"`。
- 必要代码注释使用简体中文，解释边界和取舍。
- 缓存目录必须全部位于项目 `.cache/`，模型和依赖不能持久化到 C 盘。
- 不要读取或提交真实 `.env`，不要输出密码。
- 不要实现其他任务，不要派生子智能体。

## TDD 与验证

1. 先创建失败的 `tests/test_config.py` 并运行，记录预期失败。
2. 实现最小代码。
3. 运行 `.venv\Scripts\python.exe -m pytest tests/test_config.py -v`。
4. 运行 `.venv\Scripts\python.exe -m pip check` 和 Python 版本检查。
5. 检查变更范围，提交到当前分支。

## 报告

完成后写 `.superpowers/sdd/2026-09-03-clip-backend/task-1-report.md`，包含：改动摘要、失败测试证据、最终测试证据、提交 SHA、自审发现。该目录已被 Git 忽略。
