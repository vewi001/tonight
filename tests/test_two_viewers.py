"""Two devices share one evening, with separate twenty-card taste snapshots."""
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.api.realtime import ConnectionManager
from backend.config import settings
from backend.database.db import db_session, dumps
from backend.main import app
from backend.models.schemas import PreferencesIn
from backend.sessions.service import (
    active_session, both_ready, choose_catalog_movie, choose_movie,
    confirm_watched, decline_selected_movie, get_deck, save_preferences,
    save_swipe, session_access_code, session_state, store_recommendations,
)
from tests.http_client import TestClient


def evening():
    sid = active_session()['id']
    for user in ('lera', 'nikita'):
        save_preferences(sid, PreferencesIn(user_id=user, moods=['cozy'], energy='medium'))
    return sid


@pytest.mark.parametrize('genre_count', range(1, 8))
def test_limited_genre_diversity_never_shortens_either_deck(genre_count):
    sid = evening()
    with db_session() as db:
        ids = [r[0] for r in db.execute('SELECT id FROM movies ORDER BY id')]
        db.executemany('UPDATE movies SET genres=?,franchise_key=NULL,franchise_order=NULL WHERE id=?',
                       [(dumps([f'genre-{n % genre_count}']), mid) for n, mid in enumerate(ids)])
    for user in ('lera', 'nikita'):
        deck, total = get_deck(sid, user)
        assert total == settings.swipe_count == len(deck)
        assert len({m['id'] for m in deck}) == total
        assert [m['id'] for m in deck] == [m['id'] for m in get_deck(sid, user)[0]]


@pytest.mark.parametrize('available', [0, 4, 19])
def test_actual_shortage_never_completes_a_short_deck(available):
    sid = evening()
    with db_session() as db:
        db.execute('UPDATE movies SET release_status=NULL WHERE id NOT IN (SELECT id FROM movies ORDER BY id LIMIT ?)',
                   (available,))
        db.execute('UPDATE movies SET franchise_key=NULL,franchise_order=NULL')
    client = TestClient(app)
    for user in ('lera', 'nikita'):
        response = client.get(f'/api/sessions/{sid}/swipe/{user}')
        assert response.status_code == 409
        assert f'{available} из 20' in response.json()['detail']
        assert 'стоп-жанры' in response.json()['detail']
        assert not session_state(sid)['participants'][user]['ready']
    assert client.post(f'/api/sessions/{sid}/recommend').status_code == 409
    with db_session() as db:
        assert not db.execute('SELECT * FROM swipe_decks').fetchall()


def test_shortage_respects_filters_and_recovers_after_explicit_change():
    sid = evening()
    with db_session() as db:
        db.execute("UPDATE movies SET genres='[\"хоррор\"]',franchise_key=NULL,franchise_order=NULL")
        db.execute("UPDATE movies SET genres='[\"комедия\"]' WHERE id IN (SELECT id FROM movies LIMIT 4)")
    save_preferences(sid, PreferencesIn(user_id='lera', moods=['cozy'], energy='low', disliked_genres=['хоррор']))
    assert len(get_deck(sid, 'nikita')[0]) == 20
    with pytest.raises(ValueError, match='4 из 20'):
        get_deck(sid, 'lera')
    save_preferences(sid, PreferencesIn(user_id='lera', moods=['cozy'], energy='low'))
    assert len(get_deck(sid, 'lera')[0]) == 20


def test_concurrent_deck_requests_return_exactly_the_persisted_snapshots():
    sid = evening()
    users = ['lera', 'nikita'] * 4
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda user: get_deck(sid, user), users))
    with db_session() as db:
        for user, (movies, total) in zip(users, results):
            rows = db.execute('SELECT movie_id,position FROM swipe_decks WHERE session_id=? AND user_id=? ORDER BY position',
                              (sid, user)).fetchall()
            assert total == len(movies) == len(rows) == 20
            assert [m['id'] for m in movies] == [r['movie_id'] for r in rows]
            assert [r['position'] for r in rows] == list(range(1, 21))


def test_removed_answered_card_does_not_count_toward_its_replacement():
    sid = evening()
    deck, _ = get_deck(sid, 'lera')
    for movie in deck[:19]:
        save_swipe(sid, 'lera', movie['id'], 'like')
    with db_session() as db:
        db.execute("UPDATE movies SET release_status=NULL WHERE id=?", (deck[0]['id'],))
    remaining, total = get_deck(sid, 'lera')
    assert len(remaining) == 2 and total == 20
    assert session_state(sid)['participants']['lera']['progress'] == 18
    assert not save_swipe(sid, 'lera', remaining[0]['id'], 'unseen')['ready']
    assert save_swipe(sid, 'lera', remaining[1]['id'], 'love')['ready']


def test_legacy_four_card_completion_is_extended_and_cannot_finalize_early():
    sid = evening()
    deck, _ = get_deck(sid, 'lera')
    with db_session() as db:
        db.execute('DELETE FROM swipe_decks WHERE session_id=? AND user_id=? AND position>4', (sid, 'lera'))
    for movie in deck[:4]:
        # Preserve an actual old four-card snapshot and its saved reactions.
        with db_session() as db:
            db.execute('INSERT INTO swipes VALUES(?,?,?,?,?)', (sid, 'lera', movie['id'], 'like', 'now'))
    with db_session() as db:
        db.execute('UPDATE participants SET progress=4,ready=1 WHERE session_id=?', (sid,))
    assert not both_ready(sid)
    state = session_state(sid)
    assert not state['participants']['lera']['ready']
    remaining, total = get_deck(sid, 'lera')
    assert total == 20 and len(remaining) == 16
    assert not {m['id'] for m in deck[:4]} & {m['id'] for m in remaining}


@pytest.mark.parametrize('reaction', ['love', 'like', 'okay', 'dislike', 'unseen'])
def test_two_viewers_can_finish_concurrently_and_retry_last_answer(reaction):
    sid = evening()
    client = TestClient(app)
    decks = {u: get_deck(sid, u)[0] for u in ('lera', 'nikita')}

    def finish(user):
        for movie in decks[user]:
            result = client.post(f'/api/sessions/{sid}/swipe', json={
                'user_id': user, 'movie_id': movie['id'], 'reaction': reaction})
            assert result.status_code == 200, result.text
            assert result.json()['total'] == 20
        return result.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(finish, ('lera', 'nikita')))
    assert both_ready(sid)
    state = session_state(sid)
    assert state['status'] == 'recommended'
    for user in decks:
        retry = client.post(f'/api/sessions/{sid}/swipe', json={
            'user_id': user, 'movie_id': decks[user][-1]['id'], 'reaction': reaction})
        assert retry.status_code == 200 and retry.json()['movies'] == []
        assert retry.json()['progress'] == 20 and retry.json()['ready']
    assert [m['id'] for m in session_state(sid)['recommendations']] == [m['id'] for m in state['recommendations']]
    with db_session() as db:
        assert db.execute('SELECT count(*) FROM swipes').fetchone()[0] == 40
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_filter_edit_preserves_taste_but_recounts_only_current_cards():
    sid = evening()
    deck, _ = get_deck(sid, 'lera')
    for movie in deck[:4]:
        save_swipe(sid, 'lera', movie['id'], 'love')
    excluded = deck[0]['genres'][0]
    save_preferences(sid, PreferencesIn(user_id='lera', moods=['cozy'], energy='low', disliked_genres=[excluded]))
    remaining, total = get_deck(sid, 'lera')
    assert total == 20 and all(excluded not in m['genres'] for m in remaining)
    with db_session() as db:
        count = db.execute('''SELECT count(*) FROM swipes s JOIN swipe_decks d
            USING(session_id,user_id,movie_id) WHERE s.session_id=? AND s.user_id='lera' ''', (sid,)).fetchone()[0]
        assert db.execute('SELECT count(*) FROM swipes').fetchone()[0] == 4
    assert len(remaining) == 20 - count
    assert session_state(sid)['participants']['lera']['progress'] == count


@pytest.mark.parametrize('status', ['completed', 'abandoned'])
@pytest.mark.parametrize('operation', ['choose', 'choose-another', 'select/arrival', 'select-saved/arrival',
                                       'select-catalog/arrival', 'decline', 'start-watching', 'recommend'])
def test_finished_evening_cannot_be_reopened_by_stale_device(status, operation):
    sid = evening()
    with db_session() as db:
        db.execute("INSERT INTO watchlist(movie_id,saved_at) VALUES('arrival','now')")
        db.execute('UPDATE sessions SET status=?,selected_movie_id=?,recommendations=? WHERE id=?',
                   (status, 'arrival', dumps([{'id': 'arrival', 'match': 90}]), sid))
    before = session_state(sid)
    response = TestClient(app).post(f'/api/sessions/{sid}/{operation}')
    assert response.status_code == 409, response.text
    assert session_state(sid) == before


@pytest.mark.parametrize('operation', ['decline', 'choose-another', 'watched', 'start-watching'])
def test_stale_selected_movie_never_applies_to_a_new_choice(operation):
    sid = evening()
    choose_catalog_movie(sid, 'arrival')
    response = TestClient(app).post(f'/api/sessions/{sid}/{operation}?expected_movie_id=ex-machina')
    assert response.status_code == 409
    state = session_state(sid)
    assert state['status'] == 'selected' and state['selected']['id'] == 'arrival'
    with db_session() as db:
        assert not db.execute('SELECT * FROM watch_history').fetchall()
        assert db.execute('SELECT rejected_movies FROM sessions WHERE id=?', (sid,)).fetchone()[0] == '[]'


def test_avoid_similar_rejects_finished_evening_without_learning():
    sid = evening()
    choose_catalog_movie(sid, 'arrival')
    confirm_watched(sid)
    response = TestClient(app).post(f'/api/sessions/{sid}/avoid-similar', json={'user_id': 'lera', 'movie_id': 'arrival'})
    assert response.status_code == 409
    with db_session() as db:
        assert not db.execute('SELECT * FROM avoid_similar').fetchall()


def test_simultaneous_random_choices_converge_on_one_movie():
    sid = evening()
    store_recommendations(sid, [{'id': 'arrival', 'match': 90}, {'id': 'ex-machina', 'match': 88}])
    with ThreadPoolExecutor(max_workers=8) as pool:
        selected = list(pool.map(lambda _: choose_movie(sid)['id'], range(8)))
    assert len(set(selected)) == 1
    assert session_state(sid)['selected']['id'] == selected[0]


def test_simultaneous_watch_and_decline_never_resurrect_history():
    sid = evening()
    choose_catalog_movie(sid, 'arrival')

    def act(operation):
        try:
            operation(sid, expected_movie_id='arrival')
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(act, (confirm_watched, decline_selected_movie)))
    assert sum(outcomes) == 1
    state = session_state(sid)
    with db_session() as db:
        history = db.execute('SELECT * FROM watch_history WHERE session_id=?', (sid,)).fetchall()
    assert bool(history) == (state['status'] == 'completed')
    assert state['status'] in {'completed', 'recommended'}


def test_active_evening_is_created_once_for_simultaneous_devices():
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: active_session()['id'], range(8)))
    assert len(set(ids)) == 1


@pytest.mark.parametrize('completed', [False, True])
def test_simultaneous_restart_has_one_replacement_and_preserves_completed_history(completed):
    sid = evening()
    if completed:
        choose_catalog_movie(sid, 'arrival')
        confirm_watched(sid)
    client = TestClient(app)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post(f'/api/sessions/{sid}/restart'), range(4)))
    assert all(r.status_code == 200 for r in responses)
    replacements = {r.json()['id'] for r in responses}
    assert len(replacements) == 1 and sid not in replacements
    assert session_state(sid)['status'] == ('completed' if completed else 'abandoned')
    with db_session() as db:
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 2
        assert db.execute('SELECT count(*) FROM watch_history').fetchone()[0] == int(completed)


def test_two_open_websockets_receive_same_selection_decline_and_completion():
    sid = evening()
    code = session_access_code(sid)
    client = TestClient(app)

    def receive_state(socket, event):
        for _ in range(12):
            packet = socket.receive_json()
            if packet['type'] == event:
                return packet['session']
        pytest.fail(f'No {event} packet')

    with client.websocket_connect(f'/ws/session/{sid}/lera?code={code}') as a:
        receive_state(a, 'presence')
        with client.websocket_connect(f'/ws/session/{sid}/nikita?code={code}') as b:
            receive_state(a, 'presence')
            receive_state(b, 'presence')
            for path, event in [('select-catalog/arrival', 'selected'), ('decline', 'declined'),
                                ('select-catalog/ex-machina', 'selected'), ('start-watching', 'watching'),
                                ('watched', 'completed')]:
                response = client.post(f'/api/sessions/{sid}/{path}')
                assert response.status_code == 200, response.text
                left, right = receive_state(a, event), receive_state(b, event)
                assert left == right == session_state(sid)


def test_presence_changes_during_broadcast_do_not_crash_other_viewers():
    manager = ConnectionManager()
    delivered = []

    class Socket:
        async def send_json(self, payload):
            delivered.append(self)
            manager.disconnect(1, 'nikita', b)

    a, b = Socket(), Socket()
    manager.connections[1]['lera'].add(a)
    manager.connections[1]['nikita'].add(b)
    asyncio.run(manager.broadcast(1, {'type': 'test'}))
    assert delivered == [a, b]


def test_recommendation_background_write_cannot_change_finished_evening():
    sid = evening()
    store_recommendations(sid, [{'id': 'arrival'}])
    choose_catalog_movie(sid, 'arrival')
    confirm_watched(sid)
    before = session_state(sid)
    assert not store_recommendations(sid, [{'id': 'ex-machina'}], expected_ids={'arrival'})
    assert session_state(sid) == before


def test_missing_deck_and_restart_during_viewing_have_controlled_errors():
    client = TestClient(app)
    assert client.get('/api/sessions/999999/swipe/lera').status_code == 409
    sid = evening()
    choose_catalog_movie(sid, 'arrival')
    assert client.post(f'/api/sessions/{sid}/start-watching').status_code == 200
    assert client.post(f'/api/sessions/{sid}/restart').status_code == 409


def test_retry_completion_does_not_delete_a_later_watchlist_save():
    from backend.sessions.service import save_movie_for_later, saved_movies
    sid = evening()
    choose_catalog_movie(sid, 'arrival')
    completed = confirm_watched(sid)
    save_movie_for_later('arrival', 'nikita')
    before = session_state(sid)
    assert confirm_watched(sid) == completed
    assert session_state(sid) == before
    assert [movie['id'] for movie in saved_movies()] == ['arrival']


def test_old_restart_follows_the_complete_replacement_chain():
    client = TestClient(app)
    sid = evening()
    replacement = client.post(f'/api/sessions/{sid}/restart').json()['id']
    latest = client.post(f'/api/sessions/{replacement}/restart').json()['id']
    assert client.post(f'/api/sessions/{sid}/restart').json()['id'] == latest


def test_reloading_deck_does_not_invent_a_new_state_revision():
    sid = evening()
    get_deck(sid, 'lera')
    before = session_state(sid)['revision']
    get_deck(sid, 'lera')
    assert session_state(sid)['revision'] == before


def test_idempotent_choice_never_returns_a_newly_unavailable_movie():
    sid = evening()
    choose_catalog_movie(sid, 'arrival')
    with db_session() as db:
        db.execute("UPDATE movies SET release_status=NULL WHERE id='arrival'")
    with pytest.raises(ValueError, match='недоступен'):
        choose_movie(sid)
