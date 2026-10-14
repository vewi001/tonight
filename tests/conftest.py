from __future__ import annotations

import os
from pathlib import Path

os.environ["TONIGHT_DB"] = "work/test-tonight.db"
os.environ["OLLAMA_TIMEOUT"] = "0.05"

import pytest

from backend.config import settings
from backend.database.db import initialize, db_session
from backend.movies.seed import seed_movies


@pytest.fixture(autouse=True)
def clean_database():
    path = settings.db_path
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(path) + suffix)
        if target.exists(): target.unlink()
    initialize()
    seed_movies()
    # Synthetic proof for the seed fixtures used by unrelated evening tests.
    # Production seed/migration NEVER invents these confirmations.
    with db_session() as db:
        db.execute('''UPDATE movies SET russian_title=title,release_status='Released',
                   theatrical_release_date=printf('%04d-01-01',year),theatrical_release_type=3,
                   theatrical_release_country='US' ''')
    yield
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(path) + suffix)
        if target.exists(): target.unlink()


@pytest.fixture(autouse=True)
def no_live_update_requests(monkeypatch):
    # Tests never query a live GitHub release or start a real update job.
    import backend.auto_update as auto
    monkeypatch.setattr(auto, "fetch_latest_update", lambda version: None)

