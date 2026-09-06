"""建库与检索服务的业务行为测试。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from backend.encoders.base import EncoderIdentity, normalize_embedding
from backend.image_assets import validate_image
from backend.repository import SearchRow
from backend.services import ImportStatus, LibraryService


def make_png(path: Path, color: str = "red") -> Path:
    """创建小型有效 PNG，避免服务单元测试依赖真实模型。"""
    Image.new("RGB", (8, 6), color).save(path)
    return path


class FakeEncoder:
    """返回固定单位向量的可替换编码器。"""

    identity = EncoderIdentity("fake", "test-model", "v1", 3)

    def __init__(self) -> None:
        self.encode_calls = 0

    def encode(self, _image: Image.Image) -> np.ndarray:
        self.encode_calls += 1
        return normalize_embedding(np.asarray([3.0, 4.0, 0.0], dtype=np.float32))


@dataclass
class FakeImage:
    """服务写入图片记录时所需的最小数据形状。"""

    id: int
    sha256: str


class FakeRepository:
    """保持持久化可观察状态的轻量仓库替身。"""

    def __init__(self) -> None:
        self.images: dict[str, FakeImage] = {}
        self.embeddings: set[tuple[int, EncoderIdentity]] = set()
        self._next_id = 1
        self.search_rows: list[SearchRow] = []
        self.commits = 0
        self.rollbacks = 0

    def find_by_sha256(self, sha256: str) -> FakeImage | None:
        return self.images.get(sha256)

    def has_embedding(self, image: FakeImage, identity: EncoderIdentity) -> bool:
        return (image.id, identity) in self.embeddings

    def add_image(self, **values: object) -> FakeImage:
        image = FakeImage(self._next_id, str(values["sha256"]))
        self._next_id += 1
        self.images[image.sha256] = image
        return image

    def upsert_embedding(self, image: FakeImage, identity: EncoderIdentity, _embedding: np.ndarray) -> None:
        self.embeddings.add((image.id, identity))

    def search(self, _identity: EncoderIdentity, _query: np.ndarray, top_k: int, excluded_sha256: str | None) -> list[SearchRow]:
        return [row for row in self.search_rows if row.sha256 != excluded_sha256][:top_k]

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def image_count(self) -> int:
        return len(self.images)


@pytest.fixture
def repository() -> FakeRepository:
    """提供每例独立的内存仓库。"""
    return FakeRepository()


@pytest.fixture
def service(tmp_path: Path, repository: FakeRepository) -> LibraryService:
    """使用临时图库构造不涉及网络和真实数据库的服务。"""
    return LibraryService(
        repository=repository,
        encoder=FakeEncoder(),
        image_dir=tmp_path / "library",
        project_root=tmp_path,
    )


def test_import_directory_continues_after_invalid_file(service: LibraryService, repository: FakeRepository, tmp_path: Path) -> None:
    """损坏文件只影响自身，目录中后续有效图片仍应导入。"""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "broken.jpg").write_bytes(b"not-an-image")
    make_png(source_dir / "valid.png")

    results = service.import_path(source_dir)

    assert [result.status for result in results] == [ImportStatus.FAILED, ImportStatus.IMPORTED]
    assert repository.image_count() == 1
    assert repository.commits == 1


def test_import_reuses_image_and_adds_only_missing_current_model_embedding(
    service: LibraryService, repository: FakeRepository, tmp_path: Path
) -> None:
    """同一文件重复导入是重复；切换模型时只为已有图片补一个向量。"""
    source = make_png(tmp_path / "repeat.png")

    first = service.import_path(source)
    duplicate = service.import_path(source)
    service.encoder = type("OtherEncoder", (), {
        "identity": EncoderIdentity("fake", "other-model", "v1", 3),
        "encode": lambda _self, _image: normalize_embedding(np.asarray([1.0, 0.0, 0.0], dtype=np.float32)),
    })()
    added = service.import_path(source)

    assert first[0].status is ImportStatus.IMPORTED
    assert duplicate[0].status is ImportStatus.DUPLICATE
    assert added[0].status is ImportStatus.EMBEDDING_ADDED
    assert repository.image_count() == 1
    assert len(repository.embeddings) == 2


def test_import_failure_after_new_file_storage_removes_only_that_file(
    service: LibraryService, repository: FakeRepository, tmp_path: Path
) -> None:
    """新文件编码失败时，图库不得留下没有数据库记录的孤儿文件。"""
    source = make_png(tmp_path / "will-fail.png")

    class FailingEncoder(FakeEncoder):
        def encode(self, _image: Image.Image) -> np.ndarray:
            raise RuntimeError("编码失败")

    service.encoder = FailingEncoder()
    result = service.import_path(source)[0]
    validated = validate_image(source)

    assert result.status is ImportStatus.FAILED
    assert not (tmp_path / "library" / f"{validated.sha256}.png").exists()
    assert repository.rollbacks == 1


def test_search_excludes_exact_query_without_persisting_query(
    service: LibraryService, repository: FakeRepository, tmp_path: Path
) -> None:
    """查询只在内存处理，排除相同字节却保留其他角度候选。"""
    query = make_png(tmp_path / "query.png")
    query_hash = validate_image(query).sha256
    repository.search_rows = [
        SearchRow(1, "exact.png", "data/images/exact.png", query_hash, "image/png", 8, 6, "fake", "test-model", "v1", 3, 0.0, 100.0),
        SearchRow(
            2,
            "same-carpet-angle.jpg",
            "data/images/angle.jpg",
            "a" * 64,
            "image/jpeg",
            8,
            6,
            "fake",
            "test-model",
            "v1",
            3,
            0.1,
            90.0,
            product_name="云朵地毯",
            price=Decimal("899.00"),
        ),
    ]

    results = service.search(query, top_k=5)

    assert [item.original_name for item in results] == ["same-carpet-angle.jpg"]
    assert results[0].product_name == "云朵地毯"
    assert results[0].price == Decimal("899.00")
    assert repository.image_count() == 0
    assert not (tmp_path / "library").exists()


@pytest.mark.parametrize("top_k", [0, 51, True, 1.5])
def test_search_rejects_top_k_outside_safe_range(service: LibraryService, tmp_path: Path, top_k: object) -> None:
    """不合法 Top K 必须在读取图片前拒绝，避免不必要的编码开销。"""
    with pytest.raises(ValueError, match="top_k"):
        service.search(tmp_path / "missing.png", top_k=top_k)  # type: ignore[arg-type]
