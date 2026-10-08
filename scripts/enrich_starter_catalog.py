from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import ROOT
from backend.database.db import db_session, initialize

API = "https://api.themoviedb.org/3"
IMAGE = "https://image.tmdb.org/t/p"


def request(path: str, token: str, params: dict | None = None) -> dict:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "accept": "application/json", "User-Agent": "Tonight/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def choose_match(results: list[dict], original_title: str, year: int) -> dict | None:
    if not results:
        return None
    target = original_title.casefold().strip()

    def score(item: dict) -> tuple[int, float]:
        release = item.get("release_date") or ""
        item_year = int(release[:4]) if len(release) >= 4 and release[:4].isdigit() else 0
        titles = {str(item.get("title") or "").casefold(), str(item.get("original_title") or "").casefold()}
        exact = 3 if target in titles else 0
        year_score = 2 if item_year == year else 1 if abs(item_year - year) <= 1 else 0
        return exact + year_score, float(item.get("popularity") or 0)

    best = max(results, key=score)
    return best if score(best)[0] >= 2 else None


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Tonight/1.0"})
    with urllib.request.urlopen(req, timeout=35) as response:
        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            raise ValueError(f"Expected image, got {content_type}")
        temp.write_bytes(response.read())
    temp.replace(path)


def enrich(token: str, limit: int | None = None) -> tuple[int, int]:
    initialize()
    with db_session() as db:
        rows = db.execute("SELECT id,title,original_title,year FROM movies WHERE source='starter' ORDER BY title").fetchall()
    matched = downloaded = 0
    for index, movie in enumerate(rows):
        if limit is not None and index >= limit:
            break
        data = request("/search/movie", token, {"query": movie["original_title"] or movie["title"], "year": movie["year"], "language": "ru-RU"})
        match = choose_match(data.get("results", []), movie["original_title"] or movie["title"], movie["year"])
        if not match:
            print(f"○ Не найдено: {movie['title']}")
            continue
        matched += 1
        poster_path = ROOT / "data" / "posters" / f"{movie['id']}.jpg"
        backdrop_path = ROOT / "data" / "backdrops" / f"{movie['id']}.jpg"
        poster_ref = match.get("poster_path")
        backdrop_ref = match.get("backdrop_path")
        try:
            if poster_ref and not poster_path.exists():
                download(f"{IMAGE}/w500{poster_ref}", poster_path)
                downloaded += 1
            if backdrop_ref and not backdrop_path.exists():
                download(f"{IMAGE}/w1280{backdrop_ref}", backdrop_path)
                downloaded += 1
            with db_session() as db:
                db.execute(
                    "UPDATE movies SET poster_path=?,backdrop_path=?,source='starter+tmdb' WHERE id=?",
                    (str(poster_path) if poster_path.exists() else None, str(backdrop_path) if backdrop_path.exists() else None, movie["id"]),
                )
            print(f"✓ {movie['title']}")
        except (OSError, ValueError) as exc:
            print(f"! {movie['title']}: {exc}")
        time.sleep(.08)
    return matched, downloaded


def main() -> None:
    parser = argparse.ArgumentParser(description="Добавить настоящие постеры и фоны к starter-каталогу Tonight")
    parser.add_argument("--limit", type=int, help="Обработать только первые N фильмов")
    args = parser.parse_args()
    token = os.getenv("TMDB_READ_TOKEN")
    if not token:
        raise SystemExit("Не задан TMDB_READ_TOKEN. Смотрите раздел «Постеры» в README.md")
    matched, downloaded = enrich(token, args.limit)
    print(f"\nГотово: совпадений {matched}, новых файлов {downloaded}.")
    print("Важно: бесплатный developer API TMDB предназначен только для некоммерческого использования.")
    print("Перед монетизацией получите письменное коммерческое соглашение TMDB или замените провайдера.")


if __name__ == "__main__":
    main()

