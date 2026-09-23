import pytest
from types import SimpleNamespace
from PIL import Image
from backend.folder_import import import_labeled, parse_folder, validate_labels, main
from backend.folder_screen import rejected_destination, validate_decision

def test_folder_identity():
    assert parse_folder('123_款式_暖色') == ('123', '款式_暖色')
    assert parse_folder('未知商品ID_米白') == (None, '米白')


def test_import_client_reads_system_environment(tmp_path, monkeypatch):
    from backend.folder_import import create_import_client

    monkeypatch.setenv('deepseek-api-key', 'system-key')
    client = create_import_client(tmp_path)
    assert client.key == 'system-key'


def test_import_writes_folder_identity_to_product_fields(tmp_path, monkeypatch):
    from backend import folder_import

    record = SimpleNamespace(id=7, style=None, embeddings=[SimpleNamespace(
        encoder='clip', model_name='model', pretrained='weights', dimension=2
    )])
    repository = SimpleNamespace(
        find_by_sha256=lambda _sha: record,
        update_metadata=lambda image, metadata: (
            setattr(image, 'product_name', metadata.product_name),
            setattr(image, 'style', metadata.style),
        ),
        link_product_image=lambda product_id, image, role, column: setattr(
            image, 'product_link', (product_id, role, column)
        ),
        upsert_embedding=lambda *_args: None,
    )

    class Session:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def get(self, *_args): return SimpleNamespace()
        def commit(self): pass

    monkeypatch.setattr(folder_import, 'validate_image_bytes', lambda *_args: SimpleNamespace(
        sha256='a' * 64, image=object()
    ))
    monkeypatch.setattr(folder_import, 'ImageRepository', lambda _session: repository)
    monkeypatch.setattr(folder_import, '_write_label_columns', lambda *_args: None)

    encoder = SimpleNamespace(identity=SimpleNamespace(
        encoder='clip', model_name='model', pretrained='weights', dimension=2
    ))
    client = SimpleNamespace(model='vision')
    settings = SimpleNamespace(image_dir=tmp_path, project_root=tmp_path)

    assert import_labeled(
        settings, Session, encoder, client, b'image', 'photo.jpg',
        '123456', '埃里森庄园', {}
    ) == 7
    assert record.product_name == '埃里森庄园'
    assert record.style is None
    assert record.product_link == ('123456', 'buyer_sofa', 'L')

def test_label_normalizes_non_present_attributes():
    labels = dict(room='客厅',sofa_status='not_present',sofa_color='黑色',sofa_color_group='黑色系',sofa_material='皮质',floor_status='unknown',floor_color='棕色',floor_color_group='棕色系',floor_material='木纹',wall_status='unknown',wall_color='白色',wall_color_group='白色系',wall_material='乳胶漆',image_tone='中性')
    assert validate_labels(labels)['sofa_color'] == '无法判断'
    assert labels['floor_material'] == '无法判断'


def test_label_requires_complete_valid_shape():
    with pytest.raises(ValueError):
        validate_labels(dict(room='客厅'))

def test_scan_does_not_call_model_or_write_report(tmp_path):
    folder=tmp_path/'123_款式'; folder.mkdir(); (folder/'a.jpg').write_bytes(b'not-read-in-scan')
    report=tmp_path/'report.jsonl'
    assert main([str(tmp_path),'--report',str(report)])==0
    assert not report.exists()


def test_screen_decision_is_strict_boolean_only():
    assert validate_decision({"qualified": True}) is True
    with pytest.raises(ValueError):
        validate_decision({"qualified": True, "reason": "extra"})


def test_rejected_destination_preserves_product_style_directory(tmp_path):
    source = tmp_path / "source"
    image = source / "123_款式" / "photo.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"photo")
    target = rejected_destination(image, source, tmp_path / "source_淘汰")
    assert target == tmp_path / "source_淘汰" / "123_款式" / "photo.jpg"


def test_screen_moves_rejected_image_and_writes_resumable_checkpoint(tmp_path, monkeypatch):
    from backend import folder_screen

    source = tmp_path / "source"
    image_path = source / "123_款式" / "photo.jpg"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (12, 12)).save(image_path)

    class RejectingClient:
        key = "configured"

        def __init__(self, _root):
            pass

        def _request(self, *_args, **_kwargs):
            return {"qualified": False}

    monkeypatch.setattr(folder_screen, "SceneClient", RejectingClient)
    monkeypatch.setattr(folder_screen.Settings, "load", lambda: SimpleNamespace(project_root=tmp_path))
    report = tmp_path / "report.jsonl"
    checkpoint = tmp_path / "checkpoint.json"

    assert folder_screen.main([str(source), "--execute", "--report", str(report), "--checkpoint", str(checkpoint)]) == 0
    assert not image_path.exists()
    assert (tmp_path / "source_淘汰" / "123_款式" / "photo.jpg").is_file()
    assert '"status": "rejected"' in report.read_text(encoding="utf-8")
    assert '"state": "completed"' in checkpoint.read_text(encoding="utf-8")


def test_screen_stops_on_quota_and_keeps_current_image(tmp_path, monkeypatch):
    from backend import folder_screen
    from backend.scene import SceneQuotaError

    source = tmp_path / "source"
    image_path = source / "123_款式" / "photo.jpg"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (12, 12)).save(image_path)

    class EmptyClient:
        key = "configured"

        def __init__(self, _root):
            pass

        def _request(self, *_args, **_kwargs):
            raise SceneQuotaError("quota")

    monkeypatch.setattr(folder_screen, "SceneClient", EmptyClient)
    monkeypatch.setattr(folder_screen.Settings, "load", lambda: SimpleNamespace(project_root=tmp_path))
    checkpoint = tmp_path / "checkpoint.json"

    assert folder_screen.main([str(source), "--execute", "--checkpoint", str(checkpoint), "--report", str(tmp_path / "report.jsonl")]) == 2
    assert image_path.is_file()
    assert '"state": "stopped_quota"' in checkpoint.read_text(encoding="utf-8")
