import pytest
from fastapi.testclient import TestClient

from backend.database.db import db_session, initialize
from backend.main import app, TonightModeIn
from backend.recommendation.personal import personal_recommendations
from backend.sessions.service import active_session, session_state


@pytest.mark.parametrize('viewer,other', [('lera', 'nikita'), ('nikita', 'lera')])
def test_solo_evening_needs_only_one_viewer_and_keeps_rating_personal(viewer, other):
    client = TestClient(app)
    sid = active_session()['id']
    client.post(f'/api/sessions/{sid}/join', json={'user_id': viewer})
    selected = client.post(f'/api/sessions/{sid}/select-catalog/arrival',
                           json={'company': 'solo', 'user_id': viewer})
    assert selected.status_code == 200
    assert session_state(sid)['solo_user_id'] == viewer
    assert not session_state(sid)['participants'][other]['joined']
    assert client.post(f'/api/sessions/{sid}/start-watching').json()['status'] == 'watching'
    # Migration is idempotent and a reload retains the actual viewing context.
    initialize()
    assert client.get(f'/api/sessions/{sid}').json()['viewing_company'] == 'solo'
    with db_session() as db:
        assert db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM watch_history').fetchone()[0] == 0
    hid = client.post(f'/api/sessions/{sid}/watched').json()['history_id']
    assert client.post(f'/api/history/{hid}/feedback', json={'user_id': viewer, 'rating': 5}).status_code == 200
    assert client.post(f'/api/history/{hid}/feedback', json={'user_id': other, 'rating': 5}).status_code == 409
    assert client.post(f'/api/history/{hid}/evening-feedback', json={'user_id': viewer, 'fit': True}).status_code == 409
    entry = client.get('/api/history').json()['items'][0]
    assert entry['viewing_company'] == 'solo' and entry['solo_user_id'] == viewer
    assert entry['ratings'][viewer] == 5 and entry['ratings'][other] is None
    with db_session() as db:
        assert db.execute('SELECT COUNT(*) FROM evening_feedback').fetchone()[0] == 0
    # A solo viewing must not hide this film from the other person's solo picks.
    options = TonightModeIn(company='solo', seen_ids=[]).model_dump()
    assert 'arrival' not in {m['id'] for m in personal_recommendations(viewer, 1000, tonight=options)['items']}
    assert 'arrival' in {m['id'] for m in personal_recommendations(other, 1000, tonight=options)['items']}


def test_solo_selection_validation_and_normal_selection_reset():
    client = TestClient(app)
    sid = active_session()['id']
    url = f'/api/sessions/{sid}/select-catalog/arrival'
    assert client.post(url, json={'company': 'solo'}).status_code == 422
    assert client.post(url, json={'company': 'solo', 'user_id': 'stranger'}).status_code == 422
    assert client.post(url, json={'company': 'solo', 'user_id': 'lera'}).status_code == 200
    assert client.post(url).status_code == 200
    state = session_state(sid)
    assert state['viewing_company'] == 'couple' and state['solo_user_id'] is None
    client.post(f'/api/sessions/{sid}/start-watching')
    assert client.post(url, json={'company': 'solo', 'user_id': 'lera'}).status_code == 409
    assert session_state(sid)['viewing_company'] == 'couple'


def test_solo_selection_still_requires_evening_access_on_phone():
    sid = active_session()['id']
    client = TestClient(app, client=('192.168.1.50', 50000))
    assert client.post(f'/api/sessions/{sid}/select-catalog/arrival',
                       json={'company': 'solo', 'user_id': 'lera'}).status_code == 403
