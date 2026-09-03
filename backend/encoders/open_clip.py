"""OpenCLIP 图片编码器的延迟加载适配器。"""

import importlib
import os
from threading import Lock
from typing import Any

import numpy as np
from PIL import Image

from backend.config import Settings
from backend.encoders.base import EncoderIdentity, normalize_embedding


class OpenClipEncoder:
    """将 OpenCLIP 模型包装为可替换的图片编码器。"""

    def __init__(self, settings: Settings) -> None:
        """仅保存配置，不在构造阶段导入或下载模型。"""
        self._settings = settings
        self._runtime: tuple[Any, Any, Any, str, EncoderIdentity] | None = None
        self._load_lock = Lock()

        # 即使直接实例化适配器，也要在日后导入依赖前固定项目内缓存位置。
        os.environ.update(settings.cache_environment())

    @property
    def identity(self) -> EncoderIdentity:
        """首次访问时加载模型，并返回由真实输出维度确定的身份。"""
        return self._ensure_runtime()[4]

    def encode(self, image: Image.Image) -> np.ndarray:
        """将输入转换为 RGB，并编码为归一化的 float32 单位向量。"""
        model, preprocess, torch, device, _identity = self._ensure_runtime()
        return self._encode_with_runtime(model, preprocess, torch, device, image.convert("RGB"))

    def _ensure_runtime(self) -> tuple[Any, Any, Any, str, EncoderIdentity]:
        """用双重检查锁保证并发首次访问只会初始化一套模型。"""
        runtime = self._runtime
        if runtime is not None:
            return runtime

        with self._load_lock:
            runtime = self._runtime
            if runtime is not None:
                return runtime

            # OpenCLIP/Torch 的导入可能读取缓存变量，故在导入前再次明确设置。
            os.environ.update(self._settings.cache_environment())
            torch = importlib.import_module("torch")
            open_clip = importlib.import_module("open_clip")
            device = self._select_device(torch)
            model, _unused, preprocess = open_clip.create_model_and_transforms(
                self._settings.clip_model_name,
                pretrained=self._settings.clip_pretrained,
                device=device,
            )
            model.eval()

            # 不写死输出维度；用同一模型的安全空白图探测其真实视觉输出。
            sample_vector = self._encode_with_runtime(
                model,
                preprocess,
                torch,
                device,
                Image.new("RGB", (1, 1)),
            )
            identity = EncoderIdentity(
                encoder="open_clip",
                model_name=self._settings.clip_model_name,
                pretrained=self._settings.clip_pretrained,
                dimension=int(sample_vector.size),
            )
            self._runtime = (model, preprocess, torch, device, identity)
            return self._runtime

    def _select_device(self, torch: Any) -> str:
        """解析 auto 设备；显式配置由调用方负责其可用性。"""
        if self._settings.model_device != "auto":
            return self._settings.model_device
        return "cuda" if torch.cuda.is_available() else "cpu"

    @staticmethod
    def _encode_with_runtime(model: Any, preprocess: Any, torch: Any, device: str, image: Image.Image) -> np.ndarray:
        """执行单图推理并统一校验模型输出的形状和值域。"""
        batch = preprocess(image).unsqueeze(0).to(device)
        with torch.inference_mode():
            output = model.encode_image(batch)

        values = np.asarray(output.detach().cpu().numpy())
        if values.ndim == 2 and values.shape[0] == 1:
            values = values[0]
        return normalize_embedding(values)
