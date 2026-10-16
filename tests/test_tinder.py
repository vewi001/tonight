import uuid
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database.db import db_session, initialize
from backend.recommendation.taste_profile import taste_signals, reset_profile

client = TestClient(app)


def deck(user='lera', seen=None):
    response=client.post(f'/api/tinder/{user}/recommendations',json={'seen_ids':seen or []})
    assert response.status_code==200
    return response.json()['items']


def act(movie, action, save=False, user='lera', token=None):
    return client.post(f'/api/tinder/{user}/movies/{movie}',json={
        'action':action,'save_watchlist':save,'request_id':token or str(uuid.uuid4())})


def undo(token, user='lera'):
    return client.post(f'/api/tinder/{user}/undo/{token}')


def test_decks_are_personal_unique_and_exclude_seen_and_actions():
    first=deck();ids=[m['id'] for m in first]
    assert len(ids)==len(set(ids)) and ids
    second=deck(seen=ids)
    assert not set(ids)&{m['id'] for m in second}
    for movie, action in zip(first,['interest','dislike','watched']):
        assert act(movie['id'],action).status_code==200
    assert not set(ids[:3])&{m['id'] for m in deck()}
    assert set(ids[:3])&{m['id'] for m in deck('nikita')}


@pytest.mark.parametrize('action,value',[('interest',.3),('dislike',-1),('watched',None)])
def test_action_iq_and_real_undo(action,value):
    movie=deck()[0]['id']
    response=act(movie,action)
    assert response.status_code==200
    with db_session() as db:
        signals=taste_signals(db,'lera')
        assert [s['value'] for s in signals if s['id']==movie]==([] if value is None else [value])
        assert db.execute('SELECT count(*) FROM watch_history').fetchone()[0]==0
    initialize()  # Survives reopening / normal application initialization.
    assert movie not in {m['id'] for m in deck()}
    assert undo(response.json()['id']).status_code==200
    assert movie in {m['id'] for m in deck()}
    with db_session() as db:
        assert not taste_signals(db,'lera')
        assert db.execute('SELECT count(*) FROM viewer_movie_actions').fetchone()[0]==0


@pytest.mark.parametrize('already_saved',[False,True])
def test_optional_watchlist_undo_preserves_prior_state(already_saved):
    movie=deck()[0]['id']
    if already_saved:
        with db_session() as db:
            db.execute('INSERT INTO watchlist VALUES(?,?,?,?)',(movie,'original','nikita','later'))
    response=act(movie,'interest',True)
    with db_session() as db:
        assert db.execute('SELECT 1 FROM watchlist WHERE movie_id=?',(movie,)).fetchone()
    assert undo(response.json()['id']).status_code==200
    with db_session() as db:
        row=db.execute('SELECT * FROM watchlist WHERE movie_id=?',(movie,)).fetchone()
        assert bool(row)==already_saved
        if row: assert (row['saved_at'],row['saved_by'],row['deferred_reason'])==('original','nikita','later')


def test_prior_status_restored_and_undo_is_lifo_and_idempotent():
    first,second=deck()[:2]
    with db_session() as db:
        db.execute('INSERT INTO viewer_movie_actions VALUES(?,?,?,?)',('lera',first['id'],'watched','original'))
    a=act(first['id'],'interest').json()['id']
    b=act(second['id'],'dislike').json()['id']
    assert undo(a).status_code==409
    assert undo(b).status_code==200
    assert undo(b).status_code==200
    assert undo(a).status_code==200
    with db_session() as db:
        rows=list(db.execute('SELECT action,created_at FROM viewer_movie_actions'))
        assert [tuple(r) for r in rows]==[('watched','original')]


def test_lost_response_retry_applies_once_and_foreign_undo_fails():
    movie=deck()[0]['id'];token=str(uuid.uuid4())
    assert act(movie,'interest',token=token).status_code==200
    assert act(movie,'interest',token=token).status_code==200
    assert act(movie,'interest',True,token=token).status_code==409
    assert undo(token,'nikita').status_code==404
    with db_session() as db:
        assert db.execute('SELECT count(*) FROM tinder_actions').fetchone()[0]==1
    assert undo(token).status_code==200
    assert act(movie,'interest',token=token).status_code==409


def test_undo_does_not_overwrite_changes_from_other_screen():
    movie=deck()[0]['id'];token=act(movie,'interest',True).json()['id']
    with db_session() as db:
        db.execute("UPDATE watchlist SET saved_by='nikita',saved_at='changed' WHERE movie_id=?",(movie,))
    assert undo(token).status_code==409
    with db_session() as db:
        assert db.execute('SELECT saved_at FROM watchlist WHERE movie_id=?',(movie,)).fetchone()[0]=='changed'


def test_reset_shares_iq_semantics():
    movie=deck()[0]['id'];act(movie,'interest')
    reset_profile('lera')
    with db_session() as db: assert not taste_signals(db,'lera')
    assert movie not in {m['id'] for m in deck()}


def test_existing_preferences_hidden_and_watched_are_respected():
    movie=deck()[0]['id']
    client.post(f'/api/tonight/lera/movies/{movie}',json={'action':'dislike'})
    assert movie not in {m['id'] for m in deck()}
    with db_session() as db: db.execute("UPDATE movies SET release_status=NULL,theatrical_release_date=NULL")
    assert deck()==[]


def test_invalid_requests_and_empty_catalog():
    assert client.post('/api/tinder/unknown/recommendations',json={}).status_code==400
    assert act('missing','watched').status_code==404
    assert act('arrival','love').status_code==422
    assert act('arrival','watched',True).status_code==422
    assert client.post('/api/tinder/lera/movies/arrival',json={'action':'interest','request_id':'x'}).status_code==422


def test_migrate_old_action_constraint_without_data_loss(tmp_path):
    import sqlite3
    path=tmp_path/'old.db'
    initialize(path)
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE viewer_movie_actions')
        db.execute("CREATE TABLE viewer_movie_actions(user_id TEXT NOT NULL REFERENCES users(id),movie_id TEXT NOT NULL REFERENCES movies(id),action TEXT NOT NULL CHECK(action IN ('watched','dislike')),created_at TEXT NOT NULL,PRIMARY KEY(user_id,movie_id,action))")
        db.execute("INSERT INTO movies(id,title,year,genres) VALUES('arrival','Прибытие',2016,'[]')")
        db.execute("INSERT INTO viewer_movie_actions VALUES('lera','arrival','watched','original')")
    initialize(path)
    initialize(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM viewer_movie_actions').fetchone()==('lera','arrival','watched','original')
        assert "'interest'" in db.execute("SELECT sql FROM sqlite_master WHERE name='viewer_movie_actions'").fetchone()[0]


def test_tinder_keeps_preferences_and_all_seen_can_exhaust():
    from backend.sessions.service import active_session
    session=active_session()
    with db_session() as db:
        db.execute("INSERT OR REPLACE INTO participants(session_id,user_id,min_year,max_runtime,disliked_genres,joined_at) VALUES(?,?,?,?,?,?)",(session['id'],'lera',2000,120,'["хоррор"]','now'))
    items=deck()
    assert items and all(m['year']>=2000 and m['runtime']<=120 and 'хоррор' not in m['genres'] for m in items)
    with db_session() as db: ids=[r[0] for r in db.execute('SELECT id FROM movies')]
    assert deck(seen=ids)==[]


def test_viewing_rating_still_overrides_discovery_interest():
    movie=deck()[0]['id']
    act(movie,'interest')
    with db_session() as db:
        history=db.execute('INSERT INTO watch_history(movie_id,watched_at) VALUES(?,?)',(movie,'now')).lastrowid
        db.execute('INSERT INTO feedback VALUES(?,?,?,?)',(history,'lera',1,'now'))
        assert next(s for s in taste_signals(db,'lera') if s['id']==movie)['value']==-1


def test_privacy_deletes_action_snapshots(tmp_path):
    from backend.privacy import delete_personal_data
    from backend.config import settings
    movie=deck()[0]['id'];act(movie,'interest',True)
    delete_personal_data(settings.db_path,tmp_path/'backups')
    with db_session() as db:
        assert db.execute('SELECT count(*) FROM tinder_actions').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM viewer_movie_actions').fetchone()[0]==0


def test_tonight_disinterest_after_tinder_overrides_interest():
    movie=deck()[0]['id'];act(movie,'interest')
    assert client.post(f'/api/tonight/lera/movies/{movie}',json={'action':'dislike'}).status_code==200
    with db_session() as db:
        assert next(s for s in taste_signals(db,'lera') if s['id']==movie)['value']==-1
