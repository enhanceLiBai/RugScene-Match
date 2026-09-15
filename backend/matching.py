"""严格候选与少量高视觉相似冲突候选合并，不以放宽条件凑数。"""
from PIL import Image, UnidentifiedImageError

from backend.scene import SceneError, score_scene

MAX_CONFLICT_REVIEWS = 3
MIN_REVIEW_SIMILARITY = 80


def review_conflicts(settings, repository, client, query_image, query_labels,
                     accepted, visual_candidates, top_k):
    rows = list(accepted)
    notes = {}
    attempted = failures = 0
    checked = set()
    cutoff = rows[-1].similarity_percent if len(rows) >= top_k else 0
    for candidate in visual_candidates:
        if candidate.similarity_percent < max(MIN_REVIEW_SIMILARITY, cutoff):
            continue
        if score_scene(query_labels, candidate.scene_labels, candidate.similarity_percent)[0] >= 0:
            continue
        if candidate.buyer_image_id in checked:
            continue
        if attempted >= MAX_CONFLICT_REVIEWS:
            break
        checked.add(candidate.buyer_image_id)
        attempted += 1
        try:
            record = repository.find_by_id(candidate.buyer_image_id)
            if record is None:
                raise SceneError('候选图片不存在')
            path = (settings.project_root / record.stored_path).resolve()
            if not path.is_relative_to(settings.image_dir.resolve()):
                raise SceneError('图片路径无效')
            with Image.open(path) as candidate_image:
                compatible, reason = client.compare_scenes(query_image, candidate_image)
            if compatible:
                rows.append(candidate)
                notes[candidate.buyer_image_id] = '双图复核通过：' + reason
        except (SceneError, OSError, UnidentifiedImageError):
            failures += 1
    rows.sort(key=lambda row: (-row.similarity_percent, row.buyer_image_id, row.product_id or ''))
    seen = set()
    results = []
    for row in rows:
        key = ('product', row.product_id) if row.product_id else ('image', row.buyer_image_id)
        if key in seen:
            continue
        seen.add(key)
        results.append(row)
        if len(results) >= top_k:
            break
    return results, notes, attempted, failures
