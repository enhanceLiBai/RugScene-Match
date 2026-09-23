"""真实数据库事务中的登录、角色与查询归属闭环，不调用外部模型。"""
from datetime import datetime, timedelta, timezone
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.api import create_app
from backend.auth import COOKIE, create_user, verify_password
from backend.models import UserAccount, LoginSession, MatchHistory, MatchConversion
from backend.repository import ImageRepository, ProductSearchRow
from backend.scene import SceneClient
from test_api import database_settings, database_engine, api_session_factory, api_settings, fake_encoder, png_bytes


def test_login_accounts_history_ownership_and_logout(api_settings, api_session_factory, fake_encoder, monkeypatch):
    suffix = uuid.uuid4().hex[:12]
    secret = 'test-only-' + uuid.uuid4().hex
    with api_session_factory() as session:
        admin = create_user(session, 'admin_' + suffix, '测试管理员', secret, 'admin')
        admin_name = admin.username
        session.commit()
        assert admin.password_hash != secret
        assert verify_password(secret, admin.password_hash)
    app = create_app(settings=api_settings, encoder=fake_encoder, session_factory=api_session_factory)
    with TestClient(app, client=('127.0.0.1', 50000)) as manager, TestClient(app, client=('127.0.0.1', 50001)) as worker:
        assert worker.get('/', follow_redirects=False).headers['location'] == '/login'
        assert worker.get('/admin', follow_redirects=False).headers['location'] == '/admin/login'
        assert worker.get('/login').status_code == 200
        assert '注册' not in worker.get('/login').text
        assert worker.get('/api/images/1').status_code == 401
        assert worker.post('/api/search').status_code == 401
        assert worker.post('/api/accounts', json={}).status_code == 401
        assert manager.post('/api/auth/admin-login', json={'username': admin_name, 'password': 'wrong'}).status_code == 401
        login = manager.post('/api/auth/admin-login', json={'username': admin_name, 'password': secret})
        assert login.status_code == 200
        assert 'HttpOnly' in login.headers['set-cookie']
        assert 'SameSite=lax' in login.headers['set-cookie']
        raw_cookie = manager.cookies.get(COOKIE)
        with api_session_factory() as session:
            assert session.get(LoginSession, raw_cookie) is None
        user_name = 'cs_' + suffix
        created = manager.post('/api/accounts', json={'username': user_name, 'display_name': '客服小王', 'password': secret, 'role': 'admin'})
        assert created.status_code == 201
        user_id = created.json()['user']['id']
        assert created.json()['user']['role'] == 'customer_service'
        assert 'password' not in created.text
        assert manager.post('/api/accounts', json={'username': user_name, 'display_name': '重复账号', 'password': secret}).status_code == 409
        assert worker.post('/api/auth/admin-login', json={'username': user_name, 'password': secret}).status_code == 401
        assert worker.post('/api/auth/login', json={'username': user_name, 'password': secret}).status_code == 200
        assert worker.get('/').status_code == 200
        for url in ['/admin', '/api/accounts', '/api/history', '/api/feedback']:
            assert worker.get(url).status_code == 403
        assert worker.get('/api/auth/me').json()['user']['id'] == user_id
        assert manager.get('/admin').status_code == 200

        tags = dict(room='客厅', sofa_status='present', sofa_color='米色', floor_status='present', floor_color='浅灰色', floor_material='瓷砖/石材')
        monkeypatch.setattr(SceneClient, 'identify', lambda *args: tags)
        monkeypatch.setattr(ImageRepository, 'search_products', lambda *args, **kwargs: [ProductSearchRow('P', 1, None, None, 99, tags, '米色')])
        response = worker.post('/api/search', data={'user_id': admin.id}, files={'image': ('customer.png', png_bytes(), 'image/png')})
        assert response.status_code == 200
        history_id = response.json()['history_id']
        assert history_id
        detail = manager.get(f'/api/history/{history_id}').json()
        assert detail['user']['id'] == user_id
        assert detail['user']['display_name'] == '客服小王'
        assert manager.get(detail['query_image_url']).content == png_bytes()
        listing = manager.get('/api/history').json()['items']
        assert next(row for row in listing if row['id'] == history_id)['user']['id'] == user_id
        assert worker.post('/api/conversions', json={'history_id': history_id, 'rank': 1}).status_code == 200
        with api_session_factory() as session:
            feedback = session.scalar(select(MatchConversion).where(MatchConversion.history_id == history_id))
            assert feedback.submitted_by == user_id
            old = MatchHistory(payload_json='{"results":[]}')
            session.add(old)
            session.flush()
            old_id = old.id
            session.commit()
        assert manager.get(f'/api/history/{old_id}').json()['user'] is None
        assert worker.post('/api/conversions', json={'history_id': old_id, 'rank': 1}).status_code == 404
        assert worker.post('/api/auth/logout', headers={'Origin': 'https://other.example'}).status_code == 403
        old_token = worker.cookies.get(COOKIE)
        assert worker.post('/api/auth/logout').status_code == 200
        worker.cookies.set(COOKIE, old_token)
        assert worker.get('/api/auth/me').status_code == 401


def test_tunnel_login_and_expiration(api_settings, api_session_factory, fake_encoder):
    name = 'cs_' + uuid.uuid4().hex[:12]
    secret = 'test-only-' + uuid.uuid4().hex
    with api_session_factory() as session:
        user = create_user(session, name, '测试客服', secret, 'customer_service')
        session.commit()
        user_id = user.id
    app = create_app(settings=api_settings, encoder=fake_encoder, session_factory=api_session_factory)
    headers = {'CF-Ray': 'test', 'CF-Connecting-IP': '8.8.8.8', 'X-Forwarded-Proto': 'https'}
    with TestClient(app, base_url='https://testserver', client=('127.0.0.1', 50000), headers=headers) as client:
        assert client.get('/login').status_code == 200
        assert client.get('/admin/login').status_code == 403
        assert client.post('/api/auth/admin-login', json={'username': name, 'password': secret}).status_code == 403
        response = client.post('/api/auth/login', json={'username': name, 'password': secret})
        assert response.status_code == 200
        assert 'Secure' in response.headers['set-cookie']
        assert client.get('/api/auth/me').json()['user']['id'] == user_id
        with api_session_factory() as session:
            for login in session.scalars(select(LoginSession).where(LoginSession.user_id == user_id)):
                login.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()
        assert client.get('/api/auth/me').status_code == 401


def test_chinese_account_creation_and_login(api_settings, api_session_factory, fake_encoder):
    secret = 'test-only-' + uuid.uuid4().hex
    admin_name = 'admin_' + uuid.uuid4().hex[:10]
    name = '客服小王' + uuid.uuid4().hex[:8]
    with api_session_factory() as session:
        create_user(session, admin_name, '测试管理员', secret, 'admin')
        session.commit()
    app = create_app(settings=api_settings, encoder=fake_encoder, session_factory=api_session_factory)
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        assert client.post('/api/auth/admin-login', json={'username': admin_name, 'password': secret}).status_code == 200
        response = client.post('/api/accounts', json={'username': name, 'display_name': '小王', 'password': secret})
        assert response.status_code == 201
        assert response.json()['user']['username'] == name
        assert client.post('/api/auth/logout').status_code == 200
        login = client.post('/api/auth/login', json={'username': name, 'password': secret})
        assert login.status_code == 200
        assert client.get('/api/auth/me').json()['user']['username'] == name
    # 两字中文账号可通过规则校验，不依赖生产库中是否已存在同名账号。
    class CaptureSession:
        def add(self, row): self.row = row
        def flush(self): pass
    session = CaptureSession()
    assert create_user(session, '小李', '小李', secret, 'customer_service').username == '小李'

def test_six_character_password_and_parallel_sessions(api_settings, api_session_factory, fake_encoder):
    name = 'admin_' + uuid.uuid4().hex[:12]
    password = 'test06'
    with api_session_factory() as session:
        create_user(session, name, '多设备测试', password, 'admin')
        session.commit()
    app = create_app(settings=api_settings, encoder=fake_encoder, session_factory=api_session_factory)
    with TestClient(app, client=('127.0.0.1', 50000)) as first, TestClient(app, client=('127.0.0.1', 50001)) as second:
        for client in (first, second):
            assert client.post('/api/auth/admin-login', json={'username': name, 'password': password}).status_code == 200
        assert first.cookies.get(COOKIE) != second.cookies.get(COOKIE)
        assert first.get('/api/auth/me').status_code == 200
        assert second.get('/api/auth/me').status_code == 200
        assert first.post('/api/auth/logout').status_code == 200
        assert second.get('/api/auth/me').status_code == 200

def test_customer_new_login_invalidates_previous_device(api_settings, api_session_factory, fake_encoder):
    name = 'cs_' + uuid.uuid4().hex[:12]
    password = 'test-single-device'
    with api_session_factory() as session:
        create_user(session, name, '单设备测试', password, 'customer_service')
        session.commit()
    app = create_app(settings=api_settings, encoder=fake_encoder, session_factory=api_session_factory)
    with TestClient(app, client=('127.0.0.1', 50000)) as first, TestClient(app, client=('127.0.0.1', 50001)) as second:
        assert first.post('/api/auth/login', json={'username': name, 'password': password}).status_code == 200
        assert second.post('/api/auth/login', json={'username': name, 'password': 'wrong'}).status_code == 401
        assert first.get('/api/auth/me').status_code == 200
        assert second.post('/api/auth/login', json={'username': name, 'password': password}).status_code == 200
        assert first.get('/api/auth/me').status_code == 401
        assert first.post('/api/search').status_code == 401
        assert first.post('/api/auth/logout').status_code == 401
        assert second.get('/api/auth/me').status_code == 200
        assert second.post('/api/auth/logout').status_code == 200
