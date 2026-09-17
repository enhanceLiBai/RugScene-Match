import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select, func

from backend.api import create_app
from backend.auth import create_user
from backend.models import MatchHistory, MatchHistoryImage, MatchConversion
from test_api import database_settings, database_engine, api_session_factory, api_settings, fake_encoder, png_bytes


def test_conversion_and_private_history(api_settings, api_session_factory, fake_encoder):
    password = 'test-' + uuid.uuid4().hex
    with api_session_factory() as session:
        admin = create_user(session, 'admin_' + uuid.uuid4().hex[:10], '管理员', password, 'admin')
        customer = create_user(session, 'cs_' + uuid.uuid4().hex[:10], '客服甲', password, 'customer_service')
        other = create_user(session, 'cs_' + uuid.uuid4().hex[:10], '客服乙', password, 'customer_service')
        snapshot = {'results': [{'rank': 1, 'product_id': 'P123', 'matched_buyer_image_url': '/api/images/1', 'similarity': 99},
                                {'rank': 2, 'product_id': None, 'matched_buyer_image_url': '/api/images/2', 'similarity': 90}]}
        history = MatchHistory(user_id=customer.id, payload_json=json.dumps(snapshot))
        foreign = MatchHistory(user_id=other.id, payload_json=json.dumps(snapshot))
        session.add_all([history, foreign]); session.flush()
        session.add(MatchHistoryImage(history_id=history.id, content=png_bytes(), mime_type='image/png'))
        session.commit()
        history_id, foreign_id = history.id, foreign.id
        customer_name, other_name, admin_name = customer.username, other.username, admin.username
    app = create_app(settings=api_settings, encoder=fake_encoder, session_factory=api_session_factory)
    headers = {'CF-Ray': 'test', 'CF-Connecting-IP': '8.8.8.8'}
    with TestClient(app, client=('127.0.0.1', 50000)) as manager, TestClient(app, client=('127.0.0.1', 50001), headers=headers) as worker:
        assert worker.get('/api/my-history').status_code == 401
        assert worker.post('/api/auth/login', json={'username': customer_name, 'password': password}).status_code == 200
        listing = worker.get('/api/my-history').json()
        assert [row['id'] for row in listing['items']] == [history_id]
        assert listing['items'][0]['conversion'] is None
        assert worker.get(f'/api/my-history/{foreign_id}').status_code == 404
        assert worker.get(f'/api/my-history/{foreign_id}/image').status_code == 404
        detail = worker.get(f'/api/my-history/{history_id}').json()
        assert detail['payload'] == snapshot
        assert worker.get(detail['query_image_url']).content == png_bytes()
        body = {'history_id': history_id, 'rank': 1}
        assert worker.post('/api/conversions', json={**body, 'product_id': 'FORGED'}).status_code == 422
        assert worker.post('/api/conversions', json={**body, 'rank': 3}).status_code == 422
        saved = worker.post('/api/conversions', json=body)
        assert saved.status_code == 200
        assert saved.json()['conversion']['product_id'] == 'P123'
        assert worker.post('/api/conversions', json=body).json() == saved.json()
        assert worker.post('/api/conversions', json={**body, 'rank': 2}).status_code == 409
        assert worker.get(f'/api/my-history/{history_id}').json()['conversion'] == saved.json()['conversion']
        assert worker.get('/api/conversions').status_code == 403
        assert worker.post('/api/auth/login', json={'username': other_name, 'password': password}).status_code == 200
        assert worker.post('/api/conversions', json=body).status_code == 404
        assert manager.post('/api/auth/admin-login', json={'username': admin_name, 'password': password}).status_code == 200
        data = manager.get('/api/conversions').json()
        item = next(row for row in data['items'] if row['history_id'] == history_id)
        assert item['user']['username'] == customer_name
        assert not any(row['history_id'] == foreign_id for row in data['items'])
        with api_session_factory() as session:
            assert session.scalar(select(func.count()).select_from(MatchConversion).where(MatchConversion.history_id == history_id)) == 1
            # 新增21次查询验证个人列表翻页，未登记不会产生转化记录。
            session.add_all([MatchHistory(user_id=customer.id, payload_json='{"results":[]}') for _ in range(21)])
            session.commit()
        assert worker.post('/api/auth/login', json={'username': customer_name, 'password': password}).status_code == 200
        first = worker.get('/api/my-history').json()
        second = worker.get('/api/my-history', params={'before': first['next_before']}).json()
        assert len(first['items']) == 20
        assert history_id in [row['id'] for row in second['items']]
        assert set(row['id'] for row in first['items']).isdisjoint(row['id'] for row in second['items'])
        # 没有商品ID的少量结果按排名登记，不增加补关联流程。
        assert worker.post('/api/auth/login', json={'username': other_name, 'password': password}).status_code == 200
        assert worker.post('/api/conversions', json={'history_id': foreign_id, 'rank': 2}).json()['conversion']['product_id'] is None
