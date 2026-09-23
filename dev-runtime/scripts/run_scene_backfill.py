import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import Settings
from backend.db import create_session_factory, dispose_session_factory
from backend.scene import SceneClient, backfill
from backend.repository import ImageRepository

settings = Settings.load()
factory = create_session_factory(settings)
try:
    job_id = "manual-scene-backfill"
    with factory() as session:
        ImageRepository(session).create_import_job(job_id, "场景标签回填")
        session.commit()
    print(backfill(settings, factory, SceneClient(settings.project_root), job_id), flush=True)
finally:
    dispose_session_factory(factory)
