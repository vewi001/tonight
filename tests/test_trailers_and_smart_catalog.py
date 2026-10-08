from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.database.db import db_session, dumps, initialize
from backend.main import app
from backend.movies.trailers import select_youtube_trailer, trailer_url
from backend.movies import catalog_sync
from scripts import import_tmdb
from scripts.import_tmdb import backfill_trailers, build_feed_candidates, deduplicate_existing_movies, import_smart_catalog, persist_movie


ROOT = Path(__file__).resolve().parents[1]


def video(key: str, language: str, *, official: bool = False, kind: str = "Trailer", site: str = "YouTube") -> dict:
    return {"key": key, "iso_639_1": language, "official": official, "type": kind, "site": site, "name": "Trailer"}


def test_russian_trailer_wins_over_official_english_trailer():
    selected = select_youtube_trailer(
        [video("RUSSIAN0001", "ru", official=False)],
        [video("ENGLISH0001", "en", official=True)],
    )
    assert selected == {"key": "RUSSIAN0001", "language": "ru"}


def test_trailer_selector_rejects_non_youtube_and_invalid_keys():
    selected = select_youtube_trailer(
        [video("not safe!", "ru"), video("VIMEOVID001", "ru", site="Vimeo")],
        [video("ENGLISH0001", "en", official=True)],
    )
    assert selected == {"key": "ENGLISH0001", "language": "en"}
    assert trailer_url("not safe!") is None
    assert trailer_url("ENGLISH0001") == "https://www.youtube.com/watch?v=ENGLISH0001"


def test_smart_feed_round_robins_sources_deduplicates_and_filters():
    feeds = {
        "trending_week": [
            {"id": 1, "adult": False, "release_date": "2024-01-01", "vote_average": 7.5, "vote_count": 500},
            {"id": 2, "adult": True, "release_date": "2024-01-01", "vote_average": 8.0, "vote_count": 900},
        ],
        "popular": [
            {"id": 3, "adult": False, "release_date": "2023-01-01", "vote_average": 7.0, "vote_count": 300},
            {"id": 1, "adult": False, "release_date": "2024-01-01", "vote_average": 7.5, "vote_count": 500},
            {"id": 4, "adult": False, "release_date": "2027-01-01", "vote_average": 8.0, "vote_count": 500},
        ],
        "top_rated": [
            {"id": 5, "adult": False, "release_date": "1999-01-01", "vote_average": 8.7, "vote_count": 5000},
            {"id": 6, "adult": False, "release_date": "2020-01-01", "vote_average": 0.0, "vote_count": 0},
        ],
    }
    candidates = build_feed_candidates(feeds, today=date(2026, 10, 6), min_votes=50)
    assert [item["id"] for item in candidates] == [1, 3, 5]
    assert candidates[0]["_catalog_sources"] == ["trending_week", "popular"]


def test_existing_database_migrates_trailer_fields_without_data_loss(tmp_path):
    path = tmp_path / "legacy.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE movies (id TEXT PRIMARY KEY,title TEXT NOT NULL,original_title TEXT,year INTEGER NOT NULL,genres TEXT NOT NULL,overview TEXT,runtime INTEGER,rating REAL,vote_count INTEGER DEFAULT 0,keywords TEXT DEFAULT '[]',director TEXT,cast_names TEXT DEFAULT '[]',poster_path TEXT,backdrop_path TEXT,franchise_key TEXT,franchise_order INTEGER,source TEXT DEFAULT 'starter')")
    db.execute("INSERT INTO movies(id,title,year,genres) VALUES('legacy','Старый фильм',2001,'[]')")
    db.commit()
    db.close()

    initialize(path)

    db = sqlite3.connect(path)
    columns = {row[1] for row in db.execute("PRAGMA table_info(movies)")}
    title = db.execute("SELECT title FROM movies WHERE id='legacy'").fetchone()[0]
    db.close()
    assert {"tmdb_id", "trailer_key", "trailer_language", "trailer_checked_at", "catalog_sources", "release_date"} <= columns
    assert title == "Старый фильм"


def _summary(movie_id: int, *, title: str) -> dict:
    return {"id": movie_id, "title": title, "adult": False, "release_date": "2024-01-01", "vote_average": 7.5, "vote_count": 500}


def _detail(movie_id: int, *, title: str, trailer: str | None = None) -> dict:
    videos = [video(trailer, "ru", official=True)] if trailer else []
    return {
        "id": movie_id, "title": title, "original_title": title, "adult": False,
        "release_date": "2024-01-01", "runtime": 105, "vote_average": 7.5, "vote_count": 500,
        "genres": [{"id": 18, "name": "Drama"}], "overview": "Описание", "poster_path": None,
        "backdrop_path": None, "keywords": {"keywords": []}, "credits": {"crew": [], "cast": []},
        "videos": {"results": videos}, "belongs_to_collection": None,
    }


def test_smart_import_uses_all_feeds_and_caches_trailers(monkeypatch):
    summaries = {
        "/trending/movie/week": [_summary(910001, title="Trend")],
        "/movie/popular": [_summary(910002, title="Popular")],
        "/movie/top_rated": [_summary(910003, title="Classic")],
    }

    def fake_request(path, token, params=None):
        if path == "/genre/movie/list":
            return {"genres": [{"id": 18, "name": "драма"}]}
        if path in summaries:
            return {"results": summaries[path]}
        if path.startswith("/movie/") and path.endswith("/videos"):
            return {"results": []}
        movie_id = int(path.rsplit("/", 1)[-1])
        return _detail(movie_id, title={910001: "Trend", 910002: "Popular", 910003: "Classic"}[movie_id], trailer="TRAILER0001" if movie_id == 910001 else None)

    monkeypatch.setattr(import_tmdb, "request", fake_request)
    imported = import_smart_catalog("secret", pages=3, images=False, min_votes=50, today=date(2026, 10, 6))
    assert imported == 3
    with db_session() as db:
        rows = db.execute("SELECT tmdb_id,catalog_sources,trailer_key,release_date FROM movies WHERE tmdb_id>=910001 ORDER BY tmdb_id").fetchall()
    assert [row["tmdb_id"] for row in rows] == [910001, 910002, 910003]
    assert rows[0]["trailer_key"] == "TRAILER0001"
    assert rows[0]["release_date"] == "2024-01-01"
    assert loads_json(rows[0]["catalog_sources"]) == ["trending_week"]


def test_trailer_backfill_caches_english_fallback_and_does_not_repeat(monkeypatch):
    with db_session() as db:
        db.execute("UPDATE movies SET tmdb_id=940001 WHERE id='arrival'")

    calls = []

    def fake_request(path, token, params=None):
        calls.append(params["language"])
        if params["language"] == "ru-RU":
            return {"results": []}
        return {"results": [video("ENGLISH0001", "en", official=True)]}

    monkeypatch.setattr(import_tmdb, "request", fake_request)
    assert backfill_trailers("secret") == 1
    with db_session() as db:
        row = db.execute(
            "SELECT trailer_key,trailer_language,trailer_checked_at FROM movies WHERE id='arrival'"
        ).fetchone()
    assert calls == ["ru-RU", "en-US"]
    assert (row["trailer_key"], row["trailer_language"]) == ("ENGLISH0001", "en")
    assert row["trailer_checked_at"]

    monkeypatch.setattr(
        import_tmdb, "request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("repeated")),
    )
    assert backfill_trailers("secret") == 0


def test_broken_tmdb_image_does_not_abort_movie_metadata_import(monkeypatch):
    detail = _detail(950001, title="Metadata Survives")
    detail["poster_path"] = "/forbidden-poster.jpg"
    detail["backdrop_path"] = "/forbidden-backdrop.jpg"
    monkeypatch.setattr(
        import_tmdb, "download", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("403")),
    )

    movie_id = persist_movie(detail, {18: "драма"}, ["popular"], None, images=True)

    with db_session() as db:
        row = db.execute("SELECT title,poster_path,backdrop_path FROM movies WHERE id=?", (movie_id,)).fetchone()
    assert row["title"] == "Metadata Survives"
    assert row["poster_path"] is None
    assert row["backdrop_path"] is None


def loads_json(value: str) -> list[str]:
    import json
    return json.loads(value)


def test_persist_movie_merges_existing_tmdb_duplicate_into_starter_without_losing_history():
    with db_session() as db:
        db.execute("INSERT INTO movies(id,title,original_title,year,genres,rating,vote_count,source) VALUES('canonical','Same Film','Same Film',2024,'[]',7,100,'starter')")
        db.execute("INSERT INTO movies(id,title,original_title,year,genres,rating,vote_count,tmdb_id,source) VALUES('tmdb-920001','Same Film','Same Film',2024,'[]',7,100,920001,'tmdb')")
        now = "2026-10-06T12:00:00"
        sid = db.execute("INSERT INTO sessions(session_date,title,status,created_at,updated_at) VALUES('2026-10-06','test','completed',?,?)", (now, now)).lastrowid
        db.execute("INSERT INTO watch_history(session_id,movie_id,watched_at) VALUES(?,?,?)", (sid, "tmdb-920001", now))
        db.execute("INSERT INTO watchlist(movie_id,saved_at) VALUES(?,?)", ("tmdb-920001", now))

    persist_movie(
        _detail(920001, title="Same Film"), {18: "драма"}, ["top_rated"], None, images=False,
    )

    with db_session() as db:
        movies = db.execute("SELECT id,tmdb_id FROM movies WHERE tmdb_id=920001 OR id IN ('canonical','tmdb-920001')").fetchall()
        history_movie = db.execute("SELECT movie_id FROM watch_history WHERE session_id=?", (sid,)).fetchone()[0]
        watchlist_movie = db.execute("SELECT movie_id FROM watchlist").fetchone()[0]
    assert [(row["id"], row["tmdb_id"]) for row in movies] == [("canonical", 920001)]
    assert history_movie == "canonical"
    assert watchlist_movie == "canonical"


def test_legacy_deduplication_preserves_swipe_deck_position():
    with db_session() as db:
        db.execute("INSERT INTO movies(id,title,original_title,year,genres,rating,vote_count,source) VALUES('stable','Duplicate','Duplicate',2024,'[]',7,100,'starter')")
        db.execute("INSERT INTO movies(id,title,original_title,year,genres,rating,vote_count,tmdb_id,source) VALUES('tmdb-930001','Duplicate','Duplicate',2024,'[]',7,100,930001,'tmdb')")
        now = "2026-10-06T12:00:00"
        sid = db.execute("INSERT INTO sessions(session_date,title,status,created_at,updated_at) VALUES('2026-10-06','test','choosing',?,?)", (now, now)).lastrowid
        db.execute("INSERT INTO participants(session_id,user_id,joined_at) VALUES(?,?,?)", (sid, "lera", now))
        db.execute("INSERT INTO swipe_decks(session_id,user_id,movie_id,position) VALUES(?,?,?,?)", (sid, "lera", "tmdb-930001", 7))
    assert deduplicate_existing_movies() == 1
    with db_session() as db:
        deck = db.execute("SELECT movie_id,position FROM swipe_decks WHERE session_id=?", (sid,)).fetchone()
        duplicate = db.execute("SELECT 1 FROM movies WHERE id='tmdb-930001'").fetchone()
    assert (deck["movie_id"], deck["position"]) == ("stable", 7)
    assert duplicate is None


def test_weekly_sync_uses_smart_catalog_and_records_success(monkeypatch):
    monkeypatch.setattr(catalog_sync, "settings", SimpleNamespace(
        tmdb_read_token="present", catalog_auto_update=True, catalog_refresh_days=7,
        catalog_pages=12, catalog_images=True, catalog_min_votes=75,
    ))
    captured = {}

    def fake_import(token, **kwargs):
        captured.update(token=token, **kwargs)
        return 42

    monkeypatch.setattr(import_tmdb, "import_smart_catalog", fake_import)
    monkeypatch.setattr(import_tmdb, "import_catalog", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy importer used")))
    assert catalog_sync.refresh_catalog_if_due() == 42
    status = catalog_sync.sync_status()
    assert status["last_sync_at"]
    assert status["last_error"] is None
    assert captured == {"token": "present", "pages": 12, "images": True, "min_votes": 75}


def test_failed_weekly_sync_keeps_previous_success_timestamp(monkeypatch):
    previous = "2026-09-28T12:00:00"
    with db_session() as db:
        db.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('tmdb_catalog_sync_at',?)", (previous,))
    monkeypatch.setattr(catalog_sync, "settings", SimpleNamespace(
        tmdb_read_token="present", catalog_auto_update=True, catalog_refresh_days=7,
        catalog_pages=12, catalog_images=True, catalog_min_votes=75,
    ))
    monkeypatch.setattr(catalog_sync, "_needs_refresh", lambda last: True)
    monkeypatch.setattr(import_tmdb, "import_smart_catalog", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(import_tmdb, "import_catalog", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))
    assert catalog_sync.refresh_catalog_if_due() == 0
    status = catalog_sync.sync_status()
    assert status["last_sync_at"] == previous
    assert status["last_error"] == "OSError"


def test_movie_payload_contains_only_valid_cached_trailer_url():
    with db_session() as db:
        db.execute("UPDATE movies SET trailer_key='TRAILER0001',trailer_language='ru' WHERE id='arrival'")
    from backend.movies.catalog import get_movie
    assert get_movie("arrival")["trailer_url"] == "https://www.youtube.com/watch?v=TRAILER0001"
    with db_session() as db:
        db.execute("UPDATE movies SET trailer_key='javascript:bad' WHERE id='arrival'")
    assert get_movie("arrival")["trailer_url"] is None


def test_search_cards_offer_a_trailer_when_the_catalog_has_one():
    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    search_source = source[source.index("function renderSearch()"):source.index("function renderTaste()")]
    assert "${trailerButton(movie, 'button secondary')}" in search_source


def test_api_watchlist_to_watched_and_two_ratings_keeps_trailer():
    with db_session() as db:
        db.execute(
            "UPDATE movies SET trailer_key='TRAILER0001',trailer_language='ru' WHERE id='arrival'"
        )
    client = TestClient(app)
    session = client.post("/api/sessions/new").json()

    saved = client.post("/api/watchlist/arrival")
    assert saved.status_code == 200
    selected = client.post(f"/api/sessions/{session['id']}/select-saved/arrival")
    assert selected.status_code == 200
    assert selected.json()["trailer_url"] == "https://www.youtube.com/watch?v=TRAILER0001"

    watched = client.post(f"/api/sessions/{session['id']}/watched")
    assert watched.status_code == 200
    history_id = watched.json()["history_id"]
    assert client.post(
        f"/api/history/{history_id}/feedback", json={"user_id": "lera", "rating": 5}
    ).status_code == 200
    assert client.post(
        f"/api/history/{history_id}/feedback", json={"user_id": "nikita", "rating": 4}
    ).status_code == 200

    history = client.get("/api/history").json()["items"]
    assert history[0]["movie"]["id"] == "arrival"
    assert history[0]["movie"]["trailer_url"] == "https://www.youtube.com/watch?v=TRAILER0001"
    assert history[0]["ratings"] == {"lera": 5, "nikita": 4}
    assert client.get("/api/watchlist").json()["items"] == []
