from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import ROOT
from backend.database.db import db_session, dumps, initialize
from backend.movies.genres import normalize_genres
from backend.movies.trailers import select_youtube_trailer

BASE = "https://api.themoviedb.org/3"
IMAGE = "https://image.tmdb.org/t/p"


def request(path: str, token: str, params: dict | None = None) -> dict:
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): return
    req = urllib.request.Request(url, headers={"User-Agent": "Tonight/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        path.write_bytes(response.read())


def download_optional(url: str, path: Path) -> bool:
    """Keep a missing or blocked image from aborting the metadata refresh."""
    try:
        download(url, path)
    except (OSError, TimeoutError):
        return False
    return path.exists()


def build_feed_candidates(
    feeds: dict[str, list[dict]], *, today: date | None = None, min_votes: int = 50,
) -> list[dict]:
    """Round-robin eligible TMDB summaries while retaining all source labels."""
    today = today or date.today()
    eligible_by_source: dict[str, list[dict]] = {}
    sources_by_id: dict[int, list[str]] = {}
    for source, items in feeds.items():
        eligible: list[dict] = []
        for item in items:
            release = item.get("release_date") or ""
            try:
                released = date.fromisoformat(release) <= today
            except ValueError:
                released = False
            if (
                item.get("adult") is True
                or not released
                or float(item.get("vote_average") or 0) <= 0
                or int(item.get("vote_count") or 0) < min_votes
            ):
                continue
            eligible.append(item)
            labels = sources_by_id.setdefault(int(item["id"]), [])
            if source not in labels:
                labels.append(source)
        eligible_by_source[source] = eligible

    output: list[dict] = []
    seen: set[int] = set()
    max_length = max((len(items) for items in eligible_by_source.values()), default=0)
    for position in range(max_length):
        for source in feeds:
            items = eligible_by_source[source]
            if position >= len(items):
                continue
            item = items[position]
            movie_id = int(item["id"])
            if movie_id in seen:
                continue
            seen.add(movie_id)
            output.append({**item, "_catalog_sources": sources_by_id[movie_id]})
    return output


def _replace_movie_id_in_sessions(db, old_id: str, new_id: str) -> None:
    rows = db.execute("SELECT id,recommendations,rejected_movies FROM sessions").fetchall()
    for row in rows:
        recommendations = json.loads(row["recommendations"] or "[]")
        rewritten: list[dict] = []
        seen: set[str] = set()
        for item in recommendations:
            if item.get("id") == old_id:
                item["id"] = new_id
            if item.get("id") not in seen:
                rewritten.append(item)
                seen.add(item.get("id"))
        rejected = [new_id if item == old_id else item for item in json.loads(row["rejected_movies"] or "[]")]
        rejected = list(dict.fromkeys(rejected))
        db.execute(
            "UPDATE sessions SET recommendations=?,rejected_movies=? WHERE id=?",
            (dumps(rewritten), dumps(rejected), row["id"]),
        )


def _merge_movie_records(db, canonical_id: str, duplicate_id: str) -> None:
    if canonical_id == duplicate_id:
        return
    db.execute("UPDATE sessions SET selected_movie_id=? WHERE selected_movie_id=?", (canonical_id, duplicate_id))
    db.execute("UPDATE watch_history SET movie_id=? WHERE movie_id=?", (canonical_id, duplicate_id))
    db.execute(
        """INSERT OR IGNORE INTO swipes(session_id,user_id,movie_id,reaction,created_at)
        SELECT session_id,user_id,?,reaction,created_at FROM swipes WHERE movie_id=?""",
        (canonical_id, duplicate_id),
    )
    db.execute("DELETE FROM swipes WHERE movie_id=?", (duplicate_id,))
    deck_rows = db.execute(
        "SELECT session_id,user_id FROM swipe_decks WHERE movie_id=?", (duplicate_id,)
    ).fetchall()
    for deck_row in deck_rows:
        canonical_exists = db.execute(
            "SELECT 1 FROM swipe_decks WHERE session_id=? AND user_id=? AND movie_id=?",
            (deck_row["session_id"], deck_row["user_id"], canonical_id),
        ).fetchone()
        if canonical_exists:
            db.execute(
                "DELETE FROM swipe_decks WHERE session_id=? AND user_id=? AND movie_id=?",
                (deck_row["session_id"], deck_row["user_id"], duplicate_id),
            )
        else:
            db.execute(
                "UPDATE swipe_decks SET movie_id=? WHERE session_id=? AND user_id=? AND movie_id=?",
                (canonical_id, deck_row["session_id"], deck_row["user_id"], duplicate_id),
            )
    db.execute(
        "INSERT OR IGNORE INTO watchlist(movie_id,saved_at) SELECT ?,saved_at FROM watchlist WHERE movie_id=?",
        (canonical_id, duplicate_id),
    )
    db.execute("DELETE FROM watchlist WHERE movie_id=?", (duplicate_id,))
    _replace_movie_id_in_sessions(db, duplicate_id, canonical_id)
    db.execute("DELETE FROM movies WHERE id=?", (duplicate_id,))


def deduplicate_existing_movies() -> int:
    """Merge legacy starter/TMDB pairs while keeping starter IDs stable."""
    initialize()
    with db_session() as db:
        pairs = db.execute(
            """SELECT starter.id canonical_id,tmdb.id duplicate_id,tmdb.tmdb_id,
            tmdb.trailer_key,tmdb.trailer_language,tmdb.trailer_checked_at,tmdb.catalog_sources
            FROM movies starter JOIN movies tmdb
              ON starter.id NOT GLOB 'tmdb-[0-9]*' AND tmdb.id GLOB 'tmdb-[0-9]*'
             AND starter.year=tmdb.year
             AND lower(COALESCE(NULLIF(starter.original_title,''),starter.title))=
                 lower(COALESCE(NULLIF(tmdb.original_title,''),tmdb.title))"""
        ).fetchall()
        for pair in pairs:
            _merge_movie_records(db, pair["canonical_id"], pair["duplicate_id"])
            db.execute(
                """UPDATE movies SET tmdb_id=?,
                trailer_key=COALESCE(trailer_key,?),trailer_language=COALESCE(trailer_language,?),
                trailer_checked_at=COALESCE(trailer_checked_at,?),catalog_sources=?,source='starter+tmdb'
                WHERE id=?""",
                (
                    pair["tmdb_id"], pair["trailer_key"], pair["trailer_language"], pair["trailer_checked_at"],
                    pair["catalog_sources"] or "[]", pair["canonical_id"],
                ),
            )
    return len(pairs)


def persist_movie(
    detail: dict,
    genre_names: dict[int, str],
    sources: list[str],
    trailer: dict[str, str] | None,
    *,
    images: bool,
) -> str:
    """Update or insert one movie without REPLACE/cascade data loss."""
    tmdb_id = int(detail["id"])
    release_date = detail["release_date"]
    year = int(release_date[:4])
    original_title = detail.get("original_title") or detail.get("title") or ""
    tmdb_movie_id = f"tmdb-{tmdb_id}"
    with db_session() as db:
        by_tmdb = db.execute("SELECT * FROM movies WHERE tmdb_id=? OR id=?", (tmdb_id, tmdb_movie_id)).fetchone()
        starter = db.execute(
            """SELECT * FROM movies WHERE id NOT GLOB 'tmdb-[0-9]*' AND year=?
            AND lower(COALESCE(NULLIF(original_title,''),title))=lower(?) ORDER BY id LIMIT 1""",
            (year, original_title),
        ).fetchone()
        canonical_id = starter["id"] if starter else (by_tmdb["id"] if by_tmdb else tmdb_movie_id)
        if starter and by_tmdb and starter["id"] != by_tmdb["id"]:
            _merge_movie_records(db, starter["id"], by_tmdb["id"])
        existing = db.execute("SELECT * FROM movies WHERE id=?", (canonical_id,)).fetchone()

    poster_file = ROOT / "data" / "posters" / f"{canonical_id}.jpg"
    backdrop_file = ROOT / "data" / "backdrops" / f"{canonical_id}.jpg"
    if images and detail.get("poster_path"):
        download_optional(f"{IMAGE}/w500{detail['poster_path']}", poster_file)
    if images and detail.get("backdrop_path"):
        download_optional(f"{IMAGE}/w1280{detail['backdrop_path']}", backdrop_file)
    poster = str(poster_file) if poster_file.exists() else (existing["poster_path"] if existing else None)
    backdrop = str(backdrop_file) if backdrop_file.exists() else (existing["backdrop_path"] if existing else None)
    genres = normalize_genres([genre_names.get(item["id"], item.get("name", "").lower()) for item in detail.get("genres", [])])
    keywords = [item["name"] for item in detail.get("keywords", {}).get("keywords", [])[:12]]
    director = next((item["name"] for item in detail.get("credits", {}).get("crew", []) if item.get("job") == "Director"), None)
    cast = [item["name"] for item in detail.get("credits", {}).get("cast", [])[:6]]
    values = (
        detail.get("title") or original_title, original_title, year, release_date, dumps(genres), detail.get("overview") or "",
        detail.get("runtime"), detail.get("vote_average"), detail.get("vote_count", 0), dumps(keywords), director,
        dumps(cast), poster, backdrop, detail.get("_franchise_key"), detail.get("_franchise_order"), tmdb_id,
        trailer.get("key") if trailer else None, trailer.get("language") if trailer else None,
        datetime.now().isoformat(timespec="seconds"), dumps(sources), "starter+tmdb" if not canonical_id.startswith("tmdb-") else "tmdb",
    )
    with db_session() as db:
        exists = db.execute("SELECT id FROM movies WHERE id=?", (canonical_id,)).fetchone()
        if exists:
            db.execute(
                """UPDATE movies SET title=?,original_title=?,year=?,release_date=?,genres=?,overview=?,runtime=?,rating=?,vote_count=?,
                keywords=?,director=?,cast_names=?,poster_path=?,backdrop_path=?,franchise_key=?,franchise_order=?,tmdb_id=?,
                trailer_key=?,trailer_language=?,trailer_checked_at=?,catalog_sources=?,source=? WHERE id=?""",
                (*values, canonical_id),
            )
        else:
            db.execute(
                """INSERT INTO movies(id,title,original_title,year,release_date,genres,overview,runtime,rating,vote_count,keywords,director,
                cast_names,poster_path,backdrop_path,franchise_key,franchise_order,tmdb_id,trailer_key,trailer_language,
                trailer_checked_at,catalog_sources,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (canonical_id, *values),
            )
    return canonical_id


def _feed_page_allocations(pages: int) -> dict[str, int]:
    sources = ("trending_week", "popular", "top_rated")
    total = max(len(sources), pages)
    base, remainder = divmod(total, len(sources))
    return {source: base + (1 if index < remainder else 0) for index, source in enumerate(sources)}


def _load_feed(token: str, path: str, pages: int) -> list[dict]:
    items: list[dict] = []
    for page in range(1, pages + 1):
        items.extend(request(path, token, {"language": "ru-RU", "page": page}).get("results", []))
    return items


def _enrich_and_persist(
    token: str, candidates: list[dict], genre_names: dict[int, str], *, images: bool, min_votes: int, today: date,
) -> int:
    collections: dict[int, dict[int, int]] = {}
    imported = 0
    for summary in candidates:
        detail = request(
            f"/movie/{summary['id']}", token,
            {"language": "ru-RU", "append_to_response": "keywords,credits,videos"},
        )
        release = detail.get("release_date") or ""
        try:
            released = date.fromisoformat(release) <= today
        except ValueError:
            released = False
        if (
            detail.get("adult") is True or not released or not detail.get("runtime")
            or float(detail.get("vote_average") or 0) <= 0
            or int(detail.get("vote_count") or 0) < min_votes
        ):
            continue
        collection = detail.get("belongs_to_collection") or {}
        collection_id = collection.get("id")
        if collection_id:
            if collection_id not in collections:
                collection_detail = request(f"/collection/{collection_id}", token, {"language": "ru-RU"})
                collections[collection_id] = {
                    part["id"]: position
                    for position, part in enumerate(
                        sorted(collection_detail.get("parts", []), key=lambda part: (part.get("release_date") or "9999-99-99", part["id"])),
                        start=1,
                    )
                }
            detail["_franchise_key"] = f"tmdb-collection-{collection_id}"
            detail["_franchise_order"] = collections[collection_id].get(detail["id"])
        russian_videos = detail.get("videos", {}).get("results", [])
        trailer = select_youtube_trailer(russian_videos, [])
        if not trailer:
            try:
                english_videos = request(f"/movie/{detail['id']}/videos", token, {"language": "en-US"}).get("results", [])
            except Exception:
                english_videos = []
            trailer = select_youtube_trailer(russian_videos, english_videos)
        persist_movie(detail, genre_names, summary.get("_catalog_sources", []), trailer, images=images)
        imported += 1
        time.sleep(.05)
    return imported


def import_smart_catalog(
    token: str, pages: int = 25, images: bool = False, min_votes: int = 50, today: date | None = None,
) -> int:
    initialize()
    deduplicate_existing_movies()
    today = today or date.today()
    genres_data = request("/genre/movie/list", token, {"language": "ru-RU"})
    genre_names = {item["id"]: item["name"].lower() for item in genres_data.get("genres", [])}
    allocations = _feed_page_allocations(pages)
    feeds = {
        "trending_week": _load_feed(token, "/trending/movie/week", allocations["trending_week"]),
        "popular": _load_feed(token, "/movie/popular", allocations["popular"]),
        "top_rated": _load_feed(token, "/movie/top_rated", allocations["top_rated"]),
    }
    candidates = build_feed_candidates(feeds, today=today, min_votes=min_votes)
    return _enrich_and_persist(token, candidates, genre_names, images=images, min_votes=min_votes, today=today)


def backfill_trailers(token: str) -> int:
    """Cache a trailer decision for existing TMDB rows exactly once per backfill."""
    initialize()
    with db_session() as db:
        rows = db.execute(
            "SELECT id,tmdb_id FROM movies WHERE tmdb_id IS NOT NULL AND trailer_checked_at IS NULL ORDER BY rating DESC"
        ).fetchall()
    checked = 0
    for row in rows:
        russian = request(f"/movie/{row['tmdb_id']}/videos", token, {"language": "ru-RU"}).get("results", [])
        selected = select_youtube_trailer(russian, [])
        english: list[dict] = []
        if not selected:
            english = request(f"/movie/{row['tmdb_id']}/videos", token, {"language": "en-US"}).get("results", [])
            selected = select_youtube_trailer(russian, english)
        with db_session() as db:
            db.execute(
                "UPDATE movies SET trailer_key=?,trailer_language=?,trailer_checked_at=? WHERE id=?",
                (
                    selected.get("key") if selected else None,
                    selected.get("language") if selected else None,
                    datetime.now().isoformat(timespec="seconds"),
                    row["id"],
                ),
            )
        checked += 1
    return checked


def import_catalog(token: str, pages: int = 10, list_name: str = "top_rated", images: bool = False) -> int:
    if list_name == "smart":
        return import_smart_catalog(token, pages=pages, images=images)
    if list_name not in {"popular", "top_rated", "now_playing"}:
        raise ValueError("unknown TMDB catalog list")
    initialize()
    today = date.today()
    genres_data = request("/genre/movie/list", token, {"language": "ru-RU"})
    genre_names = {item["id"]: item["name"].lower() for item in genres_data.get("genres", [])}
    source = list_name
    summaries = _load_feed(token, f"/movie/{list_name}", max(1, pages))
    candidates = build_feed_candidates({source: summaries}, today=today, min_votes=50)
    return _enrich_and_persist(token, candidates, genre_names, images=images, min_votes=50, today=today)


def main() -> None:
    parser = argparse.ArgumentParser(description="Импорт легальных метаданных TMDB в локальный Tonight")
    parser.add_argument("--pages", type=int, default=10, help="Число страниц каталога, по 20 на странице")
    parser.add_argument("--list", choices=("smart", "popular", "top_rated", "now_playing"), default="smart", help="Какой актуальный список TMDB кэшировать локально")
    parser.add_argument("--images", action="store_true", help="Скачать постеры и фоны в локальный кэш")
    args = parser.parse_args()
    token = os.getenv("TMDB_READ_TOKEN")
    if not token:
        raise SystemExit("Задайте бесплатный TMDB_READ_TOKEN. Инструкция есть в README.md")
    imported = import_catalog(token, args.pages, args.list, args.images)
    print(f"\nГотово. Добавлено или обновлено: {imported}")
    print("This product uses the TMDB API but is not endorsed or certified by TMDB.")


if __name__ == "__main__": main()
