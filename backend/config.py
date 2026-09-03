"""项目内运行环境与后端配置。"""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL


@dataclass(frozen=True)
class Settings:
    """集中保存后端运行所需的路径、数据库及编码器配置。"""

    project_root: Path
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    image_encoder: str
    clip_model_name: str
    clip_pretrained: str
    model_device: str

    @property
    def venv_dir(self) -> Path:
        """返回项目私有虚拟环境路径，避免污染用户环境。"""
        return self.project_root / ".venv"

    @property
    def image_dir(self) -> Path:
        """返回图库目录；图片二进制只允许持久化在此目录。"""
        return self.project_root / "data" / "images"

    @classmethod
    def load(cls, project_root: Path | None = None) -> "Settings":
        """从项目 .env 和进程环境变量读取配置，后者优先。"""
        root = (project_root or Path(__file__).resolve().parent.parent).resolve()
        # override=False 保留部署环境显式注入的配置，避免 .env 覆盖它们。
        load_dotenv(dotenv_path=root / ".env", override=False, encoding="utf-8")

        password = os.getenv("POSTGRES_PASSWORD")
        if not password:
            raise ValueError("缺少 POSTGRES_PASSWORD，请在环境变量或项目 .env 中配置数据库密码。")

        return cls(
            project_root=root,
            postgres_host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
            postgres_port=int(os.getenv("POSTGRES_PORT", "5432")),
            postgres_db=os.getenv("POSTGRES_DB", "carpet_matcher"),
            postgres_user=os.getenv("POSTGRES_USER", "postgres"),
            postgres_password=password,
            image_encoder=os.getenv("IMAGE_ENCODER", "open_clip"),
            clip_model_name=os.getenv("CLIP_MODEL_NAME", "ViT-B-32"),
            clip_pretrained=os.getenv("CLIP_PRETRAINED", "openai"),
            model_device=os.getenv("MODEL_DEVICE", "auto"),
        )

    def cache_environment(self) -> dict[str, str]:
        """返回供子进程继承的项目私有依赖与模型缓存配置。"""
        cache_root = self.project_root / ".cache"
        huggingface_root = cache_root / "huggingface"
        return {
            "PIP_CACHE_DIR": str(cache_root / "pip"),
            "TORCH_HOME": str(cache_root / "torch"),
            "HF_HOME": str(huggingface_root),
            "HUGGINGFACE_HUB_CACHE": str(huggingface_root / "hub"),
        }

    def database_url(self, database: str | None = None) -> URL:
        """构造数据库 URL，交由 SQLAlchemy 正确处理密码中的保留字符。"""
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=database or self.postgres_db,
        )
