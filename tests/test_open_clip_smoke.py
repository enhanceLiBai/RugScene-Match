"""真实 OpenCLIP 模型的显式冒烟测试。"""

import os
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from backend.config import Settings
from backend.encoders.open_clip import OpenClipEncoder


pytestmark = pytest.mark.model


@pytest.mark.skipif(os.getenv("RUN_MODEL_TESTS") != "1", reason="设置 RUN_MODEL_TESTS=1 后才下载并运行真实模型")
def test_open_clip_encodes_a_real_image_with_project_local_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实模型仅在显式授权时下载，权重缓存必须留在项目目录内。"""
    project_root = Path(__file__).resolve().parent.parent
    settings = Settings(
        project_root=project_root,
        postgres_host="127.0.0.1",
        postgres_port=5432,
        postgres_db="carpet_matcher",
        postgres_user="postgres",
        postgres_password="test-password",
        image_encoder="open_clip",
        clip_model_name="ViT-B-32",
        clip_pretrained="openai",
        model_device="auto",
    )
    for name in settings.cache_environment():
        monkeypatch.delenv(name, raising=False)

    managed_cache_environment_before_encode = {name: os.environ.get(name) for name in settings.cache_environment()}
    model_cache_dir = settings.project_root / ".cache" / "open_clip"
    vector = OpenClipEncoder(settings).encode(Image.new("RGB", (4, 4), "red"))

    assert vector.dtype == np.float32
    assert vector.size > 0
    assert np.isfinite(vector).all()
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-5)
    assert model_cache_dir.is_relative_to(settings.project_root / ".cache")
    assert any(item.is_file() and item.stat().st_size > 10 * 1024 * 1024 for item in model_cache_dir.rglob("*"))
    assert {name: os.environ.get(name) for name in settings.cache_environment()} == managed_cache_environment_before_encode
