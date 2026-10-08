from __future__ import annotations

from datetime import datetime

from backend.database.db import db_session, dumps
from backend.recommendation.engine import compatibility_score, recommend
from backend.movies.catalog import search_movies
from backend.sessions.service import get_deck


def make_session(disliked_lera=None, disliked_nikita=None) -> int:
    now = datetime.now().isoformat()
    with db_session() as db:
        cur = db.execute("INSERT INTO sessions(session_date,title,status,created_at,updated_at) VALUES('2026-10-02','test','choosing',?,?)", (now, now))
        sid = cur.lastrowid
        for user, disliked in (("lera", disliked_lera or []), ("nikita", disliked_nikita or [])):
            db.execute("""INSERT INTO participants(session_id,user_id,moods,energy,disliked_genres,joined_at,ready)
            VALUES(?,?,?,?,?,?,1)""", (sid, user, dumps(["surprise"]), "medium", dumps(disliked), now))
    return sid


def test_balanced_pair_beats_high_disagreement():
    balanced = compatibility_score(.80, .80)
    split = compatibility_score(1.0, .30)
    assert balanced > split


def test_strong_dislike_cannot_be_rescued_by_other_person():
    painful = compatibility_score(1.0, .05)
    merely_good = compatibility_score(.72, .72)
    assert merely_good > painful
    assert painful < .25


def test_hard_genre_exclusion_applies_to_both_people():
    sid = make_session(disliked_lera=["хоррор"])
    results = recommend(sid, 40)
    assert results
    assert all("хоррор" not in movie["genres"] for movie in results)


def test_recommendation_has_two_plain_reasons_and_confirms_stop_genres():
    sid = make_session(disliked_lera=["хоррор"], disliked_nikita=["sci-fi"])
    results = recommend(sid, 10)

    assert results
    forbidden_words = {"fairness", "score", "penalty", "прогноз"}
    for movie in results:
        assert movie["stop_genres_respected"] is True
        assert len(movie["plain_reasons"]) == 2
        assert all(reason and len(reason) <= 140 for reason in movie["plain_reasons"])
        assert not any(word in " ".join(movie["plain_reasons"]).lower() for word in forbidden_words)
        assert not {"хоррор", "sci-fi"}.intersection(movie["genres"])


def test_scifi_alias_is_a_hard_exclusion_in_results_and_swipe_deck():
    sid = make_session(disliked_lera=["фантастика"])
    results = recommend(sid, 40)
    deck, total = get_deck(sid, "lera")
    assert results and deck and total == len(deck)
    assert all("sci-fi" not in movie["genres"] for movie in results)
    assert all("sci-fi" not in movie["genres"] for movie in deck)


def test_runtime_uses_stricter_limit():
    sid = make_session()
    with db_session() as db:
        db.execute("UPDATE participants SET max_runtime=90 WHERE session_id=? AND user_id='lera'", (sid,))
        db.execute("UPDATE participants SET max_runtime=150 WHERE session_id=? AND user_id='nikita'", (sid,))
    results = recommend(sid, 40)
    assert results
    assert all(movie["runtime"] <= 90 for movie in results)


def test_empty_year_and_runtime_intersection_relaxes_only_those_constraints():
    sid = make_session(disliked_lera=["sci-fi"])
    with db_session() as db:
        db.execute("UPDATE participants SET max_runtime=40,min_year=2025 WHERE session_id=?", (sid,))
    results = recommend(sid, 40)
    assert results
    assert all("sci-fi" not in movie["genres"] for movie in results)
    assert results[0]["relaxed_constraints"] == ["длительность", "эпоха"]


def test_sequel_is_hidden_until_every_previous_part_is_watched():
    sid = make_session()
    with db_session() as db:
        db.execute("UPDATE movies SET franchise_key='test-series',franchise_order=1 WHERE id='arrival'")
        db.execute("UPDATE movies SET franchise_key='test-series',franchise_order=2 WHERE id='ex-machina'")

    before = recommend(sid, 100)
    assert "ex-machina" not in {movie["id"] for movie in before}

    now = datetime.now().isoformat()
    with db_session() as db:
        db.execute("INSERT INTO watch_history(session_id,movie_id,watched_at) VALUES(?,?,?)", (sid, "arrival", now))

    after = recommend(sid, 100)
    assert "ex-machina" in {movie["id"] for movie in after}


def test_unreleased_or_unrated_movies_are_not_recommended_or_swiped():
    sid = make_session()
    with db_session() as db:
        db.execute("UPDATE movies SET rating=0,vote_count=0 WHERE id='arrival'")
    results = recommend(sid, 100)
    deck, _ = get_deck(sid, "lera")
    assert "arrival" not in {movie["id"] for movie in results}
    assert "arrival" not in {movie["id"] for movie in deck}


def test_future_official_release_is_excluded_from_all_discovery_paths():
    sid = make_session()
    with db_session() as db:
        db.execute("UPDATE movies SET release_date='2099-01-01' WHERE id='arrival'")

    results = recommend(sid, 100)
    deck, _ = get_deck(sid, "lera")

    assert "arrival" not in {movie["id"] for movie in results}
    assert "arrival" not in {movie["id"] for movie in deck}
    assert "arrival" not in {movie["id"] for movie in search_movies("инопланетяне")}


def test_catalog_search_finds_a_title_and_local_keywords():
    assert search_movies("как Достать ножи")[0]["id"] == "knives-out"
    assert any(movie["id"] == "arrival" for movie in search_movies("инопланетяне"))
