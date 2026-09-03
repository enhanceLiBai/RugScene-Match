"""可替换图片编码器的公开契约测试。"""

from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from backend.config import Settings
from backend.encoders.base import EncoderIdentity, ImageEncoder, normalize_embedding
from backend.encoders.factory import create_encoder
from backend.encoders.open_clip import OpenClipEncoder


class FakeEncoder:
    """用确定性向量验证业务依赖的编码器契约。"""

    def __init__(self, values: list[float]) -> None:
        self._values = values

    @property
    def identity(self) -> EncoderIdentity:
        return EncoderIdentity("fake", "test-model", "test-weights", len(self._values))

    def encode(self, image: Image.Image) -> np.ndarray:
        return normalize_embedding(np.asarray(self._values))


def assert_encoder_contract(encoder: ImageEncoder, image: Image.Image) -> None:
    """断言业务层可依赖的归一化向量边界。"""
    vector = encoder.encode(image)

    assert vector.shape == (encoder.identity.dimension,)
    assert vector.dtype == np.float32
    assert np.isfinite(vector).all()
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-5)


def test_fake_encoder_satisfies_contract() -> None:
    """向量接口必须产出与模型身份维度一致的单位向量。"""
    assert_encoder_contract(FakeEncoder([3.0, 4.0]), Image.new("RGB", (4, 4)))


@pytest.mark.parametrize(
    "values",
    [
        np.asarray([], dtype=np.float32),
        np.asarray([[1.0, 2.0]], dtype=np.float32),
        np.asarray([np.nan], dtype=np.float32),
        np.asarray([np.inf], dtype=np.float32),
        np.asarray([0.0, 0.0], dtype=np.float32),
    ],
)
def test_normalize_embedding_rejects_invalid_vectors(values: np.ndarray) -> None:
    """无效输出若进入向量库会破坏相似度计算，必须在边界拒绝。"""
    with pytest.raises(ValueError):
        normalize_embedding(values)


def test_normalize_embedding_returns_float32_unit_vector() -> None:
    """不同数值类型的有限一维输出必须统一成 float32 单位向量。"""
    vector = normalize_embedding(np.asarray([3, 4], dtype=np.int64))

    assert vector.dtype == np.float32
    assert vector.tolist() == pytest.approx([0.6, 0.8])
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize(
    ("encoder", "model_name", "pretrained", "dimension"),
    [
        ("", "model", "weights", 1),
        ("open_clip", "", "weights", 1),
        ("open_clip", "model", "", 1),
        ("open_clip", "model", "weights", 0),
        ("open_clip", "model", "weights", -1),
        ("open_clip", "model", "weights", True),
        ("open_clip", "model", "weights", 1.5),
        ("open_clip", "model", "weights", float("nan")),
        ("open_clip", "model", "weights", float("inf")),
    ],
)
def test_encoder_identity_rejects_incomplete_vector_space(
    encoder: str, model_name: str, pretrained: str, dimension: object
) -> None:
    """缺失身份或非正整数维度会令持久化向量空间不可安全区分，必须拒绝。"""
    with pytest.raises(ValueError):
        EncoderIdentity(encoder, model_name, pretrained, dimension)


def test_factory_rejects_unknown_encoder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """未注册实现不能悄然回退到其他模型，避免混用向量空间。"""
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")
    settings = replace(Settings.load(tmp_path), image_encoder="unknown")

    with pytest.raises(ValueError, match="不支持的图片编码器"):
        create_encoder(settings)


class FakeTensor:
    """模拟本任务使用到的最小 Torch 张量边界。"""

    def __init__(self, values: object) -> None:
        self.values = np.asarray(values, dtype=np.float32)

    def unsqueeze(self, axis: int) -> "FakeTensor":
        return FakeTensor(np.expand_dims(self.values, axis))

    def to(self, _device: str) -> "FakeTensor":
        return self

    def detach(self) -> "FakeTensor":
        return self

    def cpu(self) -> "FakeTensor":
        return self

    def numpy(self) -> np.ndarray:
        return self.values


class FakeInferenceMode:
    """记录推理上下文，验证模型调用不会构建梯度图。"""

    def __init__(self) -> None:
        self.entries = 0

    def __enter__(self) -> None:
        self.entries += 1

    def __exit__(self, *_args: object) -> None:
        return None


class FakeModel:
    """以固定视觉输出代替真实模型，避免单元测试下载权重。"""

    def __init__(self) -> None:
        self.eval_calls = 0
        self.encode_calls = 0

    def eval(self) -> "FakeModel":
        self.eval_calls += 1
        return self

    def encode_image(self, _batch: FakeTensor) -> FakeTensor:
        self.encode_calls += 1
        return FakeTensor([[3.0, 4.0, 0.0]])


class FakeOpenClipRuntime:
    """记录 OpenCLIP 创建参数和预处理输入。"""

    def __init__(self) -> None:
        self.model = FakeModel()
        self.create_calls: list[tuple[str, str, str]] = []
        self.preprocess_modes: list[str] = []

    def create_model_and_transforms(self, model_name: str, *, pretrained: str, device: str) -> tuple[FakeModel, None, object]:
        self.create_calls.append((model_name, pretrained, device))

        def preprocess(image: Image.Image) -> FakeTensor:
            self.preprocess_modes.append(image.mode)
            return FakeTensor([1.0])

        return self.model, None, preprocess


class FakeTorchRuntime:
    """提供设备检测和 inference_mode，隔离真实 Torch 运行时。"""

    def __init__(self, cuda_available: bool) -> None:
        self.cuda = type("Cuda", (), {"is_available": staticmethod(lambda: cuda_available)})()
        self.mode = FakeInferenceMode()

    def inference_mode(self) -> FakeInferenceMode:
        return self.mode


def make_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **changes: str) -> Settings:
    """生成不读取项目凭据的测试专用编码器配置。"""
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")
    return replace(Settings.load(tmp_path), **changes)


def test_open_clip_constructor_defers_runtime_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """构造编码器不得导入 OpenCLIP，避免健康检查触发模型下载。"""
    import backend.encoders.open_clip as open_clip_module

    def import_must_not_run(_name: str) -> object:
        raise AssertionError("OpenCLIP runtime import during construction")

    monkeypatch.setattr(open_clip_module.importlib, "import_module", import_must_not_run)

    OpenClipEncoder(make_settings(tmp_path, monkeypatch))


def test_open_clip_loads_once_uses_rgb_and_inference_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """首次使用加载一次模型，并将 RGB 图片编码为单位向量。"""
    import backend.encoders.open_clip as open_clip_module

    torch = FakeTorchRuntime(cuda_available=False)
    open_clip = FakeOpenClipRuntime()
    imported: list[str] = []

    def import_runtime(name: str) -> object:
        imported.append(name)
        return {"torch": torch, "open_clip": open_clip}[name]

    monkeypatch.setattr(open_clip_module.importlib, "import_module", import_runtime)
    encoder = OpenClipEncoder(make_settings(tmp_path, monkeypatch))

    first_identity = encoder.identity
    second_identity = encoder.identity
    vector = encoder.encode(Image.new("RGBA", (4, 4), (1, 2, 3, 4)))

    assert first_identity == EncoderIdentity("open_clip", "ViT-B-32", "openai", 3)
    assert second_identity == first_identity
    assert vector.tolist() == pytest.approx([0.6, 0.8, 0.0])
    assert imported == ["torch", "open_clip"]
    assert open_clip.create_calls == [("ViT-B-32", "openai", "cpu")]
    assert open_clip.model.eval_calls == 1
    assert open_clip.model.encode_calls == 2
    assert torch.mode.entries == 2
    assert open_clip.preprocess_modes == ["RGB", "RGB"]


@pytest.mark.parametrize(
    ("requested", "cuda_available", "expected"),
    [("auto", True, "cuda"), ("auto", False, "cpu"), ("mps", False, "mps")],
)
def test_open_clip_selects_configured_device(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    requested: str,
    cuda_available: bool,
    expected: str,
) -> None:
    """自动设备只按 CUDA 可用性判断，显式设备配置必须被尊重。"""
    import backend.encoders.open_clip as open_clip_module

    torch = FakeTorchRuntime(cuda_available=cuda_available)
    open_clip = FakeOpenClipRuntime()
    monkeypatch.setattr(
        open_clip_module.importlib,
        "import_module",
        lambda name: {"torch": torch, "open_clip": open_clip}[name],
    )

    encoder = OpenClipEncoder(make_settings(tmp_path, monkeypatch, model_device=requested))

    assert encoder.identity.dimension == 3
    assert open_clip.create_calls == [("ViT-B-32", "openai", expected)]


def test_factory_applies_project_cache_before_constructing_open_clip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """工厂必须在 OpenCLIP 有机会导入前固定项目内缓存位置。"""
    settings = make_settings(tmp_path, monkeypatch)
    for name in settings.cache_environment():
        monkeypatch.delenv(name, raising=False)

    encoder = create_encoder(settings)

    assert isinstance(encoder, OpenClipEncoder)
    assert {name: __import__("os").environ[name] for name in settings.cache_environment()} == settings.cache_environment()
