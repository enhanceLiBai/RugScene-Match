from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.access import restrict_management_access


@pytest.fixture
def access_app():
    app = FastAPI()
    app.middleware('http')(restrict_management_access)

    @app.api_route('/{path:path}', methods=['GET', 'POST', 'DELETE'])
    def reached(path: str):
        return {'reached': path}

    return app


def test_direct_local_access_and_public_block(access_app):
    for host in ['127.0.0.1', '192.168.124.20', '::1']:
        with TestClient(access_app, client=(host, 50000)) as client:
            assert client.get('/admin').status_code == 200
            assert client.get('/api/history/1/image').status_code == 200
    with TestClient(access_app, client=('8.8.8.8', 50000)) as client:
        assert client.get('/admin').status_code == 403
        assert client.get('/api/feedback').status_code == 403


def test_tunnel_blocks_management_even_when_peer_or_forwarded_ip_is_local(access_app):
    with TestClient(access_app, client=('127.0.0.1', 50000)) as client:
        headers = {'CF-Connecting-IP': '192.168.1.2', 'CF-Ray': 'test', 'X-Forwarded-For': '127.0.0.1'}
        for method, path in [('GET', '/admin'), ('GET', '/feedback'), ('GET', '/admin.js'),
                             ('GET', '/feedback.js'), ('GET', '/feedback.css'), ('GET', '/api/library'),
                             ('POST', '/api/library'), ('DELETE', '/api/library/1'),
                             ('POST', '/api/imports'), ('GET', '/api/imports/test'),
                             ('POST', '/api/scene-labels/backfill'), ('GET', '/api/history'),
                             ('GET', '/api/history/1/image'), ('GET', '/api/feedback'),
                             ('GET', '/docs'), ('GET', '/openapi.json'), ('GET', '/future-admin-api')]:
            response = client.request(method, path, headers=headers)
            assert response.status_code == 403, (method, path)
        assert client.get('/admin', headers={'X-Forwarded-For': '192.168.1.2'}).status_code == 403


def test_tunnel_customer_flow_remains_open(access_app):
    with TestClient(access_app, client=('127.0.0.1', 50000)) as client:
        headers = {'CF-Connecting-IP': '8.8.8.8', 'CF-Ray': 'test'}
        for method, path in [('GET', '/'), ('GET', '/app.js'), ('GET', '/api-client.js'),
                             ('GET', '/matcher-core.js'), ('GET', '/styles.css'),
                             ('GET', '/api/images/12?preview=1'), ('POST', '/api/search'),
                             ('POST', '/api/conversions'), ('GET', '/api/my-history'), ('GET', '/api/my-history/12/image')]:
            assert client.request(method, path, headers=headers).status_code == 200
