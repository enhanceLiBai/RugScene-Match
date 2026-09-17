import pytest
from types import SimpleNamespace
from PIL import Image
from backend.folder_import import parse_folder, validate_audit, main
from backend.folder_screen import rejected_destination, validate_decision

def test_folder_identity():
    assert parse_folder('123_款式_暖色') == ('123', '款式_暖色')
    assert parse_folder('未知商品ID_米白') == (None, '米白')

def test_audit_requires_valid_labels_and_boolean():
    assert validate_audit(dict(approved=False,rejection_reasons=['有人'],labels=None))['approved'] is False
    with pytest.raises(ValueError):
        validate_audit(dict(approved='true',rejection_reasons=[],labels={}))
    with pytest.raises(ValueError):
        validate_audit(dict(approved=True,rejection_reasons=[],labels={}))

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
