from fastapi.testclient import TestClient

from backend.database.db import db_session
from backend.main import app
from backend.sessions.service import active_session,choose_catalog_movie


def test_start_watching_does_not_record_a_view_or_a_rating_and_finish_is_explicit():
    client=TestClient(app); sid=active_session()['id']
    choose_catalog_movie(sid,'arrival')
    with db_session() as db:
        db.execute("INSERT INTO watchlist(movie_id,saved_at) VALUES('arrival','synthetic')")
    started=client.post(f'/api/sessions/{sid}/start-watching')
    assert started.status_code==200 and started.json()['status']=='watching'
    assert client.post(f'/api/sessions/{sid}/start-watching').status_code==200
    assert client.get(f'/api/sessions/{sid}').json()['status']=='watching'
    with db_session() as db:
        assert db.execute('SELECT COUNT(*) FROM watch_history').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0]==0
        assert db.execute("SELECT movie_id FROM watchlist WHERE movie_id='arrival'").fetchone()
    finished=client.post(f'/api/sessions/{sid}/watched')
    assert finished.status_code==200
    hid=finished.json()['history_id']
    assert client.post(f'/api/sessions/{sid}/watched').json()['history_id']==hid
    with db_session() as db:
        assert db.execute('SELECT COUNT(*) FROM watch_history').fetchone()[0]==1
        assert db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0]==0
    assert client.post(f'/api/history/{hid}/feedback',json={'user_id':'lera','rating':5}).status_code==200
    history=client.get('/api/history').json()['items'][0]
    assert history['ratings']['lera']==5 and history['ratings']['nikita'] is None


def test_start_watching_rejects_no_selection_and_unconfirmed_movie():
    client=TestClient(app); sid=active_session()['id']
    assert client.post(f'/api/sessions/{sid}/start-watching').status_code==409
    choose_catalog_movie(sid,'arrival')
    with db_session() as db: db.execute("UPDATE movies SET russian_title=NULL WHERE id='arrival'")
    assert client.post(f'/api/sessions/{sid}/start-watching').status_code==409


def test_phone_cannot_start_watching_without_evening_access():
    sid=active_session()['id']; choose_catalog_movie(sid,'arrival')
    client=TestClient(app,client=('192.168.1.50',50000))
    assert client.post(f'/api/sessions/{sid}/start-watching').status_code==403


def test_unfinished_viewing_survives_midnight_and_cannot_be_replaced():
    client=TestClient(app); sid=active_session()['id']
    choose_catalog_movie(sid,'arrival')
    assert client.post(f'/api/sessions/{sid}/start-watching').status_code==200
    with db_session() as db:
        db.execute("UPDATE sessions SET session_date='2000-01-01' WHERE id=?",(sid,))
    assert active_session()['id']==sid
    assert active_session()['status']=='watching'
    import pytest
    with pytest.raises(ValueError): choose_catalog_movie(sid,'arrival')
    assert client.post(f'/api/sessions/{sid}/watched').status_code==200
    assert active_session()['id']!=sid
