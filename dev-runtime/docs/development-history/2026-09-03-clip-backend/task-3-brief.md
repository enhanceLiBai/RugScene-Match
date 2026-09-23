# Task 3 实现简报：可替换编码器与 OpenCLIP

## 目标

按计划 Task 3，以 TDD 新增编码器协议、向量归一化、配置驱动工厂和延迟加载的 OpenCLIP 适配器。业务层只能依赖 `ImageEncoder`，不得绑定 OpenCLIP。

## 文件与接口

- `backend/encoders/__init__.py`
- `backend/encoders/base.py`
- `backend/encoders/open_clip.py`
- `backend/encoders/factory.py`
- `tests/test_encoder_contract.py`
- `tests/test_open_clip_smoke.py`

公开接口遵守计划：`EncoderIdentity`、`ImageEncoder`、`normalize_embedding()`、`OpenClipEncoder`、`create_encoder(settings)`。

## 规则

- `normalize_embedding` 输出一维 `np.float32`，拒绝空、多维、NaN、Infinity、零范数，结果 L2 范数约为 1。
- OpenCLIP 构造阶段绝不导入/下载/加载模型；第一次读 `identity` 或 `encode()` 才加载一次，需并发安全。
- `auto` 设备按 `torch.cuda.is_available()` 选择；显式设备原样尊重。模型调用 `eval()`，推理使用 `torch.inference_mode()`。
- 输入统一为 RGB。预处理输出增加 batch 维；模型输出在 CPU 上转 NumPy 后走统一归一化。
- 模型维度从真实模型视觉输出推导或以一次安全探测确定，不能写死 512。
- `create_encoder` 只识别配置值 `open_clip`，未知值抛含“不支持的图片编码器”的中文错误。
- 在导入/加载 OpenCLIP 前应用 `settings.cache_environment()`，确保 Torch/Hugging Face 持久化缓存均在项目 `.cache/`；不得修改用户级环境变量。
- 单元测试必须用 fake/mocking 验证延迟加载、只加载一次、设备选择、eval/inference mode，不下载权重。
- 真实模型测试仅在 `RUN_MODEL_TESTS=1` 时运行，其余情况明确 skip，并标记 `model`。
- 必要注释使用简体中文；不要读取/输出 `.env` 或凭据；不实现数据库/服务/API；不派生子智能体。

## TDD 与验证

先运行缺失模块的红测试，再实现。最终运行：

- `.venv\Scripts\python.exe -m pytest tests/test_encoder_contract.py -v`
- `.venv\Scripts\python.exe -m pytest tests/test_open_clip_smoke.py -q`（默认应 skip，不能下载）
- `.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_image_assets.py tests/test_encoder_contract.py -q`
- `git diff --check`

完成后提交当前分支，并写 `.superpowers/sdd/2026-09-03-clip-backend/task-3-report.md`，记录红/绿证据、提交 SHA、自审结论。
