# Task 1 配置实现报告

## 改动摘要

- 新增 `backend/config.py`：提供不可变 `Settings`、项目内运行路径、缓存环境变量和安全的 SQLAlchemy 数据库 URL 构造。
- 新增 `tests/test_config.py`：覆盖项目内路径、环境变量覆盖 `.env`、带保留字符密码的 URL 构造和缺少密码的中文错误。

## TDD 失败证据

在新增测试且尚未创建 `backend.config` 时执行：

```text
.venv\\Scripts\\python.exe -m pytest tests/test_config.py -v
```

结果：测试收集失败，包含 `ModuleNotFoundError: No module named 'backend.config'`，符合预期。

## 最终验证证据

```text
.venv\\Scripts\\python.exe -m pytest tests/test_config.py -v  -> 4 passed
.venv\\Scripts\\python.exe -m pytest tests/test_config.py -q  -> 4 passed
.venv\\Scripts\\python.exe -m pip check                       -> No broken requirements found.
.venv\\Scripts\\python.exe --version                           -> Python 3.12.13
git diff --check                                                 -> 无输出
```

## 提交

提交 SHA：`ddd4d6fcab8e587e1e8f180a4201274929333f5c`（`feat: add project settings configuration`）。

## 自审发现

- `Settings.load()` 以 `override=False` 加载 UTF-8 `.env`，因此显式进程环境变量优先。
- 数据库 URL 使用 `URL.create()`，不会手工拼接或输出密码。
- 缓存与图片、虚拟环境路径均由 `project_root` 推导，保持在项目内。
- 共享工作区已有的 `.gitignore` 未纳入本任务提交。

## 质量审查修复

- 审查指出：`load_dotenv(override=False)` 会将第一个项目的 `.env` 写入进程环境，导致后续 `Settings.load()` 错误继承配置。
- 已先新增双项目连续加载的回归测试；旧实现失败，第二项目错误得到 `first-host`。
- 改用带 UTF-8 编码的 `dotenv_values()` 生成局部默认值映射，逐项由真实 `os.environ` 覆盖；不再修改进程环境。
- 修复后执行 `pytest tests/test_config.py -v`：`5 passed`；`pip check`：`No broken requirements found.`；`git diff --check`：无输出。
- 修复提交 SHA：`a517e3161c4cdde531a550b90faa16b0c55f327b`（`fix: isolate dotenv settings per project`）。
