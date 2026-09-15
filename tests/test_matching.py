from types import SimpleNamespace

import pytest
from PIL import Image

from backend.matching import review_conflicts
from backend.repository import ProductSearchRow
from backend.scene import SceneError


@pytest.mark.parametrize('decision,expected,failures', [(True, [2, 1], 0), (False, [1], 0), ('error', [1], 1)])
def test_conflict_review_admission_and_failure(tmp_path, decision, expected, failures):
    root = tmp_path / 'data' / 'images'
    root.mkdir(parents=True)
    Image.new('RGB', (8, 8)).save(root / 'candidate.png')
    tags = dict(room='客厅', sofa_status='present', sofa_color='米色',
                floor_status='present', floor_color='米色', floor_material='瓷砖/石材')
    accepted = ProductSearchRow(None, 1, None, None, 75, tags)
    candidate = ProductSearchRow(None, 2, None, None, 95, {**tags, 'floor_material':'木纹'})
    calls = []
    def compare(query_image, candidate_image):
        calls.append(candidate_image.size)
        if decision == 'error':
            raise SceneError('unavailable')
        return decision, '已对照裸露地面'
    repository = SimpleNamespace(find_by_id=lambda _: SimpleNamespace(stored_path='data/images/candidate.png'))
    rows, notes, attempts, failed = review_conflicts(
        SimpleNamespace(project_root=tmp_path, image_dir=root), repository,
        SimpleNamespace(compare_scenes=compare), None, tags, [accepted], [candidate], 10)
    assert [r.buyer_image_id for r in rows] == expected
    assert attempts == 1 and failed == failures
    assert calls == [(8, 8)]
    if decision is True:
        assert notes[2].startswith('双图复核通过')
        assert rows[0].similarity_percent == 95
