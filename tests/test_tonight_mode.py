import pytest
from fastapi.testclient import TestClient
from backend.main import app, TonightModeIn
from backend.database.db import db_session, dumps
from backend.recommendation.personal import personal_recommendations
from backend.recommendation.engine import MOOD_GENRES
from backend.recommendation.taste_profile import taste_signals

client = TestClient(app)
def pick(**kwargs):
    return personal_recommendations('lera', 5, tonight=TonightModeIn(**kwargs).model_dump())

@pytest.mark.parametrize('mood', ['laugh','scary','cozy','wow','smart','atmosphere','surprise'])
def test_each_mood(mood):
    data=pick(mood=mood)
    assert data['items']
    assert all(not MOOD_GENRES[mood] or set(m['genres']) & MOOD_GENRES[mood] for m in data['items'])

@pytest.mark.parametrize('runtime', [90,120,150,None])
def test_duration_and_repeated_batches_obey_constraints(runtime):
    first=pick(max_runtime=runtime)
    ids=[m['id'] for m in first['items']]
    second=pick(max_runtime=runtime,seen_ids=ids)
    assert not set(ids) & {m['id'] for m in second['items']}
    assert all(runtime is None or 0<m['runtime']<=runtime for m in first['items']+second['items'])

@pytest.mark.parametrize('company', ['solo','couple','friends','family'])
def test_company(company):
    result=pick(company=company)
    assert result['items']
    if company=='family':
        assert all(set(m['genres']) & {'семейный','мультфильм'} and not set(m['genres']) & {'хоррор','триллер'} for m in result['items'])

def test_combined_rating_year_genres_and_missing_metadata():
    result=pick(min_rating=7,min_year=2000,max_year=2020,excluded_genres=['horror','thriller'])
    assert result['items']
    assert all(m['rating']>=7 and 2000<=m['year']<=2020 and not set(m['genres']) & {'хоррор','триллер'} for m in result['items'])
    with db_session() as db:
        db.execute('UPDATE movies SET runtime=NULL,rating=NULL')
    assert not pick(max_runtime=90)['items']
    assert not pick(min_rating=1)['items']
    assert pick()['items']

def test_actions_are_persistent_idempotent_and_isolated():
    mid=pick()['items'][0]['id']
    for action in ['watchlist','watched','dislike','dislike']:
        response=client.post(f'/api/tonight/lera/movies/{mid}',json={'action':action})
        assert response.status_code==200
    with db_session() as db:
        assert db.execute('SELECT count(*) FROM viewer_movie_actions WHERE user_id=? AND movie_id=?',('lera',mid)).fetchone()[0]==2
        assert db.execute('SELECT count(*) FROM watchlist WHERE movie_id=?',(mid,)).fetchone()[0]==1
        assert any(s['id']==mid and s['value']==-1 for s in taste_signals(db,'lera'))
        assert not taste_signals(db,'nikita')
        assert db.execute('SELECT count(*) FROM watch_history').fetchone()[0]==0
    assert mid not in {m['id'] for m in pick(exclude_watched=False)['items']}

def test_watched_toggle_preserves_personal_watch_mark_without_fabricating_likes():
    mid=pick()['items'][0]['id']
    client.post(f'/api/tonight/lera/movies/{mid}',json={'action':'watched'})
    assert mid not in {m['id'] for m in pick()['items']}
    assert mid in {m['id'] for m in pick(exclude_watched=False)['items']}
    with db_session() as db:
        assert not taste_signals(db,'lera')

def test_empty_constraints_offer_actual_relaxation_and_exhaustion():
    empty=pick(min_year=2099)
    assert not empty['items']
    assert any(r['field']=='year' and r['available']>0 for r in empty['relaxations'])
    with db_session() as db:
        ids=[r[0] for r in db.execute('SELECT id FROM movies')]
    empty=pick(seen_ids=ids)
    assert empty['exhausted'] and not empty['items']

def test_pair_reads_both_profiles_and_negative_signals():
    mid=pick()['items'][0]['id']
    client.post(f'/api/tonight/nikita/movies/{mid}',json={'action':'dislike'})
    assert mid not in {m['id'] for m in pick(company='couple')['items']}
    assert mid in {m['id'] for m in pick(company='solo')['items']}

@pytest.mark.parametrize('payload', [{'max_runtime':40},{'min_rating':11},{'mood':'bad'},{'company':'bad'},{'min_year':2020,'max_year':2000},{'min_year':1800}])
def test_invalid_filters(payload):
    assert client.post('/api/tonight/lera/recommendations',json=payload).status_code==422

def test_api_users_movies_and_unknown_actions():
    assert client.post('/api/tonight/unknown/recommendations',json={}).status_code==400
    assert client.post('/api/tonight/lera/movies/unknown',json={'action':'watched'}).status_code==404
    assert client.post('/api/tonight/lera/movies/arrival',json={'action':'like'}).status_code==422
    assert client.post('/api/tonight/lera/recommendations',json={}).status_code==200

def test_iq_reset_clears_learning_but_preserves_explicit_disinterest():
    from backend.recommendation.taste_profile import reset_profile
    mid=pick()['items'][0]['id']
    client.post(f'/api/tonight/lera/movies/{mid}',json={'action':'dislike'})
    reset_profile('lera')
    with db_session() as db:
        assert not taste_signals(db,'lera')
    assert mid not in {m['id'] for m in pick()['items']}

def test_pair_excludes_other_viewers_watched_movies():
    mid=pick()['items'][0]['id']
    client.post(f'/api/tonight/nikita/movies/{mid}',json={'action':'watched'})
    assert mid not in {m['id'] for m in pick(company='couple')['items']}
    assert mid in {m['id'] for m in pick(company='solo')['items']}
