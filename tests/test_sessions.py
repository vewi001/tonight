from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.database.db import db_session, dumps
from backend.main import app
from backend.models.schemas import PreferencesIn
from backend.recommendation.engine import recommend
from backend.sessions.service import (
    active_session, both_ready, choose_catalog_movie, choose_movie, choose_saved_movie, choose_specific_recommendation, confirm_watched, decline_selected_movie, ensure_participant,
    get_deck, save_preferences, save_swipe, session_state, store_recommendations,
    remove_saved_movie, save_movie_for_later, saved_movies,
)


def test_session_survives_new_database_connection():
    session = active_session(create=True)
    ensure_participant(session["id"], "lera")
    save_preferences(session["id"], PreferencesIn(user_id="lera", moods=["cozy"], energy="low", max_runtime=120, min_year=2000, disliked_genres=["хоррор"]))
    restored = session_state(session["id"])
    assert restored["participants"]["lera"]["joined"] is True
    assert restored["participants"]["lera"]["moods"] == ["cozy"]
    assert restored["participants"]["lera"]["energy"] == "low"


def test_preferences_normalize_scifi_aliases():
    payload = PreferencesIn(user_id="nikita", moods=["smart"], energy="high", disliked_genres=["SciFi", "фантастика", "sci‑fi"])
    assert payload.disliked_genres == ["sci-fi"]


def test_preferences_accept_every_mood_shown_in_the_interface():
    payload = PreferencesIn(
        user_id="lera",
        moods=["laugh", "smart", "scary", "emotional", "cozy", "action", "mystery", "wow", "romance", "atmosphere", "surprise"],
        energy="medium",
    )
    assert len(payload.moods) == 11


def test_swipe_deck_is_a_stable_twenty_card_snapshot():
    session = active_session(create=True)
    sid = session["id"]
    ensure_participant(sid, "lera")
    save_preferences(sid, PreferencesIn(user_id="lera", moods=["cozy"], energy="medium", max_runtime=None, min_year=None, disliked_genres=[]))

    deck, total = get_deck(sid, "lera")
    assert total >= 20
    assert len(deck) >= 20
    first_id = deck[0]["id"]

    # Simulate an in-flight catalog refresh changing what a fresh query would
    # return. The card already shown must still be accepted.
    with db_session() as db:
        db.execute("UPDATE movies SET rating=1 WHERE id=?", (deck[-1]["id"],))
    progress = save_swipe(sid, "lera", first_id, "like")
    remaining, same_total = get_deck(sid, "lera")
    assert progress["total"] == total == same_total
    assert len(remaining) == len(deck) - 1


def test_legacy_eight_card_deck_is_extended_to_twenty_without_losing_order():
    sid = active_session(create=True)["id"]
    ensure_participant(sid, "lera")
    save_preferences(sid, PreferencesIn(user_id="lera", moods=["cozy"], energy="medium", max_runtime=None, min_year=None, disliked_genres=[]))
    full_deck, _ = get_deck(sid, "lera")
    original_eight = full_deck[:8]
    with db_session() as db:
        db.execute("DELETE FROM swipe_decks WHERE session_id=? AND user_id='lera'", (sid,))
        db.executemany(
            "INSERT INTO swipe_decks(session_id,user_id,movie_id,position) VALUES(?,?,?,?)",
            [(sid, "lera", movie["id"], position) for position, movie in enumerate(original_eight)],
        )
    extended, total = get_deck(sid, "lera")
    assert total >= 20 and len(extended) >= 20
    assert [movie["id"] for movie in extended[:8]] == [movie["id"] for movie in original_eight]


def test_two_people_can_complete_a_full_evening_without_card_errors():
    sid = active_session(create=True)["id"]
    for user, mood in (("lera", "cozy"), ("nikita", "mystery")):
        ensure_participant(sid, user)
        save_preferences(sid, PreferencesIn(user_id=user, moods=[mood], energy="medium", max_runtime=None, min_year=None, disliked_genres=[]))
        deck, total = get_deck(sid, user)
        assert total >= 20 and len(deck) >= 20
        for movie in deck:
            save_swipe(sid, user, movie["id"], "like")

    assert both_ready(sid)
    results = recommend(sid)
    assert results
    store_recommendations(sid, results)
    selected = choose_movie(sid)
    watched = confirm_watched(sid)
    assert watched["movie"]["id"] == selected["id"]


def test_declined_movie_is_not_written_to_local_watch_history():
    sid = active_session(create=True)["id"]
    with db_session() as db:
        db.execute("UPDATE sessions SET selected_movie_id='arrival',status='selected' WHERE id=?", (sid,))
    decline_selected_movie(sid)
    with db_session() as db:
        session = db.execute("SELECT status,selected_movie_id,rejected_movies FROM sessions WHERE id=?", (sid,)).fetchone()
        history = db.execute("SELECT * FROM watch_history WHERE session_id=?", (sid,)).fetchone()
    assert session["status"] == "recommended"
    assert session["selected_movie_id"] is None
    assert "arrival" in session["rejected_movies"]
    assert history is None


def test_declined_movie_disappears_from_the_visible_recommendations():
    sid = active_session(create=True)["id"]
    recommendations = '[{"id":"arrival","match":90},{"id":"ex-machina","match":80}]'
    with db_session() as db:
        db.execute(
            "UPDATE sessions SET recommendations=?,selected_movie_id='arrival',status='selected' WHERE id=?",
            (recommendations, sid),
        )

    decline_selected_movie(sid)
    visible = session_state(sid)["recommendations"]

    assert [movie["id"] for movie in visible] == ["ex-machina"]


def test_future_release_is_removed_from_saved_recommendations_and_old_swipe_decks():
    sid = active_session(create=True)["id"]
    with db_session() as db:
        db.execute("UPDATE movies SET release_date='2099-01-01' WHERE id='arrival'")
        db.execute(
            "UPDATE sessions SET recommendations=?,status='recommended' WHERE id=?",
            (dumps([{"id": "arrival", "match": 90}]), sid),
        )
        db.execute(
            "INSERT INTO swipe_decks(session_id,user_id,movie_id,position) VALUES(?,?,?,?)",
            (sid, "lera", "arrival", 1),
        )

    visible = session_state(sid)["recommendations"]
    deck, _ = get_deck(sid, "lera")

    assert visible == []
    assert "arrival" not in {movie["id"] for movie in deck}
    with pytest.raises(ValueError, match="available"):
        choose_specific_recommendation(sid, "arrival")


def test_replacing_an_unreleased_swipe_card_persists_the_full_returned_deck():
    sid = active_session(create=True)["id"]
    ensure_participant(sid, "lera")
    save_preferences(sid, PreferencesIn(user_id="lera", moods=["cozy"], energy="medium", max_runtime=None, min_year=None, disliked_genres=[]))
    initial, initial_total = get_deck(sid, "lera")
    assert initial_total >= 20
    with db_session() as db:
        db.execute("UPDATE movies SET release_date='2099-01-01' WHERE id=?", (initial[0]["id"],))

    replacement, returned_total = get_deck(sid, "lera")

    with db_session() as db:
        stored = db.execute(
            "SELECT movie_id,position FROM swipe_decks WHERE session_id=? AND user_id=? ORDER BY position",
            (sid, "lera"),
        ).fetchall()
    assert returned_total == initial_total
    assert len(replacement) == returned_total == len(stored)
    assert [row["position"] for row in stored] == list(range(1, returned_total + 1))


def test_future_release_cannot_be_selected_from_watchlist_or_catalog():
    sid = active_session(create=True)["id"]
    save_movie_for_later("arrival")
    with db_session() as db:
        db.execute("UPDATE movies SET release_date='2099-01-01' WHERE id='arrival'")

    with pytest.raises(ValueError, match="released"):
        choose_saved_movie(sid, "arrival")
    with pytest.raises(ValueError, match="released"):
        choose_catalog_movie(sid, "arrival")
    assert session_state(sid)["status"] == "choosing"


def test_visible_recommendation_can_be_selected_directly():
    sid = active_session(create=True)["id"]
    with db_session() as db:
        db.execute("UPDATE sessions SET recommendations=?,status='recommended' WHERE id=?", ('[{"id":"arrival"}]', sid))
    selected = choose_specific_recommendation(sid, "arrival")
    assert selected["id"] == "arrival"
    assert session_state(sid)["status"] == "selected"


def test_background_recommendation_refresh_never_unselects_a_movie():
    sid = active_session(create=True)["id"]
    with db_session() as db:
        db.execute("UPDATE sessions SET recommendations=?,selected_movie_id='arrival',status='selected' WHERE id=?", ('[{"id":"arrival"}]', sid))
    store_recommendations(sid, [{"id": "arrival", "match": 88, "explanation_lera": "обновлено"}])
    state = session_state(sid)
    assert state["status"] == "selected"
    assert state["selected"]["id"] == "arrival"


def test_shared_watchlist_saves_once_and_can_remove_a_movie():
    saved = save_movie_for_later("arrival")
    save_movie_for_later("arrival")
    assert saved["id"] == "arrival"
    assert [movie["id"] for movie in saved_movies()] == ["arrival"]
    remove_saved_movie("arrival")
    assert saved_movies() == []


def test_watchlist_remembers_who_saved_a_movie():
    save_movie_for_later("arrival", "lera")
    assert saved_movies()[0]["saved_by"] == "lera"


def test_watchlist_keeps_the_first_simple_reason_for_deferring_a_movie():
    save_movie_for_later("arrival", "lera", "На вечер, когда будет больше времени")
    save_movie_for_later("arrival", "nikita", "На другое настроение")

    item = saved_movies()[0]
    assert item["saved_by"] == "lera"
    assert item["deferred_reason"] == "На вечер, когда будет больше времени"


def test_watchlist_api_accepts_only_simple_defer_reasons():
    client = TestClient(app)
    response = client.post(
        "/api/watchlist/arrival",
        params={"user_id": "lera", "reason": "На другое настроение"},
    )
    assert response.status_code == 200
    assert client.get("/api/watchlist").json()["items"][0]["deferred_reason"] == "На другое настроение"
    assert client.post("/api/watchlist/inception", params={"reason": "Произвольный текст"}).status_code == 422


def test_watchlist_prioritizes_movies_that_fit_tonights_time_and_mood():
    session = active_session(create=True)
    save_preferences(
        session["id"],
        PreferencesIn(user_id="lera", moods=["laugh"], energy="low", max_runtime=110, min_year=None, disliked_genres=[]),
    )
    save_movie_for_later("grand-budapest", "lera")
    save_movie_for_later("arrival", "lera")

    items = saved_movies()
    assert [item["id"] for item in items] == ["grand-budapest", "arrival"]
    assert items[0]["fits_tonight"] is True
    assert items[1]["fits_tonight"] is False


def test_frontend_offers_local_search_and_genre_filter_for_watchlist():
    from backend.config import ROOT

    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'data-watchlist-search' in source
    assert 'data-watchlist-genre' in source
    assert 'Сбросить фильтры' in source
    assert 'movie.franchise_warning' in source


def test_watchlist_warns_about_a_known_unwatched_previous_franchise_part():
    session = active_session(create=True)
    with db_session() as db:
        db.execute("UPDATE movies SET franchise_key='test-series',franchise_order=1 WHERE id='arrival'")
        db.execute("UPDATE movies SET franchise_key='test-series',franchise_order=2 WHERE id='ex-machina'")
    save_movie_for_later("ex-machina", "lera")

    item = saved_movies()[0]
    assert item["franchise_warning"] == "Сначала посмотрите: «Прибытие»."

    with db_session() as db:
        db.execute(
            "INSERT INTO watch_history(session_id,movie_id,watched_at) VALUES(?,?,datetime('now'))",
            (session["id"], "arrival"),
        )
    assert saved_movies()[0]["franchise_warning"] is None


def test_saved_movie_can_be_watched_rated_flow_and_leaves_watchlist():
    sid = active_session(create=True)["id"]
    save_movie_for_later("arrival")
    selected = choose_saved_movie(sid, "arrival")
    assert selected["id"] == "arrival"
    assert session_state(sid)["status"] == "selected"
    watched = confirm_watched(sid)
    assert watched["movie"]["id"] == "arrival"
    assert session_state(sid)["status"] == "completed"
    assert saved_movies() == []
