"""Download posters/backdrops for TMDB movies already stored in Tonight."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import ROOT, settings
from backend.database.db import db_session, initialize
from scripts.import_tmdb import IMAGE, download, request


def cache_catalog_images(limit: int | None = None) -> tuple[int, int]:
    if not settings.tmdb_read_token:
        raise RuntimeError("TMDB_READ_TOKEN не найден в .env")
    initialize()
    with db_session() as db:
        rows = db.execute(
            "SELECT id,poster_path,backdrop_path FROM movies WHERE id GLOB 'tmdb-[0-9]*' ORDER BY rating DESC"
        ).fetchall()
    if limit:
        rows = rows[:limit]

    processed = downloaded = 0
    total = len(rows)
    for row in rows:
        tmdb_id = row["id"].removeprefix("tmdb-")
        poster_file = ROOT / "data" / "posters" / f"{row['id']}.jpg"
        backdrop_file = ROOT / "data" / "backdrops" / f"{row['id']}.jpg"
        if poster_file.exists() and backdrop_file.exists():
            continue
        detail = request(f"/movie/{tmdb_id}", settings.tmdb_read_token, {"language": "ru-RU"})
        poster_ref = detail.get("poster_path")
        backdrop_ref = detail.get("backdrop_path")
        if poster_ref and not poster_file.exists():
            download(f"{IMAGE}/w500{poster_ref}", poster_file)
            downloaded += 1
        if backdrop_ref and not backdrop_file.exists():
            download(f"{IMAGE}/w1280{backdrop_ref}", backdrop_file)
            downloaded += 1
        with db_session() as db:
            db.execute(
                "UPDATE movies SET poster_path=?,backdrop_path=? WHERE id=?",
                (
                    str(poster_file) if poster_file.exists() else row["poster_path"],
                    str(backdrop_file) if backdrop_file.exists() else row["backdrop_path"],
                    row["id"],
                ),
            )
        processed += 1
        if processed % 25 == 0:
            print(f"Обработано {processed} из {total}…", flush=True)
    return processed, downloaded


def main() -> None:
    parser = argparse.ArgumentParser(description="Скачать постеры и фоны для локального каталога Tonight")
    parser.add_argument("--limit", type=int, default=0, help="Ограничить число фильмов; 0 — весь каталог")
    args = parser.parse_args()
    processed, downloaded = cache_catalog_images(args.limit or None)
    print(f"Готово: обработано {processed}, скачано файлов {downloaded}.")


if __name__ == "__main__":
    main()
