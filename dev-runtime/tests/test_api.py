"""FastAPI 接口的端到端行为测试。"""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import uuid
import json
from zipfile import ZipFile

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.api import create_app
from backend.config import Settings
from backend.db import create_database_and_schema, create_session_factory, dispose_session_factory
from backend.encoders.base import EncoderIdentity, normalize_embedding
from backend.models import ImageRecord, MatchHistory
from backend.repository import ImageMetadata, ImageRepository


class FakeEncoder:
    """测试编码器不会加载真实模型或访问网络。"""

    identity = EncoderIdentity("fake", "test-model", "v1", 3)

    def __init__(self) -> None:
        self.encode_calls = 0

    def encode(self, _image: Image.Image) -> np.ndarray:
        self.encode_calls += 1
        return normalize_embedding(np.asarray([1.0, 0.0, 0.0], dtype=np.float32))


class FailingEncoder(FakeEncoder):
    """模拟服务工作单元内部编码失败，验证 API 不泄漏底层异常。"""

    def encode(self, _image: Image.Image) -> np.ndarray:
        raise RuntimeError("internal encoder failure")


@pytest.fixture(autouse=True)
def api_test_identity(request, monkeypatch):
    """本模块验证业务接口，登录验证另由 test_auth.py 覆盖。"""
    from backend import auth
    from backend.models import UserAccount
    user = {'id': 0, 'username': 'api-test', 'display_name': '接口测试', 'role': 'admin'}
    if 'api_session_factory' in request.fixturenames:
        factory = request.getfixturevalue('api_session_factory')
        with factory() as session:
            record = UserAccount(username='test_' + uuid.uuid4().hex, display_name='接口测试',
                                 password_hash='unused-in-business-tests', role='admin')
            session.add(record)
            session.flush()
            user['id'] = record.id
            session.commit()
    monkeypatch.setattr(auth, 'resolve_user', lambda *_args: user)


def test_match_history_snapshot(client, monkeypatch, api_settings, api_session_factory, fake_encoder, frontend_root):
    from backend.scene import SceneClient
    from backend.repository import ProductSearchRow

    tags = dict(room="客厅", sofa_status="present", sofa_color="米色",
                floor_status="present", floor_color="浅灰色", floor_material="瓷砖/石材")
    monkeypatch.setattr(SceneClient, "identify", lambda self, image: tags)
    monkeypatch.setattr(ImageRepository, "search_products", lambda *args, **kwargs: [
        ProductSearchRow("history-product", 1, 2, "J", 92.5, tags, "云纹米色")
    ])
    response = client.post("/api/search", files={"image": ("private-customer.png", png_bytes(), "image/png")})
    assert response.status_code == 200
    listing = client.get("/api/history").json()
    record = listing["items"][0]
    assert record["result_count"] == 1
    assert record["query_scene"] == tags
    detail = client.get(f'/api/history/{record["id"]}')
    assert detail.json()["payload"] == response.json()
    assert detail.json()["payload"]["results"][0]["style"] == "云纹米色"
    assert "private-customer" not in detail.text
    assert not list(api_settings.image_dir.glob("*"))
    image_url = detail.json()["query_image_url"]
    assert record["query_image_url"] == image_url
    # 新应用实例读取同一数据库，验证照片不依赖请求内存或客户端预览。
    with TestClient(create_app(settings=api_settings, encoder=fake_encoder,
                              session_factory=api_session_factory, frontend_root=frontend_root), client=("127.0.0.1", 50000)) as reopened:
        photo = reopened.get(image_url)
        assert photo.status_code == 200
        assert photo.headers["content-type"] == "image/png"
        assert photo.content == png_bytes()
        assert reopened.get(f'/api/history/{record["id"]}').json() == detail.json()

    monkeypatch.setattr(SceneClient, "identify", lambda self, image: {**tags, "sofa_status": "unknown"})
    empty = client.post("/api/search", files={"image": ("private.png", png_bytes(), "image/png")})
    assert empty.status_code == 200
    newest = client.get("/api/history").json()["items"][0]
    assert newest["id"] > record["id"]
    assert newest["result_count"] == 0
    assert client.get(newest["query_image_url"]).content == png_bytes()
    assert client.get(f'/api/history?before={newest["id"]}').json()["items"][0]["id"] == record["id"]
    assert client.get("/api/history/0").status_code == 404
    from backend.models import MatchHistory
    with api_session_factory() as session:
        old = MatchHistory(payload_json=response.text)
        session.add(old)
        session.commit()
        old_id = old.id
    assert client.get(f'/api/history/{old_id}').json()["query_image_url"] is None
    assert client.get(f'/api/history/{old_id}/image').status_code == 404


def test_single_import_labels_and_search_without_product(client, monkeypatch, api_session_factory):
    from backend.scene import SceneClient
    from backend.ranking import PROMPT
    def ranking_request(self, prompt, images, **kwargs):
        import json
        return {'items': [dict(image_id=item['image_id'], view_distance='far', rug_area='small', query_tone='warm', candidate_tone='warm', query_evidence='暖光', candidate_evidence='暖光', tone_match='same', tone_reason='整体暖色一致') for item in json.loads(prompt[len(PROMPT):])]}
    monkeypatch.setattr(SceneClient, '_request', ranking_request)
    from backend.scene import SceneClient, SceneError
    from backend.models import ProductImage
    from sqlalchemy import select

    tags = dict(room="客厅", sofa_status="present", sofa_color="米色",
                floor_status="present", floor_color="浅灰色", floor_material="瓷砖/石材")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-placeholder")
    calls = []
    def identify(self, image):
        calls.append(image.size)
        return tags
    monkeypatch.setattr(SceneClient, "identify", identify)
    ids = []
    for color in ("#234567", "#345678"):
        uploaded = client.post('/api/library', files={'image': ('single.png', png_bytes(color), 'image/png')})
        assert uploaded.status_code == 200
        assert uploaded.json()['scene_labels'] == tags
        ids.append(uploaded.json()['image']['id'])
    assert len(calls) == 2
    duplicate = client.post('/api/library', files={'image': ('single.png', png_bytes('#234567'), 'image/png')})
    assert duplicate.json()['status'] == 'duplicate'
    assert len(calls) == 2  # 复用已有标签，不重复调用视觉模型。
    with api_session_factory() as session:
        assert not list(session.scalars(select(ProductImage).where(ProductImage.image_id.in_(ids))))
    matches = client.post('/api/search?top_k=10', files={'image': ('query.png', png_bytes(), 'image/png')})
    assert matches.status_code == 200
    rows = {item['matched_buyer_image_url']: item for item in matches.json()['results']}
    for image_id in ids:
        row = rows[f'/api/images/{image_id}']
        assert row['product_id'] is None
        assert row['product_image_url'] is None
        assert row['product_download_url'] is None
        assert row['scene_labels'] == tags
        assert row['ranking_score'] <= row['similarity'] - 4
        assert len(row['ranking_reasons']) == 3

    def unavailable(self, image):
        raise SceneError('test unavailable')
    monkeypatch.setattr(SceneClient, 'identify', unavailable)
    failed_label = client.post('/api/library', files={'image': ('single.png', png_bytes('#456789'), 'image/png')})
    assert failed_label.status_code == 200
    assert failed_label.json()['scene_labels'] is None
    assert '未生成' in failed_label.json()['message']
    monkeypatch.setattr(SceneClient, 'identify', identify)
    retry = client.post('/api/library', files={'image': ('single.png', png_bytes('#456789'), 'image/png')})
    assert retry.json()['scene_labels'] == tags


def test_strict_search_requires_labels_and_accepts_confirmation(client, monkeypatch):
    from backend.scene import SceneClient, SceneError
    calls = []
    def unavailable(self, image):
        raise SceneError('unavailable')
    monkeypatch.setattr(SceneClient, 'identify', unavailable)
    monkeypatch.setattr(ImageRepository, 'search_products', lambda *args, **kwargs: calls.append(kwargs) or [])
    files = {'image': ('query.png', png_bytes(), 'image/png')}
    automatic = client.post('/api/search', files=files)
    assert automatic.status_code == 200
    assert automatic.json()['results'] == []
    assert not calls
    tags = dict(room='客厅', sofa_status='present', sofa_color='米色',
                floor_status='present', floor_color='米色', floor_material='瓷砖/石材')
    confirmed = client.post('/api/search', files=files, data={'confirmed_scene': json.dumps(tags)})
    assert confirmed.status_code == 200
    assert confirmed.json()['query_scene'] == tags
    assert calls[0]['scene_labels'] == tags
    invalid = client.post('/api/search', files=files, data={'confirmed_scene': '{}'})
    assert invalid.status_code == 400


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
    factory = sessionmaker(bind=connection, class_=Session, expire_on_commit=False,
                           join_transaction_mode="create_savepoint")
    try:
        yield factory
    finally:
        if transaction.is_active:
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
def frontend_root(tmp_path: Path) -> Path:
    """复制真实首页并隔离其余静态资源，验证入口契约和白名单路由。"""
    root = tmp_path / "frontend"
    root.mkdir()
    (root / "index.html").write_text(
        (Path(__file__).parents[1] / "index.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "styles.css").write_text("body { color: black; }", encoding="utf-8")
    (root / "matcher-core.js").write_text("export const matcher = {};", encoding="utf-8")
    (root / "api-client.js").write_text("export const api = {};", encoding="utf-8")
    (root / "app.js").write_text("export const app = {};", encoding="utf-8")
    for name in ("feedback.html", "feedback.js", "feedback.css", "admin.js", "login.html", "login.js", "auth-client.js", "orders.js"):
        (root / name).write_text((Path(__file__).parents[1] / name).read_text(encoding="utf-8"), encoding="utf-8")
    (root / "not-registered.env").write_text("SECRET=not-served", encoding="utf-8")
    return root


@pytest.fixture
def client(
    api_settings: Settings,
    api_session_factory,
    fake_encoder: FakeEncoder,
    frontend_root: Path,
):
    """通过真实 FastAPI 路由测试，请求会话由测试事务包裹。"""
    app = create_app(
        settings=api_settings,
        encoder=fake_encoder,
        session_factory=api_session_factory,
        frontend_root=frontend_root,
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
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


def all_metadata() -> ImageMetadata:
    """返回九个字段均有值的固定元数据，用于检查 HTTP 映射不漂移。"""
    return ImageMetadata(
        sku="RUG-001",
        product_name="云朵地毯",
        size="160×230cm",
        price=899,
        room="客厅",
        style="奶油风",
        color="米白",
        stock="现货",
        selling_point="柔软亲肤",
    )


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
    record = repository.find_by_id(image_id)
    assert record is not None
    repository.update_metadata(record, all_metadata())

    response = client.get("/api/library")

    assert response.status_code == 200
    image = next(item for item in response.json()["images"] if item["id"] == image_id)
    assert image["original_name"] == "library.png"
    assert image["image_url"] == f"/api/images/{image_id}"
    assert image["created_at"]
    assert image["history_reference_count"] == 0
    assert image["models"] == [{"encoder": "fake", "name": "test-model", "pretrained": "v1", "dimension": 3}]
    assert {key: image[key] for key in all_metadata().__dict__} == {
        "sku": "RUG-001",
        "product_name": "云朵地毯",
        "size": "160×230cm",
        "price": 899.0,
        "room": "客厅",
        "style": "奶油风",
        "color": "米白",
        "stock": "现货",
        "selling_point": "柔软亲肤",
    }


def test_library_reports_history_references_and_preserves_snapshot_on_delete(
    client: TestClient, repository: ImageRepository, api_settings: Settings, api_session_factory
) -> None:
    image_id, _content = add_image(repository, api_settings, name="referenced.png")
    with api_session_factory() as session:
        session.add(MatchHistory(payload_json=json.dumps({"results": [
            {"rank": 1, "buyer_image_id": image_id, "product_name": "历史商品"},
            {"rank": 2, "buyer_image_id": image_id},
        ]})))
        session.commit()

    listed = client.get("/api/library")
    image = next(item for item in listed.json()["images"] if item["id"] == image_id)
    assert image["history_reference_count"] == 1

    deleted = client.delete(f"/api/library/{image_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "image_id": image_id}
    with api_session_factory() as session:
        assert session.get(ImageRecord, image_id) is None
        snapshot = session.scalar(select(MatchHistory).order_by(MatchHistory.id.desc()))
        assert json.loads(snapshot.payload_json)["results"][0]["product_name"] == "历史商品"


def test_library_upload_persists_image_vector_and_optional_metadata(
    client: TestClient,
    repository: ImageRepository,
) -> None:
    """若上传未复用入库服务，图片、向量或商品资料会缺失。"""
    initial_images = repository.image_count()
    initial_embeddings = repository.embedding_count()
    response = client.post(
        "/api/library",
        files={"image": ("buyer.png", png_bytes(), "image/png")},
        data={"product_name": " 云朵地毯 ", "price": "899.00", "room": "客厅"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "imported"
    assert response.json()["image"]["product_name"] == "云朵地毯"
    assert response.json()["image"]["price"] == 899.0
    assert repository.image_count() == initial_images + 1
    assert repository.embedding_count() == initial_embeddings + 1


def test_library_duplicate_upload_preserves_and_supplements_metadata(
    client: TestClient,
    repository: ImageRepository,
) -> None:
    """若重复上传覆盖空字段，渐进补充资料会破坏已有商品信息。"""
    content = png_bytes()
    first = client.post(
        "/api/library",
        files={"image": ("buyer.png", content, "image/png")},
        data={"product_name": "云朵地毯", "price": "899.00"},
    )

    second = client.post(
        "/api/library",
        files={"image": ("duplicate.png", content, "image/png")},
        data={"style": "奶油风", "product_name": "  "},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["image"]["product_name"] == "云朵地毯"
    assert second.json()["image"]["price"] == 899.0
    assert second.json()["image"]["style"] == "奶油风"
    assert repository.image_count() == 1
    assert repository.embedding_count() == 1


def test_library_upload_maps_service_failure_to_503(
    api_settings: Settings,
    api_session_factory,
    frontend_root: Path,
) -> None:
    """若服务 FAILED 被当作成功，客户端会收到不存在的图片结果。"""
    app = create_app(
        settings=api_settings,
        encoder=FailingEncoder(),
        session_factory=api_session_factory,
        frontend_root=frontend_root,
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        response = test_client.post(
            "/api/library",
            files={"image": ("buyer.png", png_bytes(), "image/png")},
        )

    assert response.status_code == 503
    assert "internal encoder failure" not in response.text


def test_image_endpoint_reads_only_database_registered_library_file(
    client: TestClient, repository: ImageRepository, api_settings: Settings
) -> None:
    """若按 ID 读取未映射到图库路径，前端无法展示已有候选图片。"""
    image_id, content = add_image(repository, api_settings)

    response = client.get(f"/api/images/{image_id}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == content

    preview = client.get(f"/api/images/{image_id}?preview=1")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/jpeg"
    with Image.open(BytesIO(preview.content)) as rendered:
        assert max(rendered.size) <= 1200
    original = client.get(f"/api/images/{image_id}?preview=1&download=1")
    assert original.content == content
    assert "attachment" in original.headers["content-disposition"]


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
    record = repository.find_by_id(image_id)
    assert record is not None
    repository.update_metadata(record, all_metadata())
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
            "sku": "RUG-001",
            "product_name": "云朵地毯",
            "size": "160×230cm",
            "price": 899.0,
            "room": "客厅",
            "style": "奶油风",
            "color": "米白",
            "stock": "现货",
            "selling_point": "柔软亲肤",
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


@pytest.mark.parametrize(
    ("files", "data"),
    [
        ({"image": ("oversized.png", b"x" * (20 * 1024 * 1024 + 1), "image/png")}, {}),
        ({"image": ("broken.png", b"not-an-image", "image/png")}, {}),
        ({"image": ("buyer.png", png_bytes(), "image/png")}, {"price": "-0.01"}),
    ],
    ids=["oversized", "corrupt", "negative-price"],
)
def test_library_upload_rejects_invalid_input_without_internal_details(
    client: TestClient,
    files: dict[str, tuple[str, bytes, str]],
    data: dict[str, str],
) -> None:
    """若上传校验未在事务前收口，非法输入可能变成内部服务异常。"""
    response = client.post("/api/library", files=files, data=data)

    assert response.status_code == 400
    assert "Traceback" not in response.text
    assert "InvalidImageError" not in response.text


def test_library_upload_rejects_price_above_database_precision(client: TestClient) -> None:
    """超过 NUMERIC(12,2) 上限的价格必须在 API 边界返回 400。"""
    response = client.post(
        "/api/library",
        files={"image": ("buyer.png", png_bytes(), "image/png")},
        data={"price": "10000000000.00"},
    )

    assert response.status_code == 400
    assert "服务暂不可用" not in response.text


def test_root_serves_frontend_and_only_registered_assets(client: TestClient) -> None:
    """若挂载整个目录，未注册配置文件可能被同源静态路由暴露。"""
    assert client.get("/").status_code == 200
    html = client.get("/").text
    assert '<script src="api-client.js"></script>' in html
    assert 'id="seedButton"' not in html
    assert 'id="clearButton"' not in html
    assert 'id="entryStatus"' not in html
    assert 'id="reloadLibraryButton"' not in html
    assert 'id="historyList"' not in html
    assert 'id="matchButton"' in html
    admin = client.get('/admin')
    assert admin.status_code == 200
    assert 'id="entryStatus"' in admin.text
    assert 'id="reloadLibraryButton"' in admin.text
    assert 'id="historyList"' in admin.text
    assert 'id="feedbackList"' in admin.text
    assert 'id="matchButton"' not in admin.text
    assert client.get('/feedback').text == admin.text
    assert client.get('/admin.js').status_code == 200
    assert client.get("/styles.css").headers["content-type"].startswith("text/css")
    assert client.get("/matcher-core.js").status_code == 200
    assert client.get("/api-client.js").status_code == 200
    assert client.get("/app.js").status_code == 200
    assert client.get("/not-registered.env").status_code == 404


def test_default_frontend_root_is_independent_from_library_project_root(
    api_settings: Settings,
    api_session_factory,
    fake_encoder: FakeEncoder,
) -> None:
    """若默认静态根跟随临时图库根，正常部署的首页会错误返回缺失。"""
    app = create_app(settings=api_settings, encoder=fake_encoder, session_factory=api_session_factory)

    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        response = test_client.get("/")

    assert response.status_code == 200


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
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        response = test_client.get("/health")

    assert response.status_code == 503
    assert "服务暂不可用" in response.json()["detail"]
    assert "secret" not in response.text


@pytest.fixture
def import_client(tmp_path, monkeypatch):
    """导入接口使用内存事务仓库，后台任务在测试请求返回前执行完成。"""
    import backend.api as api_module
    from tests.test_excel_import import MemoryRepository, MemorySession, ImportEncoder, import_settings

    session = MemorySession()
    settings = import_settings(tmp_path)
    monkeypatch.setattr(api_module, "ImageRepository", MemoryRepository)

    def runner(job_id, workbook_path):
        from backend.excel_import import ExcelImportService

        ExcelImportService(settings, ImportEncoder(), lambda: session,
                           repository_factory=MemoryRepository).run(job_id, workbook_path)

    app = create_app(settings=settings, encoder=ImportEncoder(), session_factory=lambda: session,
                     import_runner=runner)
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client, settings, session


def small_import_workbook():
    """最小真实 XLSX 包经过正式解析器，避免只验证假启动器。"""
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("xl/workbook.xml", '<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="地毯图片" r:id="s1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="s1" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheetData><row><c r="F2" t="inlineStr"><is><t>00123</t></is></c></row></sheetData><drawing r:id="d1"/></worksheet>')
        archive.writestr("xl/worksheets/_rels/sheet1.xml.rels", '<Relationships><Relationship Id="d1" Target="../drawings/drawing1.xml"/></Relationships>')
        archive.writestr("xl/drawings/drawing1.xml", '<drawing xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><oneCellAnchor><from><col>11</col><row>1</row></from><pic><blip r:embed="i1"/></pic></oneCellAnchor></drawing>')
        archive.writestr("xl/drawings/_rels/drawing1.xml.rels", '<Relationships><Relationship Id="i1" Target="../media/image1.png"/></Relationships>')
        archive.writestr("xl/media/image1.png", png_bytes())
    return output.getvalue()


def test_import_upload_queries_completed_job_and_removes_temporary_directory(import_client, monkeypatch):
    """上传应返回不含路径的任务 ID，查询应读取后台提交的真实导入结果。"""
    client, settings, session = import_client
    from starlette.datastructures import UploadFile

    reads = []
    original_read = UploadFile.read

    async def chunked_read(upload, size=-1):
        reads.append(size)
        return await original_read(upload, size)

    monkeypatch.setattr(UploadFile, "read", chunked_read)
    response = client.post("/api/imports", files={"workbook": ("商品.xlsx", small_import_workbook())})
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"job_id", "status"}
    assert payload["status"] == "parsing"
    assert len(payload["job_id"]) == 32 and int(payload["job_id"], 16) >= 0
    status = client.get(f"/api/imports/{payload['job_id']}")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["processed"] == status.json()["total"] == 1
    assert status.json()["summary"]["encoded"] == 1
    assert status.json()["error"] is None
    assert not (settings.import_job_dir / payload["job_id"]).exists()
    assert len(session.state["images"]) == 1
    assert reads and all(size == 1024 * 1024 for size in reads)


def test_import_rejects_non_xlsx_and_returns_404_for_unknown_job(import_client):
    client, settings, session = import_client
    response = client.post("/api/imports", files={"workbook": ("商品.xls", b"wrong")})
    assert response.status_code == 400
    assert not session.state["jobs"]
    assert client.get("/api/imports/" + "0" * 32).status_code == 404


def test_import_workbook_error_is_public_and_temporary_files_are_removed(import_client):
    client, settings, _ = import_client
    response = client.post("/api/imports", files={"workbook": ("broken.xlsx", b"broken")})
    job_id = response.json()["job_id"]
    status = client.get(f"/api/imports/{job_id}").json()
    assert status["status"] == "failed" and status["error"]
    assert str(settings.project_root) not in json.dumps(status)
    assert not (settings.import_job_dir / job_id).exists()


def test_import_upload_database_failure_cleans_files_without_exposing_error(import_client, monkeypatch):
    """任务首次入库失败时，上传目录必须清理且错误不得回显连接信息。"""
    client, settings, session = import_client

    def fail_commit():
        raise SQLAlchemyError("postgresql://user:secret@host/db")

    monkeypatch.setattr(session, "commit", fail_commit)
    response = client.post("/api/imports", files={"workbook": ("商品.xlsx", small_import_workbook())})
    assert response.status_code == 503
    assert "secret" not in response.text
    assert not list(settings.import_job_dir.iterdir())
    assert not session.state["jobs"]


def test_feedback_submission_and_admin_history(client, monkeypatch, api_settings, api_session_factory, fake_encoder, frontend_root):
    from backend.scene import SceneClient
    from backend.repository import ProductSearchRow
    from backend.models import MatchFeedback

    tags = dict(room="客厅", sofa_status="present", sofa_color="米色",
                floor_status="present", floor_color="浅灰色", floor_material="瓷砖/石材")
    monkeypatch.setattr(SceneClient, "identify", lambda self, image: tags)
    monkeypatch.setattr(ImageRepository, "search_products", lambda *args, **kwargs: [
        ProductSearchRow("feedback-product", 1, 2, "L", 92.5, tags)
    ])
    response = client.post('/api/search', files={'image': ('customer.png', png_bytes(), 'image/png')})
    assert response.status_code == 200
    payload = response.json()
    history_id = payload['history_id']
    assert history_id
    assert client.get(f'/api/history/{history_id}').json()['payload'] == payload
    body = {'history_id': history_id, 'helpful': False, 'reason': '  沙发颜色不一致  '}
    assert client.post('/api/feedback', json={**body, 'reason': '  '}).status_code == 422
    assert client.post('/api/feedback', json={**body, 'history_id': 9223372036854775807}).status_code == 404
    saved = client.post('/api/feedback', json=body)
    assert saved.status_code == 201
    feedback_id = saved.json()['id']
    with api_session_factory() as session:
        row = session.get(MatchFeedback, feedback_id)
        assert row.history_id == history_id
        assert row.helpful is False
        assert row.reason == '沙发颜色不一致'
    assert client.post('/api/feedback', json={'history_id': history_id, 'helpful': True}).status_code == 201
    with TestClient(create_app(settings=api_settings, encoder=fake_encoder,
                              session_factory=api_session_factory, frontend_root=frontend_root), client=("127.0.0.1", 50000)) as reopened:
        items = reopened.get('/api/feedback?helpful=false').json()['items']
        assert all(item['helpful'] is False for item in items)
        feedback = next(item for item in items if item['id'] == feedback_id)
        assert feedback['reason'] == '沙发颜色不一致'
        detail = reopened.get(f'/api/history/{feedback["history_id"]}').json()
        assert detail['payload'] == payload
        assert reopened.get(detail['query_image_url']).content == png_bytes()
        assert reopened.get('/feedback').status_code == 200
        assert 'feedbackList' in reopened.get('/feedback').text
        assert reopened.get('/feedback.js').status_code == 200
        assert reopened.get('/feedback.css').status_code == 200
    # 管理列表游标翻页不会漏掉同一次匹配的多份反馈。
    with api_session_factory() as session:
        session.add_all([MatchFeedback(history_id=history_id, helpful=False, reason=f'原因 {i}') for i in range(21)])
        session.commit()
    first = client.get('/api/feedback?helpful=false').json()
    assert len(first['items']) == 20
    second = client.get(f'/api/feedback?helpful=false&before={first["next_before"]}').json()
    assert first['next_before']
    assert set(item['id'] for item in first['items']).isdisjoint(item['id'] for item in second['items'])
    assert feedback_id in [item['id'] for item in second['items']]


def test_search_returns_optional_style(client, monkeypatch):
    from backend.scene import SceneClient
    tags = dict(room='客厅', sofa_status='present', sofa_color='米色',
                floor_status='present', floor_color='浅灰色', floor_material='瓷砖/石材')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-placeholder')
    monkeypatch.setattr(SceneClient, 'identify', lambda self, image: tags)
    expected = {}
    for color, style in [('#913245', '  云纹米色  '), ('#284563', '')]:
        uploaded = client.post('/api/library', data={'style': style},
                               files={'image': ('style.png', png_bytes(color), 'image/png')})
        assert uploaded.status_code == 200
        expected[uploaded.json()['image']['id']] = style.strip() or None
    response = client.post('/api/search?top_k=50', files={'image': ('query.png', png_bytes(), 'image/png')})
    assert response.status_code == 200
    payload = response.json()
    rows = {row['buyer_image_id']: row for row in payload['results']}
    for image_id, style in expected.items():
        assert rows[image_id]['style'] == style
    # 快照持久化由 test_match_history_snapshot 使用非嵌套会话验证；
    # 本测试的共享连接会在真实检索会话关闭时回滚内部保存点。


def test_history_time_filter(client, api_session_factory, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from backend import api
    from backend.models import MatchHistory
    today = datetime(2099, 6, 15, tzinfo=timezone(timedelta(hours=8)))
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (today + timedelta(hours=12)).astimezone(tz)
    monkeypatch.setattr(api, 'datetime', Clock)
    with api_session_factory() as session:
        records = [MatchHistory(payload_json='{"results":[]}', created_at=today-timedelta(days=days)) for days in (0, 2, 6, 29, 30)]
        session.add_all(records)
        session.flush()
        ids = [row.id for row in records]
        session.commit()
    for period, expected in [('today', ids[:1]), ('3d', ids[:2]), ('7d', ids[:3]), ('30d', ids[:4])]:
        response = client.get('/api/history', params={'period': period})
        assert response.status_code == 200
        assert {row['id'] for row in response.json()['items']} == set(expected)
    page = client.get('/api/history', params={'period': '7d', 'before': ids[2]}).json()
    assert {row['id'] for row in page['items']} == set(ids[:2])
    assert client.get('/api/history?period=invalid').status_code == 422


def test_history_customer_filter(client, api_session_factory):
    from backend.models import UserAccount, MatchHistory
    from uuid import uuid4
    from datetime import datetime, timezone
    with api_session_factory() as session:
        users = [UserAccount(username=uuid4().hex, display_name='筛选测试', password_hash='unused', role='customer_service') for _ in range(2)]
        session.add_all(users)
        session.flush()
        records = [MatchHistory(user_id=user.id, payload_json='{"results":[]}', created_at=datetime.now(timezone.utc)) for user in (users[0], users[1], users[0])]
        session.add_all(records)
        session.flush()
        customer_id = users[0].id
        ids = [row.id for row in records]
        session.commit()
    params = {'customer_id': customer_id, 'period': 'today'}
    response = client.get('/api/history', params=params)
    assert response.status_code == 200
    assert [row['id'] for row in response.json()['items']] == [ids[2], ids[0]]
    params['before'] = ids[2]
    assert [row['id'] for row in client.get('/api/history', params=params).json()['items']] == [ids[0]]
    assert client.get('/api/history?customer_id=0').status_code == 422


def test_search_never_reconsiders_scene_rejections(client, monkeypatch, api_session_factory):
    from backend.scene import SceneClient
    from backend.models import SceneLabel
    from backend.repository import ImageRepository
    import json
    tags = dict(room='客厅', sofa_status='present', sofa_color='米色', floor_status='present', floor_color='浅灰色', floor_material='瓷砖/石材')
    monkeypatch.setattr(SceneClient, 'identify', lambda *args: tags)
    monkeypatch.setattr(SceneClient, '_request', lambda *a, **k: dict(view_distance='normal', rug_area='normal'))
    def forbidden(*args, **kwargs):
        raise AssertionError('冲突复审不应再被调用')
    monkeypatch.setattr(SceneClient, 'compare_scenes', forbidden)
    original = ImageRepository.search_products
    def filtered_only(self, *args, **kwargs):
        assert kwargs.get('filter_scene', True) is True
        return original(self, *args, **kwargs)
    monkeypatch.setattr(ImageRepository, 'search_products', filtered_only)
    upload = client.post('/api/library', files={'image': ('same.png', png_bytes('red'), 'image/png')})
    assert upload.status_code == 200
    image_id = upload.json()['image']['id']
    with api_session_factory() as session:
        label = session.get(SceneLabel, image_id)
        label.labels_json = json.dumps({**tags, 'floor_material': '木纹'})
        session.commit()
    response = client.post('/api/search', files={'image': ('same.png', png_bytes('red'), 'image/png')})
    assert response.status_code == 200
    assert response.json()['results'] == []
    assert '复核' not in response.json()['message']
