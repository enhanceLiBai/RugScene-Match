"""图片建库和相似检索的应用服务。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

import numpy as np
from sqlalchemy import select

from backend.encoders.base import EncoderIdentity, ImageEncoder
from backend.image_assets import _SUPPORTED_EXTENSIONS, store_image, validate_image
from backend.models import ImageEmbedding, ImageRecord
from backend.repository import ImageRepository, SearchRow


class ImportStatus(str, Enum):
    """单张图片导入的最终业务状态。"""

    IMPORTED = "IMPORTED"
    DUPLICATE = "DUPLICATE"
    EMBEDDING_ADDED = "EMBEDDING_ADDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ImportResult:
    """导入结果保留原始路径，便于 CLI 汇总和定位失败文件。"""

    path: Path
    status: ImportStatus
    message: str


@dataclass(frozen=True)
class SearchResult:
    """面向 CLI/API 的检索结果，包含已计算的名次和相似度。"""

    rank: int
    image_id: int
    original_name: str
    stored_path: str
    sha256: str
    mime_type: str
    width: int
    height: int
    encoder: str
    model_name: str
    pretrained: str
    dimension: int
    cosine_distance: float
    similarity_percent: float


class LibraryService:
    """编排图片校验、持久化和编码器；不绑定任何具体模型实现。"""

    def __init__(
        self,
        *,
        repository: ImageRepository,
        encoder: ImageEncoder,
        image_dir: Path,
        project_root: Path,
    ) -> None:
        """使用调用方注入的仓库和编码器，事务仅覆盖单张图片。"""
        self.repository = repository
        self.encoder = encoder
        self.image_dir = image_dir
        self.project_root = project_root

    def import_path(self, path: Path) -> list[ImportResult]:
        """导入单个文件或目录；目录中每张图片失败互不影响。"""
        source = Path(path)
        if not source.exists():
            raise ValueError(f"导入路径不存在：{source.name or source}")
        if source.is_file():
            return [self._import_one(source)]
        if not source.is_dir():
            raise ValueError(f"导入路径不是文件或目录：{source.name or source}")
        return [self._import_one(item) for item in self._iter_images(source)]

    def search(self, path: Path, top_k: int = 5) -> list[SearchResult]:
        """只在内存中校验和编码查询图，不创建文件或数据库记录。"""
        self._validate_top_k(top_k)
        validated = validate_image(Path(path))
        identity = self.encoder.identity
        query = self.encoder.encode(validated.image)
        rows = self.repository.search(identity, query, top_k, excluded_sha256=validated.sha256)
        return [self._search_result(rank, row) for rank, row in enumerate(rows, start=1)]

    def _iter_images(self, directory: Path) -> Iterable[Path]:
        """稳定递归列出支持的扩展名，避免不同系统遍历顺序改变导入输出。"""
        candidates = (item for item in directory.rglob("*") if item.is_file() and item.suffix.lower() in _SUPPORTED_EXTENSIONS)
        return sorted(candidates, key=lambda item: str(item.resolve()).replace("\\", "/").casefold())

    def _import_one(self, source: Path) -> ImportResult:
        """执行一张图片的完整工作单元，并在失败时回滚该图片的副作用。"""
        stored_path: Path | None = None
        created_library_file = False
        try:
            validated = validate_image(source)
            identity = self.encoder.identity
            image = self.repository.find_by_sha256(validated.sha256)
            if image is not None and self._has_embedding(image, identity):
                return ImportResult(source, ImportStatus.DUPLICATE, "图片与当前模型向量已存在。")

            if image is None:
                target = self.image_dir / f"{validated.sha256}{validated.extension}"
                existed_before = target.exists()
                stored_path = store_image(source, validated, self.image_dir)
                # 仅清理本次开始前不存在的目标；已有图库文件永远不受失败事务影响。
                created_library_file = not existed_before
                image = self.repository.add_image(
                    original_name=validated.original_name,
                    stored_path=self._relative_stored_path(stored_path),
                    sha256=validated.sha256,
                    mime_type=validated.mime_type,
                    width=validated.width,
                    height=validated.height,
                )
                status = ImportStatus.IMPORTED
                success_message = "图片及当前模型向量已导入。"
            else:
                status = ImportStatus.EMBEDDING_ADDED
                success_message = "已有图片已补充当前模型向量。"

            embedding = self.encoder.encode(validated.image)
            self.repository.upsert_embedding(image, identity, embedding)
            self._commit()
            return ImportResult(source, status, success_message)
        except Exception:
            self._rollback()
            if created_library_file and stored_path is not None:
                stored_path.unlink(missing_ok=True)
            # 导入记录不能携带数据库 URI、密码或模型下载的内部细节。
            return ImportResult(source, ImportStatus.FAILED, "导入失败，请检查图片内容、模型和数据库连接。")

    def _has_embedding(self, image: object, identity: EncoderIdentity) -> bool:
        """兼容最小仓库接口，同时在现有仓库中精确匹配完整模型身份。"""
        checker = getattr(self.repository, "has_embedding", None)
        if checker is not None:
            return bool(checker(image, identity))
        session = getattr(self.repository, "_session", None)
        if session is None or not isinstance(image, ImageRecord):
            raise TypeError("仓库缺少当前模型向量查询能力。")
        statement = select(ImageEmbedding.id).where(
            ImageEmbedding.image_id == image.id,
            ImageEmbedding.encoder == identity.encoder,
            ImageEmbedding.model_name == identity.model_name,
            ImageEmbedding.pretrained == identity.pretrained,
            ImageEmbedding.dimension == identity.dimension,
        )
        return session.scalar(statement) is not None

    def _commit(self) -> None:
        """服务拥有事务边界；兼容测试替身和 SQLAlchemy 仓库。"""
        committer = getattr(self.repository, "commit", None)
        if committer is not None:
            committer()
            return
        self.repository._session.commit()

    def _rollback(self) -> None:
        """仅回滚当前图片，确保目录导入能继续处理后续候选。"""
        rollback = getattr(self.repository, "rollback", None)
        if rollback is not None:
            rollback()
            return
        self.repository._session.rollback()

    def _relative_stored_path(self, stored_path: Path) -> str:
        """仓库只接收项目根目录内的相对 POSIX 路径。"""
        try:
            return stored_path.resolve().relative_to(self.project_root.resolve()).as_posix()
        except ValueError as error:
            raise ValueError("图库目录必须位于项目根目录内。") from error

    @staticmethod
    def _validate_top_k(top_k: int) -> None:
        """技术验证阶段限制候选数，避免 CLI 误发大范围全表扫描。"""
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 50:
            raise ValueError("top_k 必须是 1 到 50 之间的整数。")

    @staticmethod
    def _search_result(rank: int, row: SearchRow) -> SearchResult:
        """将仓库行映射为稳定的应用层结果。"""
        return SearchResult(rank=rank, **row.__dict__)
