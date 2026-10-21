from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.database.db import db_session
from backend.main import app
from backend.sessions.service import active_session


@pytest.mark.parametrize('change', [
    {'moods': ['made-up']}, {'moods': ['cozy', 'cozy']}, {'max_runtime': -1},
    {'max_runtime': 0}, {'max_runtime': True}, {'max_runtime': 1500},
    {'min_year': 9999}, {'min_year': 1800}, {'min_year': False},
    {'min_year': 2020, 'max_year': 1900}, {'min_runtime': 150, 'max_runtime': 90},
])
def test_invalid_preferences_leave_participant_unchanged(change):
    client = TestClient(app)
    sid = active_session()['id']
    payload = dict(user_id='lera', moods=['cozy'], energy='low', max_runtime=None, min_year=None)
    assert client.post(f'/api/sessions/{sid}/preferences', json=payload).status_code == 200
    with db_session() as db:
        before = [tuple(row) for row in db.execute('SELECT * FROM participants')]
    assert client.post(f'/api/sessions/{sid}/preferences', json={**payload, **change}).status_code == 422
    with db_session() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM participants')] == before


@pytest.mark.parametrize('runtime', [90, 120, 150, None])
@pytest.mark.parametrize('year', [2015, 2000, 1990, None])
def test_every_interface_filter_value_remains_valid(runtime, year):
    sid = active_session()['id']
    response = TestClient(app).post(f'/api/sessions/{sid}/preferences', json={
        'user_id': 'nikita', 'moods': ['laugh', 'smart', 'scary', 'emotional', 'cozy', 'action',
                                    'mystery', 'wow', 'romance', 'atmosphere', 'surprise'],
        'energy': 'high', 'max_runtime': runtime, 'min_year': year})
    assert response.status_code == 200


@pytest.mark.parametrize('operation', ['join', 'preferences'])
@pytest.mark.parametrize('state', ['missing', 'deleted', 'abandoned'])
def test_missing_or_stale_evening_returns_client_error(operation, state):
    sid = active_session()['id']
    with db_session() as db:
        if state == 'deleted':
            db.execute('DELETE FROM sessions WHERE id=?', (sid,))
        elif state == 'abandoned':
            db.execute("UPDATE sessions SET status='abandoned' WHERE id=?", (sid,))
        else:
            sid = 999999
    payload = {'user_id': 'lera', **({'moods': ['cozy'], 'energy': 'low'} if operation == 'preferences' else {})}
    client = TestClient(app, raise_server_exceptions=False)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post(f'/api/sessions/{sid}/{operation}', json=payload).status_code, range(4)))
    assert responses == [404] * 4
    with db_session() as db:
        assert not db.execute('SELECT * FROM participants').fetchall()
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_old_evening_id_after_importing_another_database_is_controlled(tmp_path, monkeypatch):
    import backend.main as main
    from backend.database.db import initialize
    client = TestClient(app, headers={'X-Tonight-Request': '1'})
    old_sid = active_session()['id']
    replacement = tmp_path / 'replacement.db'
    initialize(replacement)
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    response = client.post('/api/backups/import?confirmed=true', content=replacement.read_bytes(),
                           headers={'Content-Type': 'application/vnd.sqlite3'})
    assert response.status_code == 200, response.text
    for operation, payload in [('join', {'user_id': 'lera'}), ('preferences', {
        'user_id': 'lera', 'moods': ['cozy'], 'energy': 'medium'})]:
        response = client.post(f'/api/sessions/{old_sid}/{operation}', json=payload)
        assert response.status_code == 404, response.text
    with db_session() as db:
        assert not db.execute('SELECT * FROM participants').fetchall()
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


def test_catalog_search_only_materializes_returned_movies(monkeypatch):
    import backend.movies.catalog as catalog
    actual, seen = catalog.row_to_movie, []
    def counted(row):
        seen.append(row['id'])
        return actual(row)
    monkeypatch.setattr(catalog, 'row_to_movie', counted)
    results = catalog.search_movies('a', 12)
    assert not results and not seen
    results = catalog.search_movies('the', 12)
    assert results and len(seen) == len(results) <= 12


def test_search_worker_does_not_block_health(monkeypatch):
    import backend.main as main
    started, release = threading.Event(), threading.Event()
    def slow_search(query):
        started.set()
        assert release.wait(5)
        return []
    monkeypatch.setattr(main, 'search_movies', slow_search)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
            search = asyncio.create_task(client.get('/api/movies/search?q=space'))
            assert await asyncio.to_thread(started.wait, 2)
            try:
                health = await asyncio.wait_for(client.get('/api/health'), 1)
                assert health.status_code == 200
                assert not search.done()
            finally:
                release.set()
            assert (await search).status_code == 200
    asyncio.run(exercise())
