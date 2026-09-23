import json
from types import SimpleNamespace
from time import monotonic
import threading
from PIL import Image
from backend import ranking
from backend.repository import ProductSearchRow


def setup(tmp_path):
    images = tmp_path / 'data/images'
    images.mkdir(parents=True)
    for id in (1, 2):
        Image.new('RGB', (16, 16), (160, 140, 100)).save(images / f'{id}.png')
    settings = SimpleNamespace(project_root=tmp_path, image_dir=images)
    repo = SimpleNamespace(find_by_id=lambda id: SimpleNamespace(stored_path=f'data/images/{id}.png'))
    return settings, repo


def test_cached_attributes_change_order_and_preserve_base(tmp_path):
    settings, repo = setup(tmp_path)
    cache = tmp_path / 'data/ranking-labels'
    cache.mkdir()
    for id, distance, area in [(1, 'very_far', 'tiny'), (2, 'normal', 'normal')]:
        (cache/f'{id}.json').write_text(json.dumps(dict(version=ranking.VERSION,model='test',view_distance=distance,rug_area=area)))
    def request(prompt, images, **kwargs):
        manifest = json.loads(prompt[len(ranking.PROMPT):])
        assert all(item['cached_attributes'] for item in manifest)
        return {'items': [dict(image_id=id, view_distance='normal', rug_area='normal', query_tone='warm', candidate_tone='warm', query_evidence='暖光', candidate_evidence='暖光', tone_match='same', tone_reason='两图均为暖色光线') for id in (1,2)]}
    client = SimpleNamespace(model='test', _request=request)
    rows = [ProductSearchRow(None, 1, None, None, 95), ProductSearchRow(None, 2, None, None, 85)]
    result = ranking.rerank(settings, repo, client, Image.new('RGB',(8,8),(160,140,100)), rows, 2)
    assert [x[0].buyer_image_id for x in result] == [2,1]
    assert [x[1] for x in result] == [89,83]
    assert rows[0].similarity_percent == 95
    assert ranking.rerank(settings,repo,client,Image.new('RGB',(8,8)),[],2) == []


def test_first_use_persists_and_reuses(tmp_path):
    settings, repo = setup(tmp_path)
    calls=[]
    def request(*args, **kwargs):
        manifest = json.loads(args[0][len(ranking.PROMPT):])
        calls.append(manifest[0]['cached_attributes'])
        return {'items': [dict(image_id=1, view_distance='far',rug_area='small',query_tone='warm', candidate_tone='warm' if len(calls)==1 else 'cold', query_evidence='暖光', candidate_evidence='不同光线', tone_match='same' if len(calls)==1 else 'different',tone_reason='本次冷暖比较')]}
    client=SimpleNamespace(model='test',_request=request)
    rows=[ProductSearchRow(None,1,None,None,90)]
    for attempt in range(2):
        result=ranking.rerank(settings,repo,client,Image.new('RGB',(8,8),(160,140,100)),rows,1)
        assert result[0][1] == (86 if attempt == 0 else 82)
    assert calls[0] is None and calls[1]['view_distance'] == 'far'


def test_slow_annotation_returns_without_waiting_for_cloud(tmp_path,monkeypatch):
    settings,repo=setup(tmp_path)
    release=threading.Event()
    def request(*args,**kwargs):
        release.wait(2)
        return dict(view_distance='normal',rug_area='normal')
    monkeypatch.setattr(ranking,'WAIT_SECONDS',0.02)
    start=monotonic()
    try:
        result=ranking.rerank(settings,repo,SimpleNamespace(model='test',_request=request),Image.new('RGB',(8,8)),[ProductSearchRow(None,1,None,None,90)],1)
        assert monotonic()-start < 1
        assert '待补标' in result[0][2][0]
    finally:
        release.set()


def test_only_top10_and_unknown_tone_does_not_add_points(tmp_path):
    settings, repo = setup(tmp_path)
    repo.find_by_id = lambda id: SimpleNamespace(stored_path='data/images/1.png')
    calls = []
    def request(prompt, images, **kwargs):
        manifest = json.loads(prompt[len(ranking.PROMPT):])
        assert len(manifest) == 1 and len(images) == 2
        calls.append(manifest[0]['image_id'])
        return {'items': [dict(image_id=x['image_id'],view_distance='unknown',rug_area='unknown',tone_match='unknown',tone_reason='无法判断') for x in manifest] + [dict(image_id=99,view_distance='normal',rug_area='normal',query_tone='warm', candidate_tone='warm', query_evidence='暖光', candidate_evidence='暖光', tone_match='same',tone_reason='额外候选') ]}
    rows=[ProductSearchRow(None,id,None,None,100-id) for id in range(1,13)]
    result=ranking.rerank(settings,repo,SimpleNamespace(model='test',_request=request),Image.new('RGB',(8,8)),rows,20)
    assert len(result)==10
    assert set(calls) == set(range(1,11))
    assert all(score == row.similarity_percent for row,score,reasons in result)


def test_cool_neutral_and_warm_neutral_receive_no_bonus():
    assert ranking.tone_relation('cool_neutral','warm_neutral') == 'different'
    assert ranking.tone_relation('neutral','warm_neutral') == 'close'
    assert ranking.tone_relation('warm','warm') == 'same'
    assert ranking.tone_relation('mixed','mixed') == 'unknown'


def test_pairs_run_concurrently_and_keep_success_when_other_pair_times_out(tmp_path, monkeypatch):
    settings, repo = setup(tmp_path)
    barrier = threading.Barrier(2)
    release = threading.Event()
    monkeypatch.setattr(ranking, 'WAIT_SECONDS', 0.2)
    def request(prompt, images, **kwargs):
        item = json.loads(prompt[len(ranking.PROMPT):])[0]
        assert len(images) == 2
        barrier.wait(timeout=1)
        if item['image_id'] == 2:
            release.wait(2)
            raise RuntimeError('model unavailable')
        return {'items': [dict(image_id=1, view_distance='normal', rug_area='normal',
                              query_tone='warm', candidate_tone='warm', query_evidence='暖光',
                              candidate_evidence='暖光', tone_match='same', tone_reason='一致')]}
    try:
        result = ranking.rerank(settings, repo, SimpleNamespace(model='test', _request=request),
                               Image.new('RGB', (8,8)),
                               [ProductSearchRow(None, i, None, None, 90) for i in (1,2)], 2)
        assert [score for row, score, reasons in result] == [94, 90]
    finally:
        release.set()
