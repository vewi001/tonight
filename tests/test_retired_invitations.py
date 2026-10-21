"""Retired invitations are inert; archived data and the normal evening remain usable."""
from datetime import date
from pathlib import Path

import pytest
from tests.http_client import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.database.db import db_session, dumps, initialize
from backend.main import app
from backend.sessions.service import active_session


@pytest.mark.parametrize('host', ['127.0.0.1', '192.168.1.20'])
def test_retired_clients_cannot_create_join_or_mutate_rooms(host):
    active_session()
    with db_session() as db:
        before = [tuple(row) for row in db.execute('SELECT * FROM sessions')]
    client = TestClient(app, client=(host, 1234))
    for method, path in [('POST', '/api/sessions/new?movie_match=true'),
                         ('POST', '/api/movie-match/join'),
                         ('POST', '/api/sessions/1/match'),
                         ('GET', '/api/sessions/1/match'),
                         ('GET', '/api/sessions/1/match/qr?room=old')]:
        response = client.request(method, path)
        assert response.status_code == 410
        assert response.json()['redirect'] == '/'
        assert 'По знакомым фильмам' in response.json()['detail']
    with db_session() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM sessions')] == before


def test_archived_room_is_preserved_but_cannot_become_active_or_gain_profile_access():
    active = active_session()
    legacy = dumps({'room':'old-invitation', 'votes':{'0':{'film':'yes'}}, 'phase':'voting'})
    with db_session() as db:
        cur = db.execute('INSERT INTO sessions(session_date,title,status,match_data,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                         (date.today().isoformat(), 'Archived', 'watching', legacy, 'old', 'old'))
        sid = cur.lastrowid
    initialize()
    assert active_session()['id'] == active['id']
    client = TestClient(app, client=('127.0.0.1',1234))
    for method, suffix in [('GET',''),('POST','/join'),('POST','/restart'),('POST','/preferences')]:
        assert client.request(method, f'/api/sessions/{sid}{suffix}').status_code == 410
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f'/ws/session/{sid}/lera'):
            pass
    with db_session() as db:
        row = db.execute('SELECT match_data,status,updated_at FROM sessions WHERE id=?', (sid,)).fetchone()
        assert tuple(row) == (legacy, 'watching', 'old')
    # Phone pairing still uses the existing application invitation and evening code.
    invitation = client.get('/api/invite').json()
    assert 'room=' not in invitation['url']
    remote = TestClient(app, client=('192.168.1.20',1234))
    assert remote.post(f'/api/sessions/{active["id"]}/join',json={'user_id':'lera','access_code':invitation['access_code']}).status_code == 200


def test_removed_implementation_and_legacy_page_fallback():
    root = Path(__file__).resolve().parents[1]
    for name in ('frontend/movie-match.js','frontend/movie-match.css','backend/sessions/movie_match.py'):
        assert not (root/name).exists()
    client = TestClient(app)
    for url in ('/?join=1&room=old', '/movie-match/old', '/match/old'):
        response = client.get(url)
        assert response.status_code == 200
        assert 'movie-match.js' not in response.text
