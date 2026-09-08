# Task 7 验收报告

## 变更

- `pytest.ini` 注册模型标记并启用 `--strict-markers`。
- `README.md` 补充 Windows 项目内环境、缓存、.env、数据库初始化、CLI、API 和人工图片验收说明。
- `tests/test_open_clip_smoke.py` 将缓存契约改为：OpenCLIP 显式使用项目 `.cache/open_clip`，且不写入本项目负责的四个缓存环境变量；不约束第三方库自身的无关环境设置。

## 验证证据

- `backend.cli init-db`：连续两次均输出“数据库和表结构已初始化。”
- `pytest tests -m "not model" -q`：103 passed，1 deselected。
- `pip check`：No broken requirements found。
- `backend.cli --help`：列出 init-db、import、search、serve。
- `RUN_MODEL_TESTS=1 pytest tests/test_open_clip_smoke.py -v`：1 passed；测试确认 `.cache/open_clip` 中存在大于 10 MiB 的模型缓存产物。

## 人工数据与浏览器范围

项目内未发现用户图片，因此未执行 CLI import/search 的人工排序验收；等待用户提供同一地毯不同角度图片和对照图片。未改动静态前端，也未做浏览器验收，交由主智能体继续处理。
