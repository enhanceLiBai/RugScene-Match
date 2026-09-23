import json
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select, func

from backend.api import create_app
from backend.auth import create_user
from backend.models import MatchHistory, MatchHistoryImage, MatchConversion
from backend.repository import ImageMetadata, ImageRepository
from test_api import add_image, database_settings, database_engine, api_session_factory, api_settings, fake_encoder, png_bytes


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


def test_admin_statistics_date_filters(api_settings, api_session_factory, fake_encoder):
    from datetime import datetime, timedelta, timezone
    tz = timezone(timedelta(hours=8))
    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    password = 'test-' + uuid.uuid4().hex
    with api_session_factory() as session:
        admin = create_user(session, 'admin_' + uuid.uuid4().hex[:10], '统计管理员', password, 'admin')
        customer = create_user(session, 'cs_' + uuid.uuid4().hex[:10], '统计客服', password, 'customer_service')
        moments = [today - timedelta(days=40), today - timedelta(days=8), today - timedelta(days=6), today - timedelta(microseconds=1), today]
        histories = [MatchHistory(user_id=customer.id, created_at=t, payload_json='{"results":[]}') for t in moments]
        session.add_all(histories)
        session.flush()
        session.add(MatchConversion(history_id=histories[-2].id, rank=1, submitted_by=customer.id))
        session.commit()
        customer_id, admin_name = customer.id, admin.username
    app = create_app(settings=api_settings, encoder=fake_encoder, session_factory=api_session_factory)
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        assert client.post('/api/auth/admin-login', json={'username': admin_name, 'password': password}).status_code == 200
        def stats(period, **params):
            return client.get('/api/admin/statistics', params={'period': period, 'customer_id': customer_id, **params})
        starts = {'today': today, 'week': today - timedelta(days=today.weekday()), 'month': today.replace(day=1), '7d': today - timedelta(days=6), '30d': today - timedelta(days=29), 'all': moments[0]}
        for period, start in starts.items():
            response = stats(period)
            assert response.status_code == 200
            data = response.json()
            assert data['total_matches'] == sum(t >= start for t in moments)
            assert sum(row['matches'] for row in data['trend']) == data['total_matches']
        yesterday = (today - timedelta(days=1)).date().isoformat()
        data = stats('custom', start_date=yesterday, end_date=yesterday).json()
        assert data['total_matches'] == data['converted_matches'] == 1
        assert data['conversion_rate'] == 100
        assert data['trend'] == [{'date': yesterday, 'matches': 1, 'conversions': 1}]
        empty = (today - timedelta(days=2)).date().isoformat()
        data = stats('custom', start_date=empty, end_date=empty).json()
        assert data['total_matches'] == data['converted_matches'] == data['conversion_rate'] == 0
        assert data['trend'] == []
        assert stats('custom').status_code == 422
        assert stats('custom', start_date=today.date().isoformat(), end_date=yesterday).status_code == 422
        assert stats('custom', start_date=yesterday, end_date=(today + timedelta(days=1)).date().isoformat()).status_code == 422
        assert stats('custom', start_date='invalid', end_date=yesterday).status_code == 422


def test_admin_customer_ranking_and_history(api_settings, api_session_factory, fake_encoder):
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=0, microsecond=0)
    password = 'test-' + uuid.uuid4().hex
    with api_session_factory() as session:
        admin = create_user(session, 'admin_' + uuid.uuid4().hex[:10], '排行管理员', password, 'admin')
        first = create_user(session, 'cs_' + uuid.uuid4().hex[:10], '排行甲', password, 'customer_service')
        second = create_user(session, 'cs_' + uuid.uuid4().hex[:10], '排行乙', password, 'customer_service')
        empty = create_user(session, 'cs_' + uuid.uuid4().hex[:10], '排行空', password, 'customer_service')
        payload = {'results': [{'rank': 1, 'product_id': 'ranking-test', 'similarity': 98}]}
        rows = [MatchHistory(user_id=first.id, created_at=today, payload_json=json.dumps(payload)) for _ in range(21)]
        other = MatchHistory(user_id=second.id, created_at=today, payload_json=json.dumps(payload))
        old = MatchHistory(user_id=first.id, created_at=today - timedelta(days=10), payload_json='{"results":[]}')
        session.add_all([*rows, other, old]); session.flush()
        session.add(MatchConversion(history_id=other.id, rank=1, submitted_by=second.id))
        session.add(MatchHistoryImage(history_id=rows[-1].id, content=png_bytes(), mime_type='image/png'))
        session.commit()
        first_id, second_id, empty_id = first.id, second.id, empty.id
        first_name, admin_name, image_id, other_id = first.username, admin.username, rows[-1].id, other.id
    app = create_app(settings=api_settings, encoder=fake_encoder, session_factory=api_session_factory)
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        assert client.get('/api/admin/statistics').status_code == 401
        assert client.post('/api/auth/admin-login', json={'username': admin_name, 'password': password}).status_code == 200
        data = client.get('/api/admin/statistics', params={'period': 'today'}).json()
        ranking = {row['user']['id']: row for row in data['ranking']}
        assert ranking[first_id]['total_matches'] == 21
        assert ranking[first_id]['converted_matches'] == 0
        assert ranking[second_id]['total_matches'] == ranking[second_id]['converted_matches'] == 1
        assert ranking[second_id]['conversion_rate'] == 100
        assert ranking[empty_id]['total_matches'] == ranking[empty_id]['conversion_rate'] == 0
        params = {'period': 'custom', 'start_date': today.date().isoformat(), 'end_date': today.date().isoformat(), 'customer_id': first_id}
        personal = client.get('/api/admin/statistics', params=params).json()
        assert personal['total_matches'] == personal['history']['total'] == 21
        assert personal['converted_matches'] == 0
        assert len(personal['history']['items']) == 20
        page2 = client.get('/api/admin/statistics', params={**params, 'history_page': 2}).json()
        assert len(page2['history']['items']) == 1
        assert set(row['id'] for row in personal['history']['items']).isdisjoint(row['id'] for row in page2['history']['items'])
        assert other_id not in [row['id'] for row in personal['history']['items']]
        detail = client.get(f'/api/history/{image_id}').json()
        assert detail['user']['id'] == first_id
        assert detail['payload'] == payload
        assert client.get(detail['query_image_url']).content == png_bytes()
        second_stats = client.get('/api/admin/statistics', params={**params, 'customer_id': second_id}).json()
        assert second_stats['total_matches'] == second_stats['converted_matches'] == 1
        assert second_stats['history']['items'][0]['conversion']['rank'] == 1
        assert client.post('/api/auth/login', json={'username': first_name, 'password': password}).status_code == 200
        assert client.get('/api/admin/statistics').status_code == 403


def test_admin_product_statistics_search_dates_and_totals(api_settings, api_session_factory, fake_encoder):
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=0, microsecond=0)
    password = 'test-' + uuid.uuid4().hex
    with api_session_factory() as session:
        admin = create_user(session, 'admin_' + uuid.uuid4().hex[:10], '商品统计管理员', password, 'admin')
        customer = create_user(session, 'cs_' + uuid.uuid4().hex[:10], '商品统计客服', password, 'customer_service')
        repository = ImageRepository(session)
        first_image, _ = add_image(repository, api_settings, name='product-a-1.png')
        second_image, _ = add_image(repository, api_settings, name='product-a-2.png')
        repository.update_metadata(repository.find_by_id(first_image), ImageMetadata(product_name='云朵地毯'))
        repository.update_metadata(repository.find_by_id(second_image), ImageMetadata(product_name='云朵地毯'))
        repository.link_product_image('P-A', repository.find_by_id(first_image), 'buyer_sofa', 'L')
        repository.link_product_image('P-A', repository.find_by_id(second_image), 'buyer_sofa', 'M')
        payload_a = {'results': [{'rank': 1, 'product_id': 'P-A', 'product_name': '云朵地毯',
                                  'buyer_image_id': first_image},
                                 {'rank': 2, 'product_id': 'P-A', 'product_name': '云朵地毯',
                                  'buyer_image_id': second_image}]}
        payload_b = {'results': [{'rank': 1, 'product_id': 'P-B', 'product_name': '几何地毯'}]}
        rows = [MatchHistory(user_id=customer.id, created_at=today, payload_json=json.dumps(payload_a)),
                MatchHistory(user_id=customer.id, created_at=today, payload_json=json.dumps(payload_a)),
                MatchHistory(user_id=customer.id, created_at=today, payload_json=json.dumps(payload_b)),
                MatchHistory(user_id=customer.id, created_at=today - timedelta(days=10), payload_json=json.dumps(payload_a))]
        session.add_all(rows); session.flush()
        session.add(MatchConversion(history_id=rows[0].id, rank=1, product_id='P-A', submitted_by=customer.id))
        session.add(MatchConversion(history_id=rows[2].id, rank=1, product_id='P-B', submitted_by=customer.id))
        session.commit()
        admin_name = admin.username
    app = create_app(settings=api_settings, encoder=fake_encoder, session_factory=api_session_factory)
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        assert client.get('/api/admin/product-statistics').status_code == 401
        assert client.post('/api/auth/admin-login', json={'username': admin_name, 'password': password}).status_code == 200
        data = client.get('/api/admin/product-statistics', params={'period': '7d', 'search': 'P-A'}).json()
        assert [item['image_id'] for item in data['items']] == [first_image, second_image]
        products = {item['image_id']: item for item in data['items']}
        assert products[first_image] == {'product_id': 'P-A', 'product_name': '云朵地毯', 'buyer_images': 1,
                                         'image_id': first_image, 'image_url': f'/api/images/{first_image}',
                                         'total_matches': 2, 'converted_matches': 1, 'conversion_rate': 50}
        assert products[second_image]['total_matches'] == 2
        assert products[second_image]['converted_matches'] == 0
        from io import BytesIO
        from PIL import Image
        image_url = products[first_image]['image_url']
        preview = client.get(image_url, params={'preview': 1})
        assert preview.status_code == 200
        assert preview.headers['content-type'] == 'image/jpeg'
        with Image.open(BytesIO(preview.content)) as picture:
            picture.load()
            assert picture.width > 0 and picture.height > 0
        original = client.get(image_url)
        assert original.status_code == 200
        assert original.headers['content-type'] == 'image/png'
        without_image = client.get('/api/admin/product-statistics', params={'period': '7d', 'search': 'P-B'}).json()
        assert without_image['items'] == []
        assert data['buyer_images'] == 2
        assert data['total_matches'] == 4 and data['converted_matches'] == 1
        assert data['conversion_rate'] == 25
        searched = client.get('/api/admin/product-statistics', params={'period': 'all', 'search': '云朵'}).json()
        assert [item['image_id'] for item in searched['items']] == [first_image, second_image]
        assert searched['total_matches'] == 6 and searched['converted_matches'] == 1
        empty_day = (today - timedelta(days=2)).date().isoformat()
        empty = client.get('/api/admin/product-statistics', params={'period': 'custom', 'search': 'P-A', 'start_date': empty_day, 'end_date': empty_day}).json()
        assert empty['total_matches'] == empty['converted_matches'] == empty['conversion_rate'] == 0
        assert client.get('/api/admin/product-statistics', params={'period': 'custom'}).status_code == 422


def test_exception_listing_regression(api_settings, api_session_factory, fake_encoder):
    from backend.models import MatchException
    from datetime import datetime, timezone, timedelta
    password = uuid.uuid4().hex
    with api_session_factory() as session:
        admin = create_user(session, 'admin_' + uuid.uuid4().hex[:10], 'exception admin', password, 'admin')
        history = MatchHistory(user_id=admin.id, payload_json='{"results":[]}')
        session.add(history); session.flush()
        exception = MatchException(history_id=history.id)
        session.add(exception); session.commit()
        name, admin_id, exception_id = admin.username, admin.id, exception.id
        day = exception.created_at.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    with TestClient(create_app(settings=api_settings, encoder=fake_encoder, session_factory=api_session_factory), client=('127.0.0.1', 50000)) as client:
        assert client.post('/api/auth/admin-login', json={'username': name, 'password': password}).status_code == 200
        for params in [{'status': 'open'}, {'status': 'all', 'start_date': day, 'end_date': day}]:
            response = client.get('/api/admin/exceptions', params=params)
            assert response.status_code == 200
            assert exception_id in [row['id'] for row in response.json()['items']]
        detail = client.get(f'/api/admin/exceptions/{exception_id}')
        assert detail.status_code == 200
        assert detail.json()['query_image_url'] is None
        assert detail.json()['user']['id'] == admin_id
        assert client.post(f'/api/admin/exceptions/{exception_id}/resolve').status_code == 200
        assert exception_id not in [row['id'] for row in client.get('/api/admin/exceptions?status=open').json()['items']]
        assert exception_id in [row['id'] for row in client.get('/api/admin/exceptions?status=resolved').json()['items']]
