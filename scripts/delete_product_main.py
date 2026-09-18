"""预览或批量删除仅用作商品主图的图片；不按图片外观猜测用途。"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select
from backend.config import Settings
from backend.db import create_session_factory, dispose_session_factory
from backend.models import ImageRecord, ProductImage, SceneLabel


def main_image_ids(session):
    main = select(ProductImage.image_id).where(ProductImage.image_role == 'product_main')
    buyer = select(ProductImage.image_id).where(ProductImage.image_role == 'buyer_sofa')
    candidates = list(session.scalars(select(ImageRecord.id).where(
        ImageRecord.id.in_(main), ~ImageRecord.id.in_(buyer)).order_by(ImageRecord.id)))
    shared = list(session.scalars(select(ImageRecord.id).where(
        ImageRecord.id.in_(main), ImageRecord.id.in_(buyer)).order_by(ImageRecord.id)))
    return candidates, shared


def delete_one(session, settings, image_id):
    record = session.get(ImageRecord, image_id)
    if record is None:
        return 'skipped'
    roles = set(session.scalars(select(ProductImage.image_role).where(ProductImage.image_id == image_id)))
    if roles != {'product_main'}:
        return 'skipped'
    path = (settings.project_root / record.stored_path).resolve()
    if not path.is_relative_to(settings.image_dir.resolve()):
        raise ValueError('图片路径超出图库目录')
    session.execute(delete(SceneLabel).where(SceneLabel.image_id == image_id))
    session.delete(record)
    session.commit()
    # 与页面删除一致：先提交数据库，再清理文件；文件失败明确报告。
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return 'file_cleanup_failed'
    return 'deleted'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='实际删除数据库记录及图库原文件，不可撤销')
    args = parser.parse_args()
    factory = None
    try:
        settings = Settings.load()
        factory = create_session_factory(settings)
        with factory() as session:
            ids, shared = main_image_ids(session)
        print(f'仅主图用途：{len(ids)} 张；同时关联买家秀，保留：{len(shared)} 张。')
        print('待删除图片 ID：' + ', '.join(map(str, ids)))
        if not args.execute:
            print('预览完成，未修改数据。添加 --execute 实际删除。')
            return 0
        counts = dict(deleted=0, skipped=0, failed=0, file_cleanup_failed=0)
        for image_id in ids:
            try:
                with factory() as session:
                    result = delete_one(session, settings, image_id)
                counts[result] += 1
                if result == 'file_cleanup_failed':
                    print(f'图片 #{image_id}：数据库已删除，但原文件清理失败。')
            except Exception:
                counts['failed'] += 1
                print(f'图片 #{image_id}：删除失败，保留并继续。')
        print('处理结果：' + ', '.join(f'{key}={value}' for key, value in counts.items()))
        return 1 if counts['failed'] or counts['file_cleanup_failed'] else 0
    except Exception:
        print('执行失败，请检查数据库连接、配置或文件权限。', file=sys.stderr)
        return 1
    finally:
        if factory is not None:
            dispose_session_factory(factory)


if __name__ == '__main__':
    raise SystemExit(main())
