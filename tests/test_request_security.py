from __future__ import annotations

import ntpath
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.main import app
from backend.database.db import db_session
from backend.sessions.service import active_session, session_access_code


@pytest.mark.parametrize('host', ['testserver/api/movies/search#', 'testserver/api/sessions/1/join#',
                                      'testserver/?', 'testserver#', 'testserver?', 'testserver\\x',
                                      'audit.invalid', 'user@testserver'])
@pytest.mark.parametrize('credential', ['absent', 'wrong', 'correct'])
def test_host_cannot_select_authorization_path(host, credential):
    sid = active_session(create=True)['id']
    headers = {'Host': host}
    if credential != 'absent':
        headers['X-Tonight-Code'] = session_access_code(sid) if credential == 'correct' else 'wrong'
    client = TestClient(app, client=('192.168.1.99', 1234))
    assert client.get('/api/taste', headers=headers).status_code == 403
    assert client.post('/api/tonight/lera/movies/arrival', headers=headers, json={'action': 'watchlist'}).status_code == 403
    with db_session() as db:
        assert db.execute('SELECT count(*) FROM watchlist').fetchone()[0] == 0


@pytest.mark.parametrize('credential,status', [('absent', 403), ('wrong', 403), ('correct', 200)])
def test_normal_host_still_requires_code(credential, status):
    sid = active_session(create=True)['id']
    headers = {} if credential == 'absent' else {'X-Tonight-Code': session_access_code(sid) if credential == 'correct' else 'wrong'}
    client = TestClient(app, client=('192.168.1.99', 1234))
    assert client.get('/api/taste', headers=headers).status_code == status
    assert client.post('/api/tonight/lera/movies/arrival', headers=headers, json={'action': 'watchlist'}).status_code == status


@pytest.mark.parametrize('origin', ['https://audit.invalid', 'http://testserver:99', 'null'])
@pytest.mark.parametrize('content_type', ['text/plain', 'application/x-www-form-urlencoded', 'multipart/form-data', 'application/json'])
def test_foreign_origin_cannot_mutate_even_with_custom_header(origin, content_type):
    client = TestClient(app)
    headers = {'Origin': origin, 'Content-Type': content_type, 'X-Tonight-Request': '1'}
    for url in ['/api/backups/import?confirmed=true', '/api/backup', '/api/sessions/new']:
        assert client.post(url, content=b'{}', headers=headers).status_code == 403
    assert client.get('/api/taste', headers={'Origin': origin}).status_code == 403


@pytest.mark.parametrize('content_type', ['text/plain', 'application/x-www-form-urlencoded', 'multipart/form-data', ''])
def test_no_origin_simple_mutation_requires_explicit_header(content_type):
    client = TestClient(app)
    assert client.post('/api/sessions/new', content=b'{}', headers={'Content-Type': content_type}).status_code == 403
    assert client.post('/api/sessions/new', headers={'X-Tonight-Request': '1'}).status_code == 200


def test_same_origin_browser_and_json_local_tools_work():
    client = TestClient(app)
    assert client.post('/api/sessions/new', headers={'Origin': 'http://testserver', 'X-Tonight-Request': '1'}).status_code == 200
    assert client.post('/api/sessions/new', json={}).status_code == 200
    assert client.get('/assets/app.js').status_code == 200


@pytest.mark.parametrize('origin', ['https://audit.invalid', 'null', None])
def test_socket_does_not_trust_loopback_alone(origin):
    sid = active_session(create=True)['id']
    client = TestClient(app)
    headers = {} if origin is None else {'Origin': origin}
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f'/ws/session/{sid}/lera', headers=headers):
            pytest.fail('Untrusted socket accepted')


def test_same_origin_browser_and_code_authenticated_socket_tools_work():
    sid = active_session(create=True)['id']
    client = TestClient(app)
    for suffix, headers in [('', {'Origin': 'http://testserver'}), (f'?code={session_access_code(sid)}', {})]:
        with client.websocket_connect(f'/ws/session/{sid}/lera{suffix}', headers=headers) as ws:
            assert ws.receive_json()['session']['id'] == sid


@pytest.mark.parametrize('path', ['%5C%5C127.0.0.1%5Caudit-share%5Cfile', '%2f%2f127.0.0.1/share',
                                     'C:%5CWindows%5Cwin.ini', '%2e%2e/secret', '%252e%252e/secret',
                                     '%5C%5C?%5CC:%5Cfile', 'fonts/font.woff2:stream'])
def test_dangerous_windows_paths_rejected_before_filesystem(path, monkeypatch):
    seen = []
    original = ntpath.realpath
    def guarded(value, *args, **kwargs):
        if str(value).startswith('\\\\') or 'audit-share' in str(value):
            seen.append(str(value))
            return 'C:\\blocked-audit-path'
        return original(value, *args, **kwargs)
    monkeypatch.setattr(ntpath, 'realpath', guarded)
    assert TestClient(app).get('/assets/' + path).status_code == 403
    assert not seen
