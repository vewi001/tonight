from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.catalog_bundle import bootstrap_catalog, build_catalog_seed, stage_catalog_bundle
from backend.database.db import connect, initialize


def _movie(database: Path, movie_id: str, *, trailer: str | None = None) -> None:
    with connect(database) as db:
        db.execute(
            """INSERT INTO movies(id,title,year,genres,runtime,rating,poster_path,backdrop_path,trailer_key,source)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (movie_id, "Каталожный фильм", 2026, '["драма"]', 100, 7.5, "old/poster.jpg", "old/backdrop.jpg", trailer, "catalog"),
        )


def test_catalog_seed_contains_movie_metadata_but_never_personal_history(tmp_path: Path):
    source = tmp_path / "source.db"
    seed = tmp_path / "catalog" / "tonight.db"
    initialize(source)
    _movie(source, "catalog-film", trailer="TRAILER0001")
    with connect(source) as db:
        db.execute("INSERT INTO sessions(session_date,title,status,access_code,created_at,updated_at) VALUES('2026-10-07','Сегодня','completed','123456','2026-10-07','2026-10-07')")
        db.execute("INSERT INTO watch_history(session_id,movie_id,watched_at) VALUES(1,'catalog-film','2026-10-07')")

    build_catalog_seed(source, seed)

    bundle = sqlite3.connect(seed)
    assert bundle.execute("SELECT trailer_key, poster_path, backdrop_path FROM movies WHERE id='catalog-film'").fetchone() == ("TRAILER0001", None, None)
    assert bundle.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    assert bundle.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert bundle.execute("SELECT COUNT(*) FROM watch_history").fetchone()[0] == 0


def test_bootstrap_enriches_existing_catalog_and_copies_media_without_deleting_user_data(tmp_path: Path):
    root = tmp_path / "portable"
    source = tmp_path / "source.db"
    seed = root / "catalog" / "tonight.db"
    database = root / "data" / "tonight.db"
    initialize(source)
    _movie(source, "catalog-film", trailer="TRAILER0001")
    build_catalog_seed(source, seed)
    (root / "catalog" / "posters").mkdir()
    (root / "catalog" / "posters" / "catalog-film.jpg").write_bytes(b"poster")
    (root / "catalog" / "backdrops").mkdir()
    (root / "catalog" / "backdrops" / "catalog-film.jpg").write_bytes(b"backdrop")
    initialize(database)
    with connect(database) as db:
        db.execute("INSERT INTO users(id,name,emoji,created_at) VALUES('custom','Пользователь','🧑','2026-10-07')")

    result = bootstrap_catalog(root, database=database)

    assert result == {"movies": 1, "media": 2}
    with connect(database) as db:
        assert tuple(db.execute("SELECT trailer_key, poster_path, backdrop_path FROM movies WHERE id='catalog-film'").fetchone()) == ("TRAILER0001", None, None)
        assert db.execute("SELECT COUNT(*) FROM users WHERE id='custom'").fetchone()[0] == 1
    assert (root / "data" / "posters" / "catalog-film.jpg").read_bytes() == b"poster"
    assert (root / "data" / "backdrops" / "catalog-film.jpg").read_bytes() == b"backdrop"


def test_bootstrap_does_not_overwrite_fresher_runtime_movie_metadata(tmp_path: Path):
    root = tmp_path / "portable"
    source = tmp_path / "source.db"
    seed = root / "catalog" / "tonight.db"
    database = root / "data" / "tonight.db"
    initialize(source)
    _movie(source, "catalog-film", trailer="BUNDLE00001")
    with connect(source) as db:
        db.execute("UPDATE movies SET release_date='2099-01-01',rating=6.0 WHERE id='catalog-film'")
    build_catalog_seed(source, seed)
    bootstrap_catalog(root, database=database)
    with connect(database) as db:
        db.execute(
            "UPDATE movies SET release_date='2026-09-01',rating=9.1,trailer_key='FRESH000001',source='tmdb' WHERE id='catalog-film'"
        )

    bootstrap_catalog(root, database=database)

    with connect(database) as db:
        movie = db.execute(
            "SELECT release_date,rating,trailer_key,source FROM movies WHERE id='catalog-film'"
        ).fetchone()
    assert tuple(movie) == ("2026-09-01", 9.1, "FRESH000001", "tmdb")


def test_stage_catalog_bundle_copies_only_catalog_and_media(tmp_path: Path):
    source_data = tmp_path / "source-data"
    source = source_data / "tonight.db"
    initialize(source)
    _movie(source, "catalog-film", trailer="TRAILER0001")
    (source_data / "posters").mkdir()
    (source_data / "posters" / "catalog-film.jpg").write_bytes(b"poster")
    (source_data / "backdrops").mkdir()
    (source_data / "backdrops" / "catalog-film.jpg").write_bytes(b"backdrop")

    result = stage_catalog_bundle(source_data, tmp_path / "portable" / "catalog")

    assert result == {"movies": 1, "media": 2}
    assert (tmp_path / "portable" / "catalog" / "posters" / "catalog-film.jpg").read_bytes() == b"poster"
    bundle = sqlite3.connect(tmp_path / "portable" / "catalog" / "tonight.db")
    assert bundle.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
