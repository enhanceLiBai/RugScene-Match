"""图片编码器的稳定抽象与向量输出校验。"""

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class EncoderIdentity:
    """标识一个不可与其他向量空间混用的图片编码模型。"""

    encoder: str
    model_name: str
    pretrained: str
    dimension: int

    def __post_init__(self) -> None:
        """拒绝不完整身份，避免把未知向量写入持久层。"""
        if not self.encoder or not self.model_name or not self.pretrained:
            raise ValueError("编码器身份字段不能为空。")
        if self.dimension <= 0:
            raise ValueError("编码器向量维度必须大于零。")


class ImageEncoder(Protocol):
    """业务层依赖的图片编码器契约。"""

    @property
    def identity(self) -> EncoderIdentity:
        """返回当前模型的持久化身份。"""

    def encode(self, image: Image.Image) -> np.ndarray:
        """将一张图片编码为有限的 float32 L2 单位向量。"""


def normalize_embedding(values: np.ndarray) -> np.ndarray:
    """校验并归一化模型输出，阻止无效向量污染相似度计算。"""
    vector = np.asarray(values, dtype=np.float32)
    if vector.ndim != 1:
        raise ValueError("图片编码向量必须是一维数组。")
    if vector.size == 0:
        raise ValueError("图片编码向量不能为空。")
    if not np.isfinite(vector).all():
        raise ValueError("图片编码向量不能包含 NaN 或 Infinity。")

    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm == 0.0:
        raise ValueError("图片编码向量范数必须为有限非零值。")
    return vector / norm
