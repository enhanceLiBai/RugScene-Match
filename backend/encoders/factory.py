"""根据运行配置创建图片编码器。"""

import os

from backend.config import Settings
from backend.encoders.base import ImageEncoder


def create_encoder(settings: Settings) -> ImageEncoder:
    """创建配置指定的编码器，并先固定其依赖的持久化缓存位置。"""
    if settings.image_encoder != "open_clip":
        raise ValueError(f"不支持的图片编码器：{settings.image_encoder}")

    # OpenCLIP 会在导入或加载期间初始化 Torch/Hugging Face；必须先限制缓存目录。
    os.environ.update(settings.cache_environment())
    from backend.encoders.open_clip import OpenClipEncoder

    return OpenClipEncoder(settings)
