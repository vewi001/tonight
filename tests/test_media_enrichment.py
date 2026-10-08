from __future__ import annotations

from scripts.enrich_starter_catalog import choose_match
from backend.movies.catalog import media_url


def test_tmdb_match_prefers_exact_title_and_year():
    results = [
        {"title": "Arrival", "original_title": "Arrival", "release_date": "1956-01-01", "popularity": 99},
        {"title": "Прибытие", "original_title": "Arrival", "release_date": "2016-11-10", "popularity": 20},
    ]
    chosen = choose_match(results, "Arrival", 2016)
    assert chosen["release_date"].startswith("2016")


def test_tmdb_match_rejects_wrong_year_without_exact_title():
    results = [{"title": "Something Else", "original_title": "Different", "release_date": "1980-01-01", "popularity": 50}]
    assert choose_match(results, "Arrival", 2016) is None


def test_media_url_changes_when_real_image_appears(tmp_path):
    missing = tmp_path / "poster.jpg"
    before = media_url("arrival", "poster", str(missing))
    missing.write_bytes(b"real poster")
    after = media_url("arrival", "poster", str(missing))
    assert before != after
    assert "?v=" in after

