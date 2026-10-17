"""Hard policies must precede every discovery ranker without changing IQ."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.main import app, TonightModeIn, RouletteIn
from backend.database.db import db_session, initialize, dumps
from backend.recommendation.exclusions import (
    allows, change_rule, state_for_user,
)
from backend.recommendation.engine import recommend
from backend.recommendation.personal import personal_recommendations
from backend.recommendation.taste_profile import taste_signals, reset_profile
from backend.sessions.service import active_session, store_recommendations, choose_movie, choose_specific_recommendation, session_state, confirm_watched

client = TestClient(app)


def add(kind, value, user='lera', scope='permanent', sid=None):
    return client.post(f'/api/exclusions/{user}', json={'kind':kind,'value':value,'scope':scope,'session_id':sid})


def all_ids():
    with db_session() as db:
        return {r[0] for r in db.execute('SELECT id FROM movies')}


def test_permanent_crud_persistence_reset_and_old_data():
    sid=active_session()['id']
    with db_session() as db:
        db.execute('INSERT INTO swipes VALUES(?,?,?,?,?)',(sid,'lera','arrival','love','now'))
        before=taste_signals(db,'lera')
    assert add('movie','arrival').status_code==200
    assert add('movie','arrival').status_code==200
    assert add('genre','horror').json()['permanent'][0]['value']=='хоррор'  # canonical alias
    initialize()  # existing DB / application restart, idempotent upgrade
    assert len(state_for_user('lera')['permanent'])==2
    with db_session() as db:
        assert taste_signals(db,'lera')==before
    reset_profile('lera')
    assert len(state_for_user('lera')['permanent'])==2
    assert client.delete('/api/exclusions/lera?kind=movie&value=arrival').status_code==200
    assert client.delete('/api/exclusions/lera?clear=true').status_code==422
    assert len(state_for_user('lera')['permanent'])==1
    assert client.delete('/api/exclusions/lera?clear=true&confirmed=true').json()['permanent']==[]
    with db_session() as db:
        assert db.execute('SELECT reaction FROM swipes').fetchone()[0]=='love'


@pytest.mark.parametrize('kind,value', [('genre','imaginary'),('keyword','imaginary'),('director','imaginary'),
    ('movie','absent'),('max_runtime','0'),('max_runtime','1441'),('watched','false')])
def test_unsupported_or_invented_metadata_is_rejected(kind,value):
    assert add(kind,value).status_code==422


def test_catalog_characteristics_and_removal_are_real():
    data=state_for_user('lera')
    for kind in ('genre','keyword','director'):
        value=data['options'][kind][0]
        assert add(kind,value).status_code==200
        change_rule('lera','permanent',kind=kind,value=value,remove=True)
    assert state_for_user('lera')['permanent']==[]


@pytest.mark.parametrize('finish', ['completed','abandoned','midnight','restart','clear'])
def test_temporary_restoration_expiry_and_no_learning(finish):
    sid=active_session()['id']
    with db_session() as db:
        db.execute('INSERT INTO swipes VALUES(?,?,?,?,?)',(sid,'lera','arrival','love','now'))
        before=taste_signals(db,'lera')
    assert add('genre','хоррор',scope='temporary',sid=sid).status_code==200
    initialize()
    other_device=TestClient(app)
    assert other_device.get(f'/api/exclusions/lera?session_id={sid}').json()['temporary']==[{'kind':'genre','value':'хоррор'}]
    with db_session() as db:
        assert taste_signals(db,'lera')==before
        assert not db.execute('SELECT 1 FROM recommendation_exclusions').fetchone()
    if finish in {'completed','abandoned'}:
        with db_session() as db:
            db.execute('UPDATE sessions SET status=? WHERE id=?',(finish,sid))
    elif finish=='midnight':
        with db_session() as db:
            db.execute('UPDATE sessions SET session_date=? WHERE id=?',((date.today()-timedelta(days=1)).isoformat(),sid))
    elif finish=='restart':
        new=client.post(f'/api/sessions/{sid}/restart').json()
        assert state_for_user('lera',new['id'])['temporary']==[]
    else:
        assert client.delete(f'/api/exclusions/lera?scope=temporary&clear=true&session_id={sid}').status_code==200
    assert state_for_user('lera',sid)['temporary']==[]
    if finish!='clear':
        assert add('genre','драма',scope='temporary',sid=sid).status_code==422


def test_finish_physically_clears_temporary_rules_and_keeps_permanent():
    sid=active_session()['id']
    add('genre','драма',scope='temporary',sid=sid)
    add('genre','хоррор')
    with db_session() as db:
        db.execute("UPDATE sessions SET selected_movie_id='arrival' WHERE id=?",(sid,))
    confirm_watched(sid)
    with db_session() as db:
        assert db.execute('SELECT temporary_exclusions FROM sessions').fetchone()[0]=='{}'
    assert state_for_user('lera')['permanent']


@pytest.mark.parametrize('mode', ['personal','tonight','tinder','roulette-smart','roulette-surprise','roulette-watchlist','match','weekly'])
@pytest.mark.parametrize('scope', ['permanent','temporary'])
def test_shared_filter_applies_before_all_modes(mode,scope):
    sid=active_session()['id']
    with db_session() as db:
        db.execute("INSERT INTO watchlist(movie_id,saved_at) SELECT id,'now' FROM movies")
    assert add('genre','хоррор',scope=scope,sid=sid).status_code==200
    assert add('movie','arrival',scope=scope,sid=sid).status_code==200
    if mode=='personal':
        items=personal_recommendations('lera',200)['items']
    elif mode=='tonight':
        items=client.post('/api/tonight/lera/recommendations',json={}).json()['items']
    elif mode=='tinder':
        items=client.post('/api/tinder/lera/recommendations',json={}).json()['items']
    elif mode.startswith('roulette'):
        opts=RouletteIn(mode=mode.split('-')[1]).model_dump()
        # Verify the whole pool by drawing without replacement, not one lucky pick.
        items=[]
        for _ in range(len(all_ids())+1):
            opts['seen_ids']=[m['id'] for m in items]
            batch=personal_recommendations('lera',1,tonight=opts,roulette=opts)['items']
            if not batch:break
            items+=batch
    elif mode=='match':
        items=recommend(sid,200)
    else:
        with db_session() as db:db.execute('DELETE FROM watchlist')
        items=client.get('/api/weekly-picks').json()['items']
    assert items
    assert all('хоррор' not in m['genres'] and m['id']!='arrival' for m in items)


def test_pair_unions_both_users_without_writing_their_profiles():
    sid=active_session()['id']
    add('movie','arrival',user='nikita',scope='temporary',sid=sid)
    solo=personal_recommendations('lera',200)['items']
    pair=personal_recommendations('lera',200,tonight=TonightModeIn(company='couple').model_dump())['items']
    assert 'arrival' in {m['id'] for m in solo}
    assert 'arrival' not in {m['id'] for m in pair}
    assert state_for_user('lera')['temporary']==[]
    with db_session() as db:
        assert taste_signals(db,'lera')==taste_signals(db,'nikita')==[]


def test_conflict_and_empty_results_never_relax_hard_rules():
    sid=active_session()['id']
    add('genre','хоррор')
    data=client.post('/api/tonight/lera/recommendations',json={'mood':'scary','excluded_genres':['триллер']}).json()
    assert data['items']==[]
    assert data['exclusions']['permanent']==1
    assert client.post('/api/roulette/lera/pick',json={'included_genres':['хоррор']}).json()['items']==[]
    add('max_runtime','1',scope='temporary',sid=sid)
    assert not personal_recommendations('lera')['items']
    assert not recommend(sid)
    assert state_for_user('lera')['permanent']


@pytest.mark.parametrize('kind,value,field,valid', [('genre','хоррор','genres',['комедия']),
    ('keyword','space','keywords',['cooking']),('director','A','director','B'),('max_runtime','120','runtime',110)])
def test_missing_metadata_fails_closed(kind,value,field,valid):
    rule=[{'kind':kind,'value':value}]
    assert not allows({'id':'m'},rule)
    assert allows({'id':'m',field:valid},rule)


def test_stale_match_snapshot_and_late_ai_cannot_resurrect_excluded_movie():
    sid=active_session()['id']
    results=recommend(sid,200)
    target=results[0]['id']
    store_recommendations(sid,results)
    add('movie',target)
    store_recommendations(sid,results)  # simulate an older in-flight AI response
    assert target not in {m['id'] for m in session_state(sid)['recommendations']}
    with pytest.raises(ValueError):choose_specific_recommendation(sid,target)
    for _ in range(10):assert choose_movie(sid)['id']!=target


def test_explicit_search_and_catalog_selection_remain_available():
    sid=active_session()['id']
    add('movie','arrival')
    assert any(m['id']=='arrival' for m in client.get('/api/movies/search?q=Прибытие').json()['items'])
    assert client.post(f'/api/sessions/{sid}/select-catalog/arrival',json={'company':'solo','user_id':'lera'}).status_code==200


def test_existing_disinterest_is_visible_removable_and_keeps_watched():
    sid=active_session()['id']
    client.post('/api/tonight/lera/movies/arrival',json={'action':'dislike'})
    client.post('/api/tonight/lera/movies/arrival',json={'action':'watched'})
    assert state_for_user('lera')['disinterest'][0]['movie_id']=='arrival'
    assert 'arrival' not in {m['id'] for m in recommend(sid,200)}
    assert client.delete('/api/exclusions/lera/disinterest/arrival').status_code==200
    assert state_for_user('lera')['disinterest']==[]
    with db_session() as db:
        assert db.execute("SELECT action FROM viewer_movie_actions WHERE movie_id='arrival'").fetchone()[0]=='watched'


def test_sync_broadcast_and_second_device_reads_same_rules(monkeypatch):
    from backend.main import manager
    sid=active_session()['id']
    messages=[]
    async def broadcast(session_id,payload):messages.append((session_id,payload))
    monkeypatch.setattr(manager,'connections',{sid:{}})
    monkeypatch.setattr(manager,'broadcast',broadcast)
    assert add('genre','драма').status_code==200
    assert any(payload['type']=='exclusions_changed' for _,payload in messages)
    assert TestClient(app).get('/api/exclusions/lera').json()['permanent']==state_for_user('lera')['permanent']


def test_remote_endpoints_keep_evening_code_protection(monkeypatch):
    from backend import main
    monkeypatch.setattr(main,'_is_loopback',lambda host:False)
    sid=active_session()['id']
    assert client.get('/api/exclusions/lera').status_code==403
    with db_session() as db:code=db.execute('SELECT access_code FROM sessions WHERE id=?',(sid,)).fetchone()[0]
    assert client.get('/api/exclusions/lera',headers={'X-Tonight-Code':code}).status_code==200
    assert client.post('/api/exclusions/lera',json={'kind':'movie','value':'arrival'}).status_code==403


def test_upgrade_from_database_without_new_schema_preserves_ratings():
    sid=active_session()['id']
    with db_session() as db:
        db.execute('INSERT INTO swipes VALUES(?,?,?,?,?)',(sid,'lera','arrival','love','now'))
        db.execute('DROP TABLE recommendation_exclusions')
        db.execute('ALTER TABLE sessions DROP COLUMN temporary_exclusions')
    initialize()
    with db_session() as db:
        assert taste_signals(db,'lera')[0]['value']==1
        assert db.execute('SELECT temporary_exclusions FROM sessions').fetchone()[0]=='{}'
    assert state_for_user('lera')['permanent']==[]


@pytest.mark.parametrize('scope',['permanent','temporary'])
def test_runtime_replaces_previous_limit_in_same_scope(scope):
    sid=active_session()['id']
    add('max_runtime','90',scope=scope,sid=sid)
    add('max_runtime','120',scope=scope,sid=sid)
    assert state_for_user('lera')[scope]==[{'kind':'max_runtime','value':'120'}]


@pytest.mark.parametrize('kind,value,field,bad,missing',[
    ('keyword','space','keywords',dumps(['space']),'[]'),
    ('director','A','director','A',None),
    ('max_runtime','120','runtime',150,None),
])
def test_characteristics_filter_before_personal_and_shared_ranking(kind,value,field,bad,missing):
    sid=active_session()['id']
    good={'keyword':dumps(['cooking']),'director':'B','max_runtime':90}[kind]
    with db_session() as db:
        db.execute(f'UPDATE movies SET {field}=?',(good,))
        db.execute(f"UPDATE movies SET {field}=? WHERE id='arrival'",(bad,))
        db.execute(f"UPDATE movies SET {field}=? WHERE id='ex-machina'",(missing,))
    assert add(kind,value).status_code==200
    for movies in [personal_recommendations('lera',200)['items'],recommend(sid,200)]:
        assert movies
        assert not {'arrival','ex-machina'} & {m['id'] for m in movies}


def test_temporary_api_requires_explicit_session_and_correct_remote_code(monkeypatch):
    from backend import main
    sid=active_session()['id']
    assert add('genre','драма',scope='temporary').status_code==422
    assert client.delete('/api/exclusions/lera?scope=temporary&clear=true').status_code==422
    new=client.post('/api/sessions/new').json()['id']
    with db_session() as db:
        db.execute("UPDATE sessions SET access_code='123456' WHERE id=?",(sid,))
        db.execute("UPDATE sessions SET access_code='654321' WHERE id=?",(new,))
    monkeypatch.setattr(main,'_is_loopback',lambda host:False)
    response=client.post('/api/exclusions/lera',headers={'X-Tonight-Code':'654321'},
        json={'kind':'genre','value':'драма','scope':'temporary','session_id':sid})
    assert response.status_code==403
    assert not state_for_user('lera',sid)['temporary']
