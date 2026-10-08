from __future__ import annotations

import os
from pathlib import Path

os.environ["TONIGHT_DB"] = "work/test-tonight.db"
os.environ["OLLAMA_TIMEOUT"] = "0.05"

import pytest

from backend.config import settings
from backend.database.db import initialize
from backend.movies.seed import seed_movies


@pytest.fixture(autouse=True)
def clean_database():
    path = settings.db_path
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(path) + suffix)
        if target.exists(): target.unlink()
    initialize()
    seed_movies()
    yield
    for suffix in ("", "-wal", "-shm"):
        target = Path(str(path) + suffix)
        if target.exists(): target.unlink()

