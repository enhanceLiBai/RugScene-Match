"""FastAPI 接口的端到端行为测试。"""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.api import create_app
from backend.config import Settings
from backend.db import create_database_and_schema, create_session_factory, dispose_session_factory
from backend.encoders.base import EncoderIdentity, normalize_embedding
from backend.repository import ImageRepository


class FakeEncoder:
    """测试编码器不会加载真实模型或访问网络。"""

    identity = EncoderIdentity("fake", "test-model", "v1", 3)

    def __init__(self) -> None:
        self.encode_calls = 0

    def encode(self, _image: Image.Image) -> np.ndarray:
        self.encode_calls += 1
        return normalize_embedding(np.asarray([1.0, 0.0, 0.0], dtype=np.float32))


def png_bytes(color: str = "red") -> bytes:
    """构造真实图片上传内容，避免绕过 Pillow 校验。"""
    output = BytesIO()
    Image.new("RGB", (12, 8), color).save(output, format="PNG")
    return output.getvalue()


def random_sha256() -> str:
    """让每个测试记录使用独立精确哈希，绝不触及既有用户数据。"""
    return uuid.uuid4().hex + uuid.uuid4().hex


@pytest.fixture(scope="session")
def database_settings() -> Settings:
    """复用本机数据库配置，仅幂等创建 schema 而不清理任何记录。"""
    settings = Settings.load()
    create_database_and_schema(settings)
    return settings


@pytest.fixture(scope="session")
def database_engine(database_settings: Settings):
    """提供测试专用连接来源，并在整个测试模块结束后释放连接池。"""
    factory = create_session_factory(database_settings)
    engine = factory.kw["bind"]
    try:
        yield engine
    finally:
        dispose_session_factory(factory)


@pytest.fixture
def api_session_factory(database_engine):
    """每个测试以外层事务隔离 API 写入，结束时只回滚自己的数据。"""
    connection = database_engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, class_=Session, expire_on_commit=False)
    try:
        yield factory
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def api_settings(database_settings: Settings, tmp_path: Path) -> Settings:
    """图库落在临时目录，数据库凭据保留在只读配置对象中。"""
    return replace(
        database_settings,
        project_root=tmp_path,
        image_encoder="fake",
        clip_model_name="test-model",
        clip_pretrained="v1",
    )


@pytest.fixture
def fake_encoder() -> FakeEncoder:
    """每个测试获得独立调用计数，避免跨测试污染断言。"""
    return FakeEncoder()


@pytest.fixture
def client(api_settings: Settings, api_session_factory, fake_encoder: FakeEncoder):
    """通过真实 FastAPI 路由测试，请求会话由测试事务包裹。"""
    app = create_app(settings=api_settings, encoder=fake_encoder, session_factory=api_session_factory)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def repository(api_session_factory) -> ImageRepository:
    """为 API 测试预置同一事务中可见的图片和向量。"""
    return ImageRepository(api_session_factory())


def add_image(repository: ImageRepository, settings: Settings, *, name: str = "angle.png") -> tuple[int, bytes]:
    """写入一条真实元数据、图库文件和当前假模型向量。"""
    content = png_bytes("blue")
    sha256 = random_sha256()
    target = settings.image_dir / f"{sha256}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    image = repository.add_image(
        original_name=name,
        stored_path=f"data/images/{target.name}",
        sha256=sha256,
        mime_type="image/png",
        width=12,
        height=8,
    )
    repository.upsert_embedding(image, FakeEncoder.identity, normalize_embedding(np.asarray([1.0, 0.0, 0.0], dtype=np.float32)))
    return image.id, content


def test_health_checks_database_without_encoding_an_image(client: TestClient, fake_encoder: FakeEncoder) -> None:
    """若健康检查改为读取编码器身份，会在真实 OpenCLIP 下意外下载或加载模型。"""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert response.json()["model"]["encoder"] == "fake"
    assert fake_encoder.encode_calls == 0


def test_library_lists_images_with_available_model_identities(
    client: TestClient, repository: ImageRepository, api_settings: Settings
) -> None:
    """若遗漏 embedding 查询，前端将无法知道图片可用于哪个模型空间。"""
    image_id, _content = add_image(repository, api_settings, name="library.png")

    response = client.get("/api/library")

    assert response.status_code == 200
    image = next(item for item in response.json()["images"] if item["id"] == image_id)
    assert image["original_name"] == "library.png"
    assert image["image_url"] == f"/api/images/{image_id}"
    assert image["models"] == [{"encoder": "fake", "name": "test-model", "pretrained": "v1", "dimension": 3}]


def test_image_endpoint_reads_only_database_registered_library_file(
    client: TestClient, repository: ImageRepository, api_settings: Settings
) -> None:
    """若按 ID 读取未映射到图库路径，前端无法展示已有候选图片。"""
    image_id, content = add_image(repository, api_settings)

    response = client.get(f"/api/images/{image_id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == content


def test_image_endpoint_returns_404_when_record_or_file_is_missing(client: TestClient) -> None:
    """若丢失记录或文件仍返回成功，客户端会得到不可用的图片地址。"""
    response = client.get("/api/images/999999999")

    assert response.status_code == 404
    assert "图片不存在" in response.json()["detail"]


def test_search_returns_ranked_results_without_persisting_query(
    client: TestClient, repository: ImageRepository, api_settings: Settings
) -> None:
    """若搜索走导入路径，查询上传会污染图库和图片表。"""
    image_id, _content = add_image(repository, api_settings, name="same-carpet-angle.png")
    before = repository.image_count()

    response = client.post(
        "/api/search",
        params={"top_k": 3},
        files={"image": ("query.png", png_bytes("red"), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == {"encoder": "fake", "name": "test-model", "pretrained": "v1", "dimension": 3}
    assert payload["results"] == [
        {
            "rank": 1,
            "image_id": image_id,
            "original_name": "same-carpet-angle.png",
            "image_url": f"/api/images/{image_id}",
            "similarity": 100.0,
        }
    ]
    assert repository.image_count() == before


def test_search_returns_empty_results_with_explanation_when_model_has_no_vectors(client: TestClient) -> None:
    """若无当前模型向量时只返回空数组，调用方无法区分无匹配与未建向量。"""
    response = client.post(
        "/api/search",
        files={"image": ("query.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert "当前模型" in response.json()["message"]


def test_search_rejects_corrupt_uploaded_image_with_400(client: TestClient) -> None:
    """若坏图片进入编码器，错误会变成不透明的服务内部异常。"""
    response = client.post(
        "/api/search",
        files={"image": ("broken.jpg", b"not-an-image", "image/jpeg")},
    )

    assert response.status_code == 400
    assert "图片" in response.json()["detail"]


@pytest.mark.parametrize("top_k", [0, 51])
def test_search_rejects_top_k_outside_safe_range(client: TestClient, top_k: int) -> None:
    """若端点未限制候选数，误用会让数据库执行超出验证范围的扫描。"""
    response = client.post(
        "/api/search",
        params={"top_k": top_k},
        files={"image": ("query.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 422


def test_database_error_returns_503_without_connection_details(api_settings: Settings, fake_encoder: FakeEncoder) -> None:
    """若数据库故障泄漏底层异常，响应可能暴露连接信息或堆栈。"""
    def unavailable_session_factory() -> Session:
        raise SQLAlchemyError("postgresql://user:secret@host/db")

    app = create_app(settings=api_settings, encoder=fake_encoder, session_factory=unavailable_session_factory)
    with TestClient(app) as test_client:
        response = test_client.get("/health")

    assert response.status_code == 503
    assert "服务暂不可用" in response.json()["detail"]
    assert "secret" not in response.text
