import asyncio
from io import BytesIO
from threading import Barrier, Event, get_ident
from types import SimpleNamespace

import httpx
from PIL import Image

from backend import api
from backend.config import Settings
from backend.encoders.base import EncoderIdentity


def test_eight_reviews_do_not_block_frontend(monkeypatch):
    barrier = Barrier(8, timeout=10)
    entered = Event()
    release = Event()
    sessions = []

    class Session:
        def __enter__(self):
            self.owner = get_ident()
            sessions.append(self)
            return self
        def __exit__(self, *args):
            assert self.owner == get_ident()
        def add(self, record): pass
        def flush(self): pass
        def commit(self): pass

    class Repository:
        def __init__(self, session): self.session = session
        def search_products(self, *args, **kwargs):
            assert self.session.owner == get_ident()
            return []

    def review(*args):
        barrier.wait()
        entered.set()
        assert release.wait(10)
        return [], {}, 0, 0

    monkeypatch.setattr(api, 'ImageRepository', Repository)
    monkeypatch.setattr(api, 'usable_scene', lambda labels: True)
    monkeypatch.setattr(api.SceneClient, 'identify', lambda *args: {})
    monkeypatch.setattr(api, 'review_conflicts', review)
    encoder = SimpleNamespace(identity=EncoderIdentity('fake', 'test', 'v1', 3), encode=lambda image: [1, 0, 0])
    app = api.create_app(settings=Settings.load(), encoder=encoder, session_factory=Session)
    data = BytesIO()
    Image.new('RGB', (8, 8)).save(data, format='PNG')

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            tasks = [asyncio.create_task(client.post('/api/search', files={'image': ('test.png', data.getvalue(), 'image/png')})) for _ in range(8)]
            try:
                assert await asyncio.to_thread(entered.wait, 12)
                response = await asyncio.wait_for(client.get('/'), 2)
                assert response.status_code == 200
            finally:
                release.set()
            results = await asyncio.gather(*tasks)
            assert all(r.status_code == 200 for r in results)
            assert len(sessions) == 16  # Eight independent queries and eight history writes.
    asyncio.run(scenario())
