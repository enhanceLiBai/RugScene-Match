import pytest
from backend.scene import validate_labels,score_scene

def test_scene_matching_and_unknown():
    labels = {'room':'客厅','sofa_status':'present','sofa_color':'黑色','floor_status':'present','floor_color':'浅灰色','floor_material':'瓷砖/石材'}
    assert score_scene(labels,labels,60)[0] == 92
    assert score_scene(labels,None,60)[0] == -1
    different = {'room':'卧室','sofa_status':'present','sofa_color':'绿色','floor_status':'present','floor_color':'深木色','floor_material':'木纹'}
    assert score_scene(labels,different,90)[0] < score_scene(labels,labels,60)[0]

def test_invalid_labels_rejected():
    with pytest.raises(ValueError): validate_labels({'sofa_color':'imaginary'})
