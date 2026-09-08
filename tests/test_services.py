"""建库与检索服务的业务行为测试。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import threading
import uuid

import numpy as np
from PIL import Image
import pytest
from sqlalchemy.orm import Session

import backend.services as services_module
from backend.config import Settings
from backend.db import create_database_and_schema, create_session_factory, dispose_session_factory
from backend.encoders.base import EncoderIdentity, normalize_embedding
from backend.image_assets import StoredImage, ValidatedImage, validate_image, validate_image_bytes
from backend.repository import ImageMetadata, ImageRepository, SearchRow
from backend.services import ImportResult, ImportStatus, LibraryService


def make_png(path: Path, color: str = "red") -> Path:
    """创建小型有效 PNG，避免服务单元测试依赖真实模型。"""
    Image.new("RGB", (8, 6), color).save(path)
    return path


def png_bytes(color: str = "red") -> bytes:
    """生成用于内存上传场景的真实 PNG 字节。"""
    output = BytesIO()
    Image.new("RGB", (8, 6), color).save(output, format="PNG")
    return output.getvalue()


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
    sku: str | None = None
    product_name: str | None = None
    size: str | None = None
    price: Decimal | None = None
    room: str | None = None
    style: str | None = None
    color: str | None = None
    stock: str | None = None
    selling_point: str | None = None


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

    def find_by_id(self, image_id: int | None) -> FakeImage | None:
        return next((image for image in self.images.values() if image.id == image_id), None)

    def has_embedding(self, image: FakeImage, identity: EncoderIdentity) -> bool:
        return (image.id, identity) in self.embeddings

    def add_image(self, **values: object) -> FakeImage:
        image = FakeImage(self._next_id, str(values["sha256"]))
        self._next_id += 1
        self.images[image.sha256] = image
        return image

    def update_metadata(self, image: FakeImage, metadata: ImageMetadata) -> None:
        for field in ImageMetadata.__dataclass_fields__:
            value = getattr(metadata, field)
            if value is not None:
                setattr(image, field, value)

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


def test_import_bytes_persists_metadata_and_duplicate_updates_nonblank_fields(
    service: LibraryService, repository: FakeRepository
) -> None:
    """重复上传同一字节时应保留已有资料并补充新的非空字段。"""
    data = png_bytes("red")

    first = service.import_bytes(data, "buyer.png", ImageMetadata(product_name="云朵", sku="CT-1"))
    second = service.import_bytes(data, "buyer.png", ImageMetadata(room="客厅"))

    assert first.status is ImportStatus.IMPORTED
    assert second.status is ImportStatus.DUPLICATE
    assert first.image_id == second.image_id
    image = repository.find_by_id(first.image_id)
    assert image is not None
    assert image.product_name == "云朵"
    assert image.sku == "CT-1"
    assert image.room == "客厅"


def test_import_bytes_encoding_failure_rolls_back_and_removes_only_new_file(
    service: LibraryService, repository: FakeRepository, tmp_path: Path
) -> None:
    """内存上传编码失败时仅清理本次新建文件，已有图库文件必须保留。"""
    data = png_bytes("blue")
    sentinel = tmp_path / "library" / "sentinel.png"
    sentinel.parent.mkdir()
    sentinel.write_bytes(b"keep")

    class FailingEncoder(FakeEncoder):
        def encode(self, _image: Image.Image) -> np.ndarray:
            raise RuntimeError("编码失败")

    service.encoder = FailingEncoder()
    result = service.import_bytes(data, "buyer.png", ImageMetadata(product_name="云朵"))

    assert result.status is ImportStatus.FAILED
    assert result.image_id is None
    assert not any(path.name != "sentinel.png" for path in (tmp_path / "library").iterdir())
    assert sentinel.read_bytes() == b"keep"
    assert repository.rollbacks == 1


def test_import_bytes_race_failure_keeps_file_created_by_other_request(
    service: LibraryService, repository: FakeRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """链接瞬间由其他请求创建目标时，本请求失败不得删除对方文件。"""
    data = png_bytes("blue")
    validated = validate_image_bytes(data, "buyer.png")
    target = tmp_path / "library" / f"{validated.sha256}.png"

    def competitor_wins(_temporary: object, destination: object, *_args: object, **_kwargs: object) -> None:
        Path(destination).write_bytes(b"concurrent-library-content")
        raise FileExistsError

    class FailingEncoder(FakeEncoder):
        def encode(self, _image: Image.Image) -> np.ndarray:
            raise RuntimeError("编码失败")

    monkeypatch.setattr("backend.image_assets.os.link", competitor_wins)
    service.encoder = FailingEncoder()

    result = service.import_bytes(data, "buyer.png", ImageMetadata())

    assert result.status is ImportStatus.FAILED
    assert target.read_bytes() == b"concurrent-library-content"
    assert repository.rollbacks == 1


def test_same_sha_two_sessions_keep_file_when_failed_import_precedes_successful_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同哈希的失败事务不能删除另一会话随后成功提交所依赖的图库文件。"""
    settings = Settings.load()
    create_database_and_schema(settings)
    session_factory = create_session_factory(settings)
    data = png_bytes(f"#{uuid.uuid4().hex[:6]}")
    validated = validate_image_bytes(data, "first.png")
    image_dir = tmp_path / "data" / "images"
    start = threading.Barrier(2)
    lock_handoff = threading.Barrier(2)
    first_lock_acquired = threading.Event()
    second_lock_attempted = threading.Event()
    advisory_lock_used = threading.Event()
    first_file_stored = threading.Event()
    second_file_stored = threading.Event()
    results: dict[str, ImportResult] = {}
    errors: list[BaseException] = []

    class CoordinatedRepository(ImageRepository):
        """真实仓库加少量测试协调点，确保两个事务竞争同一个哈希。"""

        def __init__(self, session: Session, worker: str) -> None:
            super().__init__(session)
            self.worker = worker

        def lock_sha256(self, sha256: str) -> None:
            advisory_lock_used.set()
            if self.worker == "first":
                super().lock_sha256(sha256)
                first_lock_acquired.set()
                lock_handoff.wait(timeout=10)
                assert second_lock_attempted.wait(timeout=10)
                return
            assert first_lock_acquired.wait(timeout=10)
            lock_handoff.wait(timeout=10)
            second_lock_attempted.set()
            super().lock_sha256(sha256)

    original_store = services_module.store_image_with_ownership

    def coordinated_store(source: Path, image: ValidatedImage, destination: Path) -> StoredImage:
        if source.name == "second.png":
            assert first_file_stored.wait(timeout=10)
            stored = original_store(source, image, destination)
            second_file_stored.set()
            return stored
        stored = original_store(source, image, destination)
        first_file_stored.set()
        return stored

    class FirstEncoder(FakeEncoder):
        def encode(self, _image: Image.Image) -> np.ndarray:
            if not advisory_lock_used.is_set():
                assert second_file_stored.wait(timeout=10)
            raise RuntimeError("first import fails after storing the shared file")

    def run(worker: str) -> None:
        session = session_factory()
        try:
            repository = CoordinatedRepository(session, worker)
            service = LibraryService(
                repository=repository,
                encoder=FirstEncoder() if worker == "first" else FakeEncoder(),
                image_dir=image_dir,
                project_root=tmp_path,
            )
            start.wait(timeout=10)
            name = "first.png" if worker == "first" else "second.png"
            results[worker] = service.import_bytes(data, name, ImageMetadata())
        except BaseException as error:  # 线程中的断言需回传给主测试线程。
            errors.append(error)
        finally:
            session.close()

    first = threading.Thread(target=run, args=("first",), daemon=True)
    second = threading.Thread(target=run, args=("second",), daemon=True)
    try:
        monkeypatch.setattr(services_module, "store_image_with_ownership", coordinated_store)
        first.start()
        second.start()
        first.join(timeout=15)
        second.join(timeout=15)

        assert not first.is_alive()
        assert not second.is_alive()
        assert not errors
        assert results["first"].status is ImportStatus.FAILED
        assert results["second"].status is ImportStatus.IMPORTED
        assert (image_dir / f"{validated.sha256}.png").is_file()
    finally:
        first.join(timeout=1)
        second.join(timeout=1)
        cleanup = session_factory()
        try:
            record = ImageRepository(cleanup).find_by_sha256(validated.sha256)
            if record is not None:
                cleanup.delete(record)
                cleanup.commit()
        finally:
            cleanup.close()
            dispose_session_factory(session_factory)


def test_import_keeps_new_file_when_commit_acknowledgement_is_lost(
    tmp_path: Path,
) -> None:
    """提交已尝试后的确认异常不能触发可能删除已提交文件的补偿。"""

    class CommitAcknowledgementLossRepository(FakeRepository):
        def commit(self) -> None:
            super().commit()
            raise ConnectionError("commit acknowledgement lost")

    uncertain_repository = CommitAcknowledgementLossRepository()
    uncertain_service = LibraryService(
        repository=uncertain_repository,
        encoder=FakeEncoder(),
        image_dir=tmp_path / "library",
        project_root=tmp_path,
    )
    data = png_bytes("purple")
    validated = validate_image_bytes(data, "buyer.png")

    result = uncertain_service.import_bytes(data, "buyer.png", ImageMetadata())

    assert result.status is ImportStatus.FAILED
    assert (tmp_path / "library" / f"{validated.sha256}.png").is_file()
    assert uncertain_repository.commits == 1
    assert uncertain_repository.rollbacks == 1


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
