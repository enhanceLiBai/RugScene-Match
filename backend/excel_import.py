"""单遍处理 Excel 图片，逐图提交并持续保存后台任务进度。"""

from collections.abc import Callable, Iterable
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.encoders.base import ImageEncoder
from backend.image_assets import store_image_bytes, validate_image_bytes
from backend.repository import ImageRepository
from backend.tencent_excel import WorkbookImage, WorkbookStructureError, iter_product_images


logger = logging.getLogger(__name__)


def cleanup_import_job(settings: Settings, job_id: str) -> None:
    """只清理给定 32 位任务 ID 对应的目录，拒绝根目录和越界路径。"""
    if re.fullmatch(r"[0-9a-f]{32}", job_id) is None:
        raise ValueError("导入任务标识无效。")
    root = settings.import_job_dir.resolve()
    target = (root / job_id).resolve()
    if target.parent != root:
        raise ValueError("导入任务路径无效。")
    if target.exists():
        shutil.rmtree(target)


class ExcelImportService:
    """解析器和仓库可注入；每张图及每次进度更新均使用独立事务。"""

    def __init__(
        self,
        settings: Settings,
        encoder: ImageEncoder,
        session_factory: Callable[[], Session],
        *,
        parser: Callable[[Path], Iterable[WorkbookImage]] = iter_product_images,
        repository_factory: Callable[[Session], ImageRepository] = ImageRepository,
    ) -> None:
        self.settings = settings
        self.encoder = encoder
        self.session_factory = session_factory
        self.parser = parser
        self.repository_factory = repository_factory

    def _update_job(self, job_id: str, **values: object) -> None:
        session = self.session_factory()
        try:
            self.repository_factory(session).update_import_job(job_id, **values)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _import_image(self, item: WorkbookImage) -> tuple[bool, bool]:
        """返回是否新增、是否编码；任一步失败均回滚当前图片的记录与关联。"""
        session = self.session_factory()
        try:
            repository = self.repository_factory(session)
            record = repository.find_by_sha256(hashlib.sha256(item.data).hexdigest())
            imported = record is None
            validated = None
            if imported:
                validated, target = store_image_bytes(item.data, item.filename, self.settings.image_dir)
                record = repository.add_image(
                    original_name=validated.original_name,
                    stored_path=target.relative_to(self.settings.project_root.resolve()).as_posix(),
                    sha256=validated.sha256, mime_type=validated.mime_type,
                    width=validated.width, height=validated.height,
                )
            encoded = False
            if item.role == "product_main":
                # 主图不读取编码器身份，保持模型惰性加载，也不产生搜索向量。
                repository.set_current_product_main(item.product_id, record, item.source_column)
            else:
                repository.link_product_image(item.product_id, record, item.role, item.source_column)
                identity = self.encoder.identity
                has_embedding = any(
                    (embedding.encoder, embedding.model_name, embedding.pretrained, embedding.dimension)
                    == (identity.encoder, identity.model_name, identity.pretrained, identity.dimension)
                    for embedding in record.embeddings
                )
                if not has_embedding:
                    validated = validated or validate_image_bytes(item.data, item.filename)
                    repository.upsert_embedding(record, identity, self.encoder.encode(validated.image))
                    encoded = True
            session.commit()
            return imported, encoded
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def run(self, job_id: str, workbook_path: Path) -> None:
        """运行已创建的任务；单图失败继续，工作簿或数据库失败结束并清理 Excel。"""
        summary = {"imported": 0, "reused": 0, "encoded": 0, "skipped": 0, "errors": []}
        processed = total = 0

        def progress(status: str, error: str | None = None) -> None:
            self._update_job(
                job_id, status=status, processed=processed, total=total,
                summary_json=json.dumps(summary, ensure_ascii=False), error_message=error,
            )

        try:
            progress("parsing")
            for item in self.parser(workbook_path):
                # total 是单遍流式解析中已发现的数量，不预读全部图片计算总数。
                total += 1
                progress("importing")
                try:
                    imported, encoded = self._import_image(item)
                except SQLAlchemyError:
                    raise
                except Exception:
                    summary["skipped"] += 1
                    summary["errors"].append({
                        "product_id": item.product_id, "source_column": item.source_column,
                        "message": "图片无效或处理失败，已跳过。",
                    })
                else:
                    summary["imported" if imported else "reused"] += 1
                    summary["encoded"] += int(encoded)
                processed += 1
                progress("importing")
            progress("completed")
        except Exception as error:
            message = "工作簿无效或结构不受支持。" if isinstance(error, WorkbookStructureError) else "导入失败，服务暂不可用，请稍后重试。"
            try:
                progress("failed", message)
            except SQLAlchemyError:
                # 数据库持续不可用时无法写入失败状态，但仍必须释放临时 Excel。
                logger.error("导入任务失败，数据库暂不可用，未能保存失败状态。")
        finally:
            cleanup_import_job(self.settings, job_id)
