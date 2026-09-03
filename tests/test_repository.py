"""PostgreSQL/pgvector 模型与仓库的集成行为测试。"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import numpy as np
import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.db import create_database_and_schema, create_session_factory, dispose_session_factory
from backend.encoders.base import EncoderIdentity
from backend.models import ImageEmbedding, ImageRecord
from backend.repository import ImageRepository, cosine_distance_to_percent


def unit(values: list[float]) -> np.ndarray:
    """构造归一化 float32 测试向量。"""
    vector = np.asarray(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def random_sha256() -> str:
    """为每个集成测试生成独立的精确文件哈希，避免碰触既有记录。"""
    return uuid.uuid4().hex + uuid.uuid4().hex


def add_test_image(repository: ImageRepository, original_name: str = "fixture.jpg") -> ImageRecord:
    """创建当前测试事务独有的图片元数据。"""
    return repository.add_image(
        original_name=original_name,
        stored_path="data\\images\\fixture.jpg",
        sha256=random_sha256(),
        mime_type="image/jpeg",
        width=12,
        height=8,
    )


@pytest.fixture(scope="session")
def settings() -> Settings:
    """读取本机数据库配置，但测试绝不回显任何连接凭据。"""
    return Settings.load()


@pytest.fixture(scope="session")
def session_factory(settings: Settings):
    """仅幂等创建本任务所需 schema，再提供会话工厂。"""
    create_database_and_schema(settings)
    factory = create_session_factory(settings)
    try:
        yield factory
    finally:
        dispose_session_factory(factory)


@pytest.fixture
def db_session(session_factory) -> Session:
    """每个测试都绑定独立外层事务，结束时统一回滚测试写入。"""
    session = session_factory()
    transaction = session.begin()
    try:
        yield session
    finally:
        transaction.rollback()
        session.close()


@pytest.fixture
def repository(db_session: Session) -> ImageRepository:
    """提供使用测试事务的仓库实例。"""
    return ImageRepository(db_session)


def test_schema_supports_multiple_models_for_one_image(repository: ImageRepository) -> None:
    """同一文件可有不同模型与维度的向量，避免模型切换时丢失历史结果。"""
    image = repository.add_image(
        original_name="multi-model.jpg",
        stored_path="data/images/multi-model.jpg",
        sha256=random_sha256(),
        mime_type="image/jpeg",
        width=12,
        height=8,
    )
    repository.upsert_embedding(image, EncoderIdentity("fake", "a", "v1", 3), unit([1, 0, 0]))
    repository.upsert_embedding(image, EncoderIdentity("fake", "b", "v1", 2), unit([1, 0]))

    assert repository.embedding_count(image.id) == 2


def test_schema_uses_fixed_length_sha256_column(db_session: Session) -> None:
    """精确去重哈希必须是规格要求的 char(64)，避免列定义随实现漂移。"""
    column_type = db_session.execute(
        text(
            """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'images' AND column_name = 'sha256'
        """
        )
    ).scalar_one()

    assert column_type == "character"


def test_schema_initialization_is_idempotent_and_enables_vector(settings: Settings, db_session: Session) -> None:
    """重复初始化只能补齐缺失对象，不能依赖重建或清空既有数据库。"""
    create_database_and_schema(settings)
    create_database_and_schema(settings)

    assert db_session.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar_one()


def test_dispose_session_factory_disposes_its_bound_engine() -> None:
    """长期 CLI/API 进程可显式释放连接池，避免测试或短命令残留连接。"""
    engine = MagicMock()
    from sqlalchemy.orm import sessionmaker

    session_factory = sessionmaker(bind=engine)
    dispose_session_factory(session_factory)

    engine.dispose.assert_called_once_with()


def test_upsert_uses_postgresql_conflict_update_without_preselect() -> None:
    """同一模型向量的并发写入必须由数据库唯一约束原子仲裁。"""
    session = MagicMock()
    repository = ImageRepository(session)
    image = MagicMock(id=123)

    repository.upsert_embedding(image, EncoderIdentity("fake", "atomic", "v1", 3), unit([1, 0, 0]))

    session.scalar.assert_not_called()
    statement = session.execute.call_args.args[0]
    assert "ON CONFLICT" in str(statement.compile(dialect=dialect()))


def test_repository_finds_lists_counts_and_normalizes_relative_paths(repository: ImageRepository) -> None:
    """仓库只保存相对 POSIX 路径，并提供稳定的基础读取接口。"""
    count_before = repository.image_count()
    image = add_test_image(repository, "first.jpg")

    found = repository.find_by_sha256(image.sha256)

    assert found is not None
    assert found.id == image.id
    assert found.stored_path == "data/images/fixture.jpg"
    assert [item.id for item in repository.list_images() if item.id == image.id] == [image.id]
    assert repository.image_count() == count_before + 1


@pytest.mark.parametrize("stored_path", ["", ".", "../outside.jpg", "/absolute.jpg", "C:\\outside.jpg"])
def test_repository_rejects_non_relative_stored_paths(repository: ImageRepository, stored_path: str) -> None:
    """数据库路径若可越过项目根目录，后续图片读取接口将产生越权风险。"""
    with pytest.raises(ValueError, match="相对于项目根目录"):
        repository.add_image(
            original_name="bad-path.jpg",
            stored_path=stored_path,
            sha256=random_sha256(),
            mime_type="image/jpeg",
            width=12,
            height=8,
        )


def test_upsert_replaces_only_same_complete_model_identity(repository: ImageRepository) -> None:
    """同一模型重导入更新向量，其他模型向量必须保留。"""
    image = add_test_image(repository)
    primary = EncoderIdentity("fake", "model", "v1", 3)
    other = EncoderIdentity("fake", "model", "v2", 3)
    repository.upsert_embedding(image, primary, unit([1, 0, 0]))
    repository.upsert_embedding(image, other, unit([0, 1, 0]))
    repository.upsert_embedding(image, primary, unit([0, 0, 1]))

    rows = repository.search(primary, unit([0, 0, 1]), top_k=5)

    assert repository.embedding_count(image.id) == 2
    assert len(rows) == 1
    assert rows[0].pretrained == "v1"
    assert rows[0].similarity_percent == 100.0


def test_search_filters_full_identity_orders_by_cosine_distance_and_excludes_same_file(
    repository: ImageRepository,
) -> None:
    """检索必须隔离模型空间、按距离排序，并仅排除字节完全相同的查询文件。"""
    query_file = add_test_image(repository, "query.jpg")
    same_carpet = add_test_image(repository, "same-carpet-angle.jpg")
    other = add_test_image(repository, "other.jpg")
    unwanted_model = add_test_image(repository, "other-model.jpg")
    unwanted_weights = add_test_image(repository, "other-weights.jpg")
    unwanted_dimension = add_test_image(repository, "other-dimension.jpg")
    model_suffix = uuid.uuid4().hex
    identity = EncoderIdentity("fake", f"model-a-{model_suffix}", "v1", 3)
    repository.upsert_embedding(query_file, identity, unit([1, 0, 0]))
    repository.upsert_embedding(same_carpet, identity, unit([1, 0, 0]))
    repository.upsert_embedding(other, identity, unit([1, 1, 0]))
    repository.upsert_embedding(unwanted_model, EncoderIdentity("fake", f"model-b-{model_suffix}", "v1", 3), unit([1, 0, 0]))
    repository.upsert_embedding(unwanted_weights, EncoderIdentity("fake", f"model-a-{model_suffix}", "v2", 3), unit([1, 0, 0]))
    repository.upsert_embedding(unwanted_dimension, EncoderIdentity("fake", f"model-a-{model_suffix}", "v1", 2), unit([1, 0]))

    rows = repository.search(identity, unit([1, 0, 0]), top_k=5, excluded_sha256=query_file.sha256)

    assert [row.original_name for row in rows] == ["same-carpet-angle.jpg", "other.jpg"]
    assert [(row.encoder, row.model_name, row.pretrained, row.dimension) for row in rows] == [
        ("fake", f"model-a-{model_suffix}", "v1", 3),
        ("fake", f"model-a-{model_suffix}", "v1", 3),
    ]
    assert rows[0].similarity_percent == 100.0
    assert rows[1].similarity_percent == 70.71
    assert rows[0].stored_path == "data/images/fixture.jpg"


@pytest.mark.parametrize(
    "embedding",
    [
        np.asarray([1, 0, 0], dtype=np.float64),
        np.asarray([1, 0], dtype=np.float32),
        np.asarray([np.nan, 0, 0], dtype=np.float32),
    ],
)
def test_repository_rejects_invalid_vectors_before_write(repository: ImageRepository, embedding: np.ndarray) -> None:
    """仓库边界不能盲目信任调用者，错误向量不得进入 pgvector。"""
    image = add_test_image(repository)

    with pytest.raises(ValueError):
        repository.upsert_embedding(image, EncoderIdentity("fake", "model", "v1", 3), embedding)

    assert repository.embedding_count(image.id) == 0


@pytest.mark.parametrize(
    "embedding",
    [
        np.asarray([0, 0, 0], dtype=np.float32),
        np.asarray([2, 0, 0], dtype=np.float32),
        np.asarray([np.inf, 0, 0], dtype=np.float32),
    ],
)
def test_repository_rejects_non_unit_vectors_before_write(repository: ImageRepository, embedding: np.ndarray) -> None:
    """编码器契约要求有限的单位向量，仓库必须在写入边界重复验证。"""
    image = add_test_image(repository)

    with pytest.raises(ValueError):
        repository.upsert_embedding(image, EncoderIdentity("fake", "model", "v1", 3), embedding)

    assert repository.embedding_count(image.id) == 0


@pytest.mark.parametrize("stored_path", ["C:outside.jpg", "\\\\server\\share\\image.jpg"])
def test_repository_rejects_windows_drive_and_unc_paths(repository: ImageRepository, stored_path: str) -> None:
    """Windows drive-relative 与 UNC 路径也可能脱离项目根目录，不能写入数据库。"""
    with pytest.raises(ValueError, match="相对于项目根目录"):
        repository.add_image(
            original_name="bad-windows-path.jpg",
            stored_path=stored_path,
            sha256=random_sha256(),
            mime_type="image/jpeg",
            width=12,
            height=8,
        )


@pytest.mark.parametrize("sha256", ["A" * 64, "g" * 64, "a" * 63])
def test_repository_rejects_noncanonical_sha256_before_write(repository: ImageRepository, sha256: str) -> None:
    """哈希必须是小写 64 位十六进制文本，防止错误去重键绕过数据库约束。"""
    with pytest.raises(ValueError, match="SHA-256"):
        repository.add_image(
            original_name="bad-hash.jpg",
            stored_path="data/images/bad-hash.jpg",
            sha256=sha256,
            mime_type="image/jpeg",
            width=12,
            height=8,
        )


def test_image_count_uses_database_count_query() -> None:
    """统计记录数不应加载全表图片元数据。"""
    session = MagicMock()
    session.scalar.return_value = 7

    count = ImageRepository(session).image_count()

    assert count == 7
    session.scalars.assert_not_called()


def test_embedding_count_uses_database_count_query() -> None:
    """向量统计不应加载全部向量对象。"""
    session = MagicMock()
    session.scalar.return_value = 3

    count = ImageRepository(session).embedding_count(image_id=123)

    assert count == 3
    session.scalars.assert_not_called()


def test_cosine_distance_percentage_clamps_rounds_and_rejects_non_finite_values() -> None:
    """对 pgvector 返回值统一裁剪，避免边界浮点误差传递给 API。"""
    assert cosine_distance_to_percent(-0.1) == 100.0
    assert cosine_distance_to_percent(0.292893218) == 70.71
    assert cosine_distance_to_percent(2.0) == 0.0
    with pytest.raises(ValueError, match="有限"):
        cosine_distance_to_percent(float("nan"))


def test_database_constraints_and_cascade_apply_inside_rollback_transaction(
    repository: ImageRepository, db_session: Session
) -> None:
    """数据库约束和级联删除仅作用于本测试写入，并由外层事务统一回滚。"""
    image = add_test_image(repository)
    repository.upsert_embedding(image, EncoderIdentity("fake", "model", "v1", 3), unit([1, 0, 0]))

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                ImageRecord(
                    original_name="invalid.jpg",
                    stored_path="data/images/invalid.jpg",
                    sha256=random_sha256(),
                    mime_type="image/jpeg",
                    width=0,
                    height=8,
                )
            )
            db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                ImageEmbedding(
                    image_id=image.id,
                    encoder="fake",
                    model_name="bad-dimension",
                    pretrained="v1",
                    dimension=0,
                    embedding=unit([1, 0, 0]),
                )
            )
            db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                ImageRecord(
                    original_name="invalid-hash.jpg",
                    stored_path="data/images/invalid-hash.jpg",
                    sha256="A" * 64,
                    mime_type="image/jpeg",
                    width=12,
                    height=8,
                )
            )
            db_session.flush()

    db_session.delete(image)
    db_session.flush()
    assert repository.embedding_count(image.id) == 0
