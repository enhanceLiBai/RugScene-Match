"""根据运行配置创建图片编码器。"""

from backend.config import Settings
from backend.encoders.base import ImageEncoder


def create_encoder(settings: Settings) -> ImageEncoder:
    """创建配置指定的编码器。"""
    if settings.image_encoder != "open_clip":
        raise ValueError(f"不支持的图片编码器：{settings.image_encoder}")

    from backend.encoders.open_clip import OpenClipEncoder

    return OpenClipEncoder(settings)
