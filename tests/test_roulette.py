import random
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from backend.main import app, RouletteIn
from backend.database.db import db_session, dumps
from backend.recommendation.personal import personal_recommendations
from backend.recommendation.roulette import weighted_pick
from backend.recommendation.taste_profile import taste_signals

client = TestClient(app)


def pick(**kwargs):
    options = RouletteIn(**kwargs).model_dump()
    return personal_recommendations('lera', 1, tonight=options, roulette=options)


@pytest.mark.parametrize('mode', ['smart', 'surprise', 'watchlist'])
def test_modes_use_catalog_and_no_repeats_until_exhaustion(mode):
    with db_session() as db:
        db.execute("INSERT INTO watchlist(movie_id,saved_at,saved_by) SELECT id,'now','lera' FROM movies")
    seen = []
    for _ in range(1000):
        data = pick(mode=mode, seen_ids=seen)
        if not data['items']:
            break
        movie = data['items'][0]
        assert movie['id'] not in seen
        assert movie['recommendation_reason']
        seen.append(movie['id'])
    else:
        pytest.fail('Pool did not exhaust')
    assert len(seen) > 5
    assert data['exhausted']


def test_watchlist_empty_single_and_filtered_never_falls_back():
    assert pick(mode='watchlist')['watchlist_count'] == 0
    assert not pick(mode='watchlist')['items']
    mid = pick()['items'][0]['id']
    client.post(f'/api/tonight/lera/movies/{mid}', json={'action':'watchlist'})
    assert pick(mode='watchlist')['items'][0]['id'] == mid
    assert not pick(mode='watchlist', seen_ids=[mid])['items']
    assert not pick(mode='watchlist', min_year=2099)['items']


@pytest.mark.parametrize('mode', ['smart', 'surprise', 'watchlist'])
def test_all_constraints_apply_together_and_hidden_never_appear(mode):
    with db_session() as db:
        db.execute("INSERT INTO watchlist(movie_id,saved_at,saved_by) SELECT id,'now','lera' FROM movies")
        db.execute("UPDATE movies SET runtime=110,rating=8,year=2010,genres=?", (dumps(['комедия']),))
        ids = [r[0] for r in db.execute('SELECT id FROM movies ORDER BY id LIMIT 7')]
        db.execute('UPDATE movies SET runtime=NULL WHERE id=?', (ids[0],))
        db.execute('UPDATE movies SET rating=NULL WHERE id=?', (ids[1],))
        db.execute('UPDATE movies SET russian_title=NULL WHERE id=?', (ids[2],))
        db.execute('UPDATE movies SET genres=? WHERE id=?', (dumps(['комедия','хоррор']),ids[3]))
        db.execute('UPDATE movies SET year=1990 WHERE id=?', (ids[4],))
        db.execute('UPDATE movies SET runtime=130 WHERE id=?', (ids[5],))
        db.execute('UPDATE movies SET rating=6 WHERE id=?', (ids[6],))
    options=dict(mode=mode,max_runtime=120,min_rating=7,min_year=2000,max_year=2020,
                 included_genres=['comedy'],excluded_genres=['horror'])
    seen=[]
    while True:
        result=pick(**options,seen_ids=seen)
        if not result['items']: break
        m=result['items'][0]
        assert m['id'] not in ids
        assert m['runtime']<=120 and m['rating']>=7 and 2000<=m['year']<=2020
        assert 'комедия' in m['genres'] and 'хоррор' not in m['genres']
        seen.append(m['id'])
    assert seen


def test_watched_dislike_and_iq_sync():
    mid=pick()['items'][0]['id']
    client.post(f'/api/tonight/lera/movies/{mid}',json={'action':'watched'})
    with db_session() as db:
        assert not taste_signals(db,'lera')
        assert db.execute('SELECT count(*) FROM watch_history').fetchone()[0]==0
    with db_session() as db:
        all_ids=[r[0] for r in db.execute('SELECT id FROM movies')]
    others=[x for x in all_ids if x!=mid]
    assert not pick(seen_ids=others)['items']
    assert pick(seen_ids=others,exclude_watched=False)['items'][0]['id']==mid
    client.post(f'/api/tonight/lera/movies/{mid}',json={'action':'dislike'})
    assert not pick(seen_ids=others,exclude_watched=False)['items']
    with db_session() as db:
        assert any(s['id']==mid and s['value']==-1 for s in taste_signals(db,'lera'))
        assert not taste_signals(db,'nikita')


def test_saved_preferences_are_intersected_and_surprise_has_no_hard_mood():
    from backend.sessions.service import active_session, ensure_participant
    session=active_session()
    ensure_participant(session['id'],'lera')
    with db_session() as db:
        db.execute('UPDATE participants SET min_year=2000,max_runtime=120,disliked_genres=?,moods=? WHERE user_id=?',
                   (dumps(['хоррор']),dumps(['laugh']),'lera'))
    seen=[]
    while True:
        data=pick(mode='surprise', max_runtime=150, min_year=1900, seen_ids=seen)
        if not data['items']: break
        m=data['items'][0]
        assert m['year']>=2000 and m['runtime']<=120 and 'хоррор' not in m['genres']
        seen.append(m['id'])
    assert seen


def test_sampling_prefers_iq_but_surprise_is_more_diverse():
    items=[{'id':'high','recommendation_score':.6},{'id':'low','recommendation_score':0}]
    smart=Counter(weighted_pick(items,'smart',random.Random(i))['id'] for i in range(3000))
    surprise=Counter(weighted_pick(items,'surprise',random.Random(i))['id'] for i in range(3000))
    assert 0 < smart['low'] < surprise['low']
    assert smart['high'] > surprise['high'] > surprise['low'] > 500


@pytest.mark.parametrize('payload', [{'mode':'bad'},{'max_runtime':0},{'min_rating':11},
    {'min_year':2020,'max_year':2000},{'company':'couple'},{'min_year':1800}])
def test_api_validation(payload):
    assert client.post('/api/roulette/lera/pick',json=payload).status_code==422


def test_api_unknown_viewer_and_records_only_chosen_impression():
    assert client.post('/api/roulette/unknown/pick',json={}).status_code==400
    response=client.post('/api/roulette/lera/pick',json={})
    assert response.status_code==200
    data=response.json()
    assert len(data['items'])==1 and data['candidate_count']>1
    with db_session() as db:
        assert db.execute('SELECT count(*) FROM personal_impressions').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM viewer_movie_actions').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM watch_history').fetchone()[0]==0
