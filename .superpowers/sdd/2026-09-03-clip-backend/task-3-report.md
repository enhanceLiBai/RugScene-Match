# Task 3 报告：可替换图片编码器与 OpenCLIP

## 交付内容

- 新增 `EncoderIdentity`、`ImageEncoder` 协议与 `normalize_embedding()`；归一化输出固定为一维 `float32`，并拒绝空值、多维、NaN、Infinity 和零范数。
- 新增配置驱动的 `create_encoder()`；仅支持 `open_clip`，其他配置会返回中文错误。
- 新增 `OpenClipEncoder`：构造时不导入模型，首次读取身份或编码时在锁保护下只加载一次；模型调用 `eval()`、推理使用 `torch.inference_mode()`，设备遵循 `auto`/显式配置，向量维度由真实输出探测。
- 导入或加载前通过 `Settings.cache_environment()` 将 Torch、Hugging Face 和 pip 缓存限制在项目 `.cache/`；未读取 `.env` 或输出凭据。
- 新增不下载模型的 fake-runtime 契约测试，及默认跳过、仅在 `RUN_MODEL_TESTS=1` 时运行的真实模型冒烟测试；注册 `model` 测试标记。

## TDD 证据

- 红：首次运行 `tests/test_encoder_contract.py -v`，因 `backend.encoders` 不存在而报 `ModuleNotFoundError`。
- 红：加入 OpenCLIP 测试后，因 `backend.encoders.open_clip` 不存在而报 `ModuleNotFoundError`。
- 红：移除身份校验后运行身份边界测试，4 例均因未抛出 `ValueError` 失败；恢复最小校验后通过。
- 绿：`tests/test_encoder_contract.py -q`：`18 passed`。
- 绿：`tests/test_open_clip_smoke.py -q`（未设置 `RUN_MODEL_TESTS`）：`1 skipped`，没有下载模型。
- 绿：`tests/test_config.py tests/test_image_assets.py tests/test_encoder_contract.py -q`：`46 passed`。
- 绿：完整 Python 测试：`46 passed, 1 skipped`；`git diff --check` 与暂存差异检查均无输出。

## 自审结论

- 业务层仅依赖协议和工厂，未绑定 OpenCLIP。
- OpenCLIP、Torch 均在延迟加载路径导入；首次加载由互斥锁保护，模型身份缓存后复用。
- 单元测试以 fake runtime 覆盖延迟加载、只加载一次、RGB 转换、`eval()`、推理上下文、设备选择和项目内缓存；未联网。
- 未触碰数据库、服务、API 或任何凭据文件。

## 审查修复

- 规格审查指出 `EncoderIdentity.dimension` 原先会接受 `True`、浮点数、NaN 和 Infinity。该字段是持久化向量空间键，现仅接受非布尔的正整数。
- 红：扩展参数化测试后，`True`、`1.5`、NaN、Infinity 四例均因未抛出 `ValueError` 失败。
- 绿：修复后 contract 为 `23 passed`；默认 smoke 为 `1 skipped`；Task 1–3 组合回归为 `51 passed`；`git diff --check` 无输出。

## 提交

- 实现提交：`7e7d2967b9f5782b5622fd3f26665bd908cba90c`（`feat: add pluggable image encoders`）。
- 审查修复提交：`17153380f114498664049ed7ba46dd4a72f85eaa`（`fix: validate encoder identity dimension`）。
