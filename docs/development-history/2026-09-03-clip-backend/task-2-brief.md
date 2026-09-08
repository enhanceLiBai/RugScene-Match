# Task 2 实现简报：图片资产校验、哈希与安全存储

## 目标

按计划 Task 2，以测试驱动新增 `backend/image_assets.py` 和 `tests/test_image_assets.py`。只负责图片资产边界，不接触数据库、模型、服务或 API。

## 必须实现的接口

- `ValidatedImage(sha256, original_name, mime_type, width, height, extension, image)`
- `InvalidImageError`
- `validate_image(path: Path) -> ValidatedImage`
- `validate_image_bytes(data: bytes, original_name: str) -> ValidatedImage`
- `store_image(source: Path, validated: ValidatedImage, image_dir: Path) -> Path`

路径入口和字节入口必须复用同一套校验逻辑；字节入口用于后续 FastAPI 在内存中验证查询图片。

## 业务规则

- 只支持 `.jpg`、`.jpeg`、`.png`、`.webp`，扩展名判断不区分大小写。
- SHA-256 基于上传/源文件原始字节，不基于解码后的像素。
- 用 Pillow 对内容做真实校验：先 `verify()`，再重新打开、`load()`，输出 RGB 图像。
- 拒绝空数据、损坏图片、不支持扩展、零尺寸；异常只包含安全文件名，不包含二进制内容。
- MIME 和规范扩展名应由实际解码格式推导，不能盲信文件名；`.jpeg` 最终规范为 `.jpg`。
- 存储到 `image_dir/<sha256><extension>`，创建目录，重复调用幂等且不覆盖既有文件。
- 为避免 TOCTOU 和二次读取不一致，`ValidatedImage` 应保留通过校验的原始字节，或以等价方式确保落盘字节正是已计算哈希的字节。若与计划示例字段有小幅扩展，请保持向后兼容。
- 落盘应尽量原子化；临时文件只能在目标图库目录内，并确保异常清理。
- 所有必要注释使用简体中文；Python 文本文件操作必须显式 UTF-8（本任务不应需要文本读写）。
- 不读取 `.env`，不输出秘密，不派生子智能体。

## TDD 与验证

先写并运行失败测试，再实现。测试至少覆盖：RGBA 转 RGB、尺寸、原始字节哈希、字节入口、损坏内容、不支持扩展、扩展名大小写、内容格式与文件名不匹配、幂等存储、不覆盖同名既有文件、异常时不留临时文件。

最终运行：

- `.venv\Scripts\python.exe -m pytest tests/test_image_assets.py -v`
- `.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_image_assets.py -q`
- `git diff --check`

完成后提交当前分支，并写 `.superpowers/sdd/2026-09-03-clip-backend/task-2-report.md`，记录红/绿测试证据、提交 SHA 和自审结论。
