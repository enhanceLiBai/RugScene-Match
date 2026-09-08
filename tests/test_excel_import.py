"""使用可回滚的内存仓库验证 Excel 导入业务，不连接数据库或真实模型。"""

from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from sqlalchemy.exc import SQLAlchemyError

from backend.config import Settings
from backend.encoders.base import EncoderIdentity
from backend.tencent_excel import WorkbookImage, WorkbookStructureError


class MemorySession:
    def __init__(self):
        self.state = {"images": {}, "links": {}, "jobs": {}}
        self.saved = deepcopy(self.state)

    def commit(self):
        self.saved = deepcopy(self.state)

    def rollback(self):
        self.state = deepcopy(self.saved)

    def close(self):
        pass


class MemoryRepository:
    def __init__(self, session):
        self.session = session

    def find_by_sha256(self, sha256):
        return self.session.state["images"].get(sha256)

    def add_image(self, **values):
        record = SimpleNamespace(id=len(self.session.state["images"]) + 1, embeddings=[], **values)
        self.session.state["images"][record.sha256] = record
        return record

    def link_product_image(self, product_id, image, image_role, source_column):
        key = (product_id, image.id, image_role)
        return self.session.state["links"].setdefault(key, SimpleNamespace(
            product_id=product_id, image_id=image.id, image_role=image_role,
            source_column=source_column, is_active=True,
        ))

    def set_current_product_main(self, product_id, image, source_column="K"):
        link = self.link_product_image(product_id, image, "product_main", source_column)
        for item in self.session.state["links"].values():
            if item.product_id == product_id and item.image_role == "product_main":
                item.is_active = item is link
        return link

    def upsert_embedding(self, image, identity, embedding):
        image.embeddings.append(SimpleNamespace(
            encoder=identity.encoder, model_name=identity.model_name,
            pretrained=identity.pretrained, dimension=identity.dimension, embedding=embedding,
        ))

    def create_import_job(self, job_id, original_name):
        job = SimpleNamespace(job_id=job_id, original_name=original_name, status="uploading",
                              processed=0, total=0, summary_json=None, error_message=None)
        self.session.state["jobs"][job_id] = job
        return job

    def find_import_job(self, job_id):
        return self.session.state["jobs"].get(job_id)

    def update_import_job(self, job_id, **values):
        job = self.find_import_job(job_id)
        for name, value in values.items():
            setattr(job, name, value)
        return job


class ImportEncoder:
    identity = EncoderIdentity("fake", "test", "v1", 3)

    def __init__(self):
        self.calls = 0

    def encode(self, image):
        self.calls += 1
        return np.asarray([1, 0, 0], dtype=np.float32)


def import_settings(tmp_path):
    return Settings(tmp_path, "localhost", 5432, "test", "test", "unused", "fake", "test", "v1", "cpu", tmp_path / ".cache" / "open_clip")


def image_bytes(color):
    output = BytesIO()
    Image.new("RGB", (3, 2), color).save(output, format="PNG")
    return output.getvalue()


def workbook_image(color, column="L", product_id="00123"):
    return WorkbookImage(product_id, "product_main" if column == "K" else "buyer_sofa",
                         column, f"{color}.png", image_bytes(color))


def run_import(tmp_path, items, *, session=None, encoder=None, repository_factory=MemoryRepository):
    from backend.excel_import import ExcelImportService

    settings = import_settings(tmp_path)
    session = session or MemorySession()
    encoder = encoder or ImportEncoder()
    job_id = f"{len(session.state['jobs']) + 1:032x}"
    MemoryRepository(session).create_import_job(job_id, "商品.xlsx")
    session.commit()
    workbook_path = settings.import_job_dir / job_id / "workbook.xlsx"
    workbook_path.parent.mkdir(parents=True)
    workbook_path.write_bytes(b"fake workbook")
    parser = items if callable(items) else lambda _: iter(items)
    ExcelImportService(settings, encoder, lambda: session, parser=parser,
                       repository_factory=repository_factory).run(job_id, workbook_path)
    return session, encoder, MemoryRepository(session).find_import_job(job_id), workbook_path


def test_excel_import_main_and_three_buyers_reuses_bytes_and_updates_main(tmp_path):
    """主图若编码、重复内容若新增、切换主图若丢历史，此主流程会失败。"""
    items = [workbook_image("red", "K"), workbook_image("blue", "L"),
             workbook_image("green", "M"), workbook_image("yellow", "N")]
    session, encoder, job, workbook = run_import(tmp_path, items)
    assert job.status == "completed"
    assert (job.processed, job.total) == (4, 4)
    assert encoder.calls == 3
    assert len(session.state["images"]) == 4
    assert not workbook.parent.exists()
    for record, item in zip(session.state["images"].values(), items):
        assert (tmp_path / record.stored_path).read_bytes() == item.data
    session, encoder, job, _ = run_import(tmp_path, [*items, workbook_image("white", "K")],
                                         session=session, encoder=encoder)
    assert len(session.state["images"]) == 5
    assert encoder.calls == 3
    summary = json.loads(job.summary_json)
    assert summary["reused"] == 4
    assert summary["imported"] == 1
    main_links = [link for link in session.state["links"].values() if link.image_role == "product_main"]
    assert [(link.image_id, link.is_active) for link in main_links] == [(1, False), (5, True)]


def test_excel_import_skips_bad_image_and_rolls_back_failed_encoding(tmp_path):
    """坏图或单图编码失败不应阻止下一张图，也不能留下半条图片关联。"""
    class FailingEncoder(ImportEncoder):
        def encode(self, image):
            if image.getpixel((0, 0)) == (255, 0, 0):
                raise RuntimeError("private model path")
            return super().encode(image)

    items = [WorkbookImage("00123", "buyer_sofa", "L", "broken.png", b"broken"),
             workbook_image("red"), workbook_image("green", "M")]
    session, _, job, _ = run_import(tmp_path, items, encoder=FailingEncoder())
    assert job.status == "completed"
    assert job.processed == job.total == 3
    assert len(session.state["images"]) == len(session.state["links"]) == 1
    summary = json.loads(job.summary_json)
    assert summary["skipped"] == 2
    assert len(summary["errors"]) == 2
    assert "private" not in job.summary_json


@pytest.mark.parametrize("failure", [WorkbookStructureError("private workbook path"), SQLAlchemyError("secret")])
def test_excel_import_fatal_failure_marks_failed_and_cleans_only_own_job(tmp_path, failure):
    """工作簿或数据库致命错误必须标为失败并清理任务文件，不能删其他任务。"""
    def broken_parser(_):
        yield workbook_image("blue")
        raise failure

    other = tmp_path / "data" / "import_jobs" / ("f" * 32)
    other.mkdir(parents=True)
    (other / "keep.xlsx").write_bytes(b"keep")
    _, _, job, workbook = run_import(tmp_path, broken_parser)
    assert job.status == "failed"
    assert job.error_message
    assert "private" not in job.error_message and "secret" not in job.error_message
    assert not workbook.parent.exists()
    assert (other / "keep.xlsx").read_bytes() == b"keep"


def test_excel_import_database_write_failure_stops_after_rollback(tmp_path):
    """数据库写入故障不能被当成坏图跳过，也不能提交半条关联。"""
    class BrokenRepository(MemoryRepository):
        def link_product_image(self, *args):
            super().link_product_image(*args)
            raise SQLAlchemyError("secret connection")

    session, encoder, job, workbook = run_import(
        tmp_path, [workbook_image("red"), workbook_image("green")],
        repository_factory=BrokenRepository,
    )
    assert job.status == "failed"
    assert (job.processed, job.total) == (0, 1)
    assert not session.state["images"] and not session.state["links"]
    assert encoder.calls == 0
    assert not workbook.parent.exists()
