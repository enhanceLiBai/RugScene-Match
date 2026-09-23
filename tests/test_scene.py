import pytest
from backend.scene import validate_labels,score_scene

def test_scene_matching_and_unknown():
    labels = {'room':'客厅','sofa_status':'present','sofa_color':'黑色','floor_status':'present','floor_color':'浅灰色','floor_material':'瓷砖/石材'}
    assert score_scene(labels,labels,60)[0] == 60
    assert score_scene(labels,None,60)[0] == -1
    different = {'room':'卧室','sofa_status':'present','sofa_color':'绿色','floor_status':'present','floor_color':'深木色','floor_material':'木纹'}
    assert score_scene(labels,different,90)[0] < score_scene(labels,labels,60)[0]

def test_invalid_labels_rejected():
    with pytest.raises(ValueError): validate_labels({'sofa_color':'imaginary'})

def test_other_color_uses_model_detail_when_available():
    labels = validate_labels({'room':'客厅', 'sofa_status':'present',
                              'sofa_color':'其他', 'sofa_color_detail':'卡其色/浅棕色',
                              'floor_status':'present', 'floor_color':'浅灰色',
                              'floor_material':'瓷砖/石材'})
    assert labels['sofa_color'] == '卡其色'
    assert labels['sofa_color_group'] == '棕色系'


def test_strict_filters_and_visual_order():
    query = dict(room='客厅', sofa_status='present', sofa_color='米色',
                 floor_status='present', floor_color='米色', floor_material='瓷砖/石材')
    close = {**query, 'floor_color': '浅灰色'}
    assert score_scene(query, close, 94.49)[0] == 94.49
    assert score_scene(query, query, 75.45)[0] == 75.45
    for change in ({'room':'卧室'}, {'sofa_color':'蓝色'}, {'floor_color':'深木色'},
                   {'floor_material':'木纹'}, {'room':'无法判断'}, {'floor_status':'unknown'},
                   {'floor_color':'其他'}):
        assert score_scene(query, {**query, **change}, 99)[0] == -1


def test_gray_tones_match_without_allowing_black_white():
    query = dict(room='客厅', sofa_status='present', sofa_color='米色',
                 floor_status='present', floor_color='浅灰色', floor_material='瓷砖/石材')
    assert score_scene(query, {**query, 'floor_color':'深灰色'}, 85.23)[0] == 85.23
    assert score_scene({**query, 'floor_color':'白色'}, {**query, 'floor_color':'黑色'}, 99)[0] == -1


@pytest.mark.parametrize('decision,accepted', [('match', True), ('mismatch', False), ('uncertain', False)])
def test_pair_review_requires_all_four_attributes(monkeypatch, tmp_path, decision, accepted):
    from backend.scene import SceneClient
    client = SceneClient(tmp_path)
    result = dict(room='match', sofa_color='match', floor_color=decision,
                  floor_material='match', reason='地面属性复核')
    monkeypatch.setattr(client, '_request', lambda *args, **kwargs: result)
    assert client.compare_scenes(object(), object())[0] is accepted
