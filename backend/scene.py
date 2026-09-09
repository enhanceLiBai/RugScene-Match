"""共享场景识别、标签缓存及属性评分。"""
import base64
import json
import os
from io import BytesIO
import httpx
from dotenv import dotenv_values
from PIL import Image
from sqlalchemy import select
from backend.models import SceneLabel, ImageRecord, ProductImage

VERSION = "scene-v3"
COLORS = ['黑色','白色','米色','浅灰色','深灰色','棕色','浅木色','深木色','蓝色','绿色','红色','黄色','其他','无法判断']
MATERIALS = ['木纹','瓷砖/石材','水泥感','其他','无法判断']
ROOMS = ['客厅','卧室','玄关','餐厅','书房','其他','无法判断']
STATUSES = ['present','not_present','unknown']
OPTIONS = {'room': ROOMS, 'sofa_status': STATUSES, 'sofa_color': COLORS, 'floor_status': STATUSES, 'floor_color': COLORS, 'floor_material': MATERIALS}

class SceneError(RuntimeError):
    pass

class SceneClient:
    def __init__(self, root):
        config = {**dotenv_values(root / '.env'), **os.environ}
        self.key = config.get('DEEPSEEK_API_KEY', '')
        self.url = config.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')
        self.model = config.get('DEEPSEEK_MODEL', 'deepseek-v4-flash-vision-exp')

    def identify(self, image):
        if not self.key:
            raise SceneError('未配置视觉模型密钥')
        copy = image.convert('RGB'); copy.thumbnail((1280,1280))
        output = BytesIO(); copy.save(output, format='JPEG', quality=85)
        prompt = '识别空间类型、沙发和地板。沙发/地板先填状态：present=画面确认存在，not_present=确认没有，unknown=可能存在但看不清；present时填写颜色/材质，否则颜色材质填无法判断。只返回JSON，键及允许值：' + json.dumps(OPTIONS, ensure_ascii=False)
        try:
            r = httpx.post(self.url + '/chat/completions', headers={'Authorization': 'Bearer '+self.key}, json={
                'model': self.model, 'temperature': 0, 'max_tokens': 2048,
                'messages':[{'role':'user','content':[{'type':'text','text':prompt}, {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(output.getvalue()).decode()}}]}]}, timeout=60, trust_env=False)
            r.raise_for_status()
            content = r.json()['choices'][0]['message']['content'].strip()
            if content.startswith('```'): content = content.split('\n',1)[1].rsplit('```',1)[0]
            return validate_labels(json.loads(content))
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            raise SceneError('场景识别暂不可用') from None

def validate_labels(labels):
    if not isinstance(labels, dict) or any(labels.get(k) not in options for k,options in OPTIONS.items()):
        raise ValueError('场景标签格式无效')
    result = {k:labels[k] for k in OPTIONS}
    for prefix in ('sofa','floor'):
        if result[f'{prefix}_status'] != 'present':
            result[f'{prefix}_color'] = '无法判断'
            if prefix == 'floor': result['floor_material'] = '无法判断'
    return result

def ensure_label(session, client, image_id, image):
    existing = session.get(SceneLabel, image_id)
    if existing and existing.model == client.model and existing.version == VERSION:
        return
    labels = client.identify(image)
    if existing is None:
        existing = SceneLabel(image_id=image_id); session.add(existing)
    existing.model = client.model; existing.version = VERSION
    existing.labels_json = json.dumps(labels, ensure_ascii=False)

def score_scene(query, candidate, visual):
    if not query or not candidate: return -1, ['missing_labels']
    if any(query.get(k) != 'present' or candidate.get(k) != 'present' for k in ('sofa_status','floor_status')):
        return -1, ['required_attribute_missing']
    score = visual * .2
    reasons = []
    query_room = query.get('room','无法判断'); candidate_room = candidate.get('room','无法判断')
    if query_room != '无法判断' and candidate_room != '无法判断' and query_room != candidate_room:
        return -1, ['room_mismatch']
    if any(query.get(k) == '无法判断' or candidate.get(k) == '无法判断' for k in ('sofa_color','floor_color','floor_material')):
        return -1, ['required_attribute_unknown']
    score = visual * .2
    for key,weight in [('sofa_color',.35),('floor_color',.25),('floor_material',.2)]:
        q = (query or {}).get(key,'无法判断'); c = (candidate or {}).get(key,'无法判断')
        if q == '无法判断' or c == '无法判断':
            score += visual * weight
        elif q == c:
            score += 100 * weight; reasons.append(key)
        elif key != 'floor_material' and any(q in g and c in g for g in [COLORS[1:4],['黑色','深灰色'],['棕色','浅木色','深木色']]):
            score += 50 * weight
    return round(score,2), reasons

def backfill(settings, factory, client, job_id):
    from backend.repository import ImageRepository
    with factory() as session:
        ids = list(session.scalars(select(ProductImage.image_id).where(ProductImage.image_role=='buyer_sofa',ProductImage.is_active.is_(True)).distinct()))
    done = failed = 0
    for image_id in ids:
        try:
            with factory() as session:
                record = session.get(ImageRecord,image_id)
                path = (settings.project_root / record.stored_path).resolve()
                if not path.is_relative_to(settings.image_dir.resolve()): raise SceneError('图片路径无效')
                with Image.open(path) as image: ensure_label(session,client,image_id,image)
                session.commit()
        except Exception:
            failed += 1
        done += 1
        with factory() as session:
            ImageRepository(session).update_import_job(job_id,status='completed' if done==len(ids) else 'importing',processed=done,total=len(ids),summary_json=json.dumps({'labeled':done-failed,'skipped':failed}))
            session.commit()
    if not ids:
        with factory() as session:
            ImageRepository(session).update_import_job(job_id,status='completed',processed=0,total=0); session.commit()
