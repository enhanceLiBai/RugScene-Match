# Task 2 完成报告：图片资产校验、哈希与安全存储

## 交付内容

- 新增 `backend/image_assets.py`：`ValidatedImage`、`InvalidImageError`、路径与字节统一校验入口，以及幂等安全落盘。
- 新增 `tests/test_image_assets.py`：覆盖 RGBA 转 RGB、原始字节 SHA-256、JPEG 规范扩展名、大小写扩展名、损坏/空数据、格式伪装、幂等、不覆盖已有目标、并发提交窗口、校验后源文件变化及临时文件清理。
- 图片实际格式决定 MIME 和规范扩展名；落盘使用已校验的原始字节，并通过同目录临时文件加硬链接提交，避免覆盖已存在的哈希目标。

## 红/绿证据

- RED：`python -m pytest tests/test_image_assets.py::test_validate_image_returns_dimensions_rgb_and_byte_hash -v` 在实现前失败，错误为 `ModuleNotFoundError: No module named 'backend.image_assets'`。
- RED：并发提交测试在替换式提交实现下失败，证明其会覆盖竞争方已写入目标；补充临时文件清理断言也在首次硬链接实现中失败，证明会遗留临时文件。
- GREEN：`.venv\\Scripts\\python.exe -m pytest tests/test_image_assets.py -v`，12 passed。
- GREEN：`.venv\\Scripts\\python.exe -m pytest tests/test_config.py tests/test_image_assets.py -q`，17 passed。
- 检查：`git diff --check` 无输出。

## 自审结论

- 未读取 `.env`，未改动数据库、编码器、服务或 API。
- 所有新增必要注释为简体中文；本任务不涉及 Python 文本文件读写。
- 异常仅回显安全文件名，不回显输入二进制；落盘不依赖校验后的源路径，规避 TOCTOU 二次读取不一致。

## 提交

- 图片资产实现与测试提交：`c712650b817ae715a44e0ec36af0e6822cf26821`

## 审查修复（追加提交）

- 存储前重新计算 `raw_bytes` 的 SHA-256；仅接受计算结果一致的 64 位小写十六进制哈希，扩展名仅允许 `.jpg`、`.png`、`.webp`，并确认解析后的目标仍在图库根目录内。
- 临时文件进入上下文后立即记录路径；`write`、`flush`、`fsync` 任一步失败均由 `finally` 清理。
- 新增 `MAX_IMAGE_PIXELS = 50_000_000`。在 `load()`/`convert()` 前核对实际 Pillow 格式、扩展名和像素数量，并将解压炸弹警告与错误统一转换为 `InvalidImageError`。
- RED：伪造元数据 5 项、临时写入故障 3 项、资源限制/异常分类 3 项均先在旧实现失败。
- GREEN：`.venv\\Scripts\\python.exe -m pytest tests/test_image_assets.py -v`，23 passed；`.venv\\Scripts\\python.exe -m pytest tests/test_config.py tests/test_image_assets.py -q`，28 passed；`git diff --check` 无输出。
