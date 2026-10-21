from datetime import date

import pytest

from backend.movies.catalog import is_released


def verified(**changes):
    return dict(id='verified',title='Подтверждённый фильм',russian_title='Подтверждённый фильм',
        original_title='Original',year=2020,release_date='2020-01-01',release_status='Released',
        theatrical_release_date='2020-01-03',theatrical_release_type=3,
        theatrical_release_country='US',**changes)


@pytest.mark.parametrize('field,value',[
    ('russian_title',None),('russian_title',''),('russian_title','Other title'),
    ('release_status',None),('release_status','In Production'),
    ('theatrical_release_date',None),('theatrical_release_date','2099-01-01'),
    ('theatrical_release_date','2020'),('theatrical_release_date','2020-02-30'),
    ('theatrical_release_type',1),('theatrical_release_type',4),('theatrical_release_type',5),
    ('theatrical_release_type',6),('theatrical_release_type',True),
    ('theatrical_release_country',None),('theatrical_release_country','invalid'),
])
def test_unconfirmed_movies_never_eligible(field,value):
    movie=verified(); movie[field]=value
    assert not is_released(movie,date(2026,10,14))


def test_legacy_year_or_general_date_is_not_proof():
    assert not is_released(dict(title='Русское название',year=1990),date(2026,10,14))
    assert not is_released(dict(title='Русское название',year=1990,release_date='1990-01-01'),date(2026,10,14))


@pytest.mark.parametrize('release_type',[2,3])
def test_confirmed_theatrical_release_with_official_russian_name(release_type):
    movie=verified(); movie['theatrical_release_type']=release_type
    assert is_released(movie,date(2026,10,14))
    movie['theatrical_release_date']='2026-10-14'
    assert is_released(movie,date(2026,10,14))
    movie['theatrical_release_date']='2026-10-15'
    assert not is_released(movie,date(2026,10,14))


def test_explicit_russian_translation_is_required_not_just_language_parameter():
    from scripts.import_tmdb import verified_availability
    detail=dict(id=1,title='English fallback',original_title='English fallback',original_language='en',status='Released',
        translations={'translations':[]},release_dates={'results':[{'iso_3166_1':'US','release_dates':[
            {'type':3,'release_date':'2020-01-03T00:00:00.000Z'}]}]})
    assert verified_availability(detail,date(2026,10,14)) is None

    detail['translations']['translations']=[{'iso_639_1':'ru','iso_3166_1':'RU','data':{'title':'Русское название'}}]
    result=verified_availability(detail,date(2026,10,14))
    assert result['russian_title']=='Русское название' and result['theatrical_release_date']=='2020-01-03'
    detail['release_dates']['results'][0]['release_dates'][0]['type']=4
    assert verified_availability(detail,date(2026,10,14)) is None


@pytest.mark.parametrize('field,value',[
    ('russian_title',None),('theatrical_release_date',None),('theatrical_release_date','2099-01-01'),
    ('theatrical_release_type',1),('theatrical_release_type',4),('release_status','In Production'),
])
def test_all_offers_and_selection_routes_reject_unconfirmed_but_keep_saved_rows(field,value):
    from tests.http_client import TestClient
    from backend.database.db import db_session, dumps
    from backend.main import app
    from backend.movies.catalog import get_movie, search_movies
    from backend.movies.franchises import franchises
    from backend.recommendation.engine import recommend
    from backend.recommendation.weekly import weekly_picks
    from backend.sessions.service import active_session, get_deck, session_state
    client=TestClient(app)
    session=active_session(); session_id=session['id']
    bad=get_movie('arrival'); bad['match']=90
    with db_session() as db:
        db.execute(f'UPDATE movies SET {field}=? WHERE id=?',(value,'arrival'))
        db.execute("UPDATE movies SET franchise_key='availability-series',franchise_order=1 WHERE id='arrival'")
        db.execute("UPDATE movies SET franchise_key='availability-series',franchise_order=2 WHERE id='ex-machina'")
        db.execute("INSERT INTO watchlist(movie_id,saved_at) VALUES('arrival','synthetic')")
        db.execute("UPDATE sessions SET recommendations=?,status='recommended' WHERE id=?",(dumps([bad]),session_id))
        db.execute("INSERT INTO watch_history(id,movie_id,watched_at) VALUES(999,'ex-machina','synthetic')")
        db.execute("INSERT INTO feedback VALUES(999,'lera',5,'synthetic')")
    assert 'arrival' not in {m['id'] for m in search_movies('Прибытие')}
    assert 'arrival' not in {m['id'] for m in get_deck(session_id,'lera')[0]}
    assert 'arrival' not in {m['id'] for m in recommend(session_id)}
    assert 'arrival' not in {m['id'] for m in weekly_picks()}
    assert not session_state(session_id)['recommendations']
    for group in franchises():
        assert group['next_movie'] is None or group['next_movie']['id']!='arrival'
    saved=client.get('/api/watchlist').json()
    assert not saved['items'] and saved['hidden_unverified_count']==1
    assert not client.get('/api/movies/search',params={'q':'Прибытие'}).json()['items']
    for route in ('select','select-saved','select-catalog'):
        response=client.post(f'/api/sessions/{session_id}/{route}/arrival')
        assert response.status_code==409,(route,response.text)
    with db_session() as db:
        assert db.execute("SELECT * FROM watchlist WHERE movie_id='arrival'").fetchone()
        assert db.execute("SELECT rating FROM feedback WHERE history_id=999").fetchone()[0]==5
        assert db.execute("SELECT movie_id FROM watch_history WHERE id=999").fetchone()[0]=='ex-machina'
        assert db.execute("SELECT recommendations FROM sessions WHERE id=?",(session_id,)).fetchone()[0]==dumps([bad])


def test_cached_recommendation_uses_confirmed_current_russian_name():
    from backend.database.db import db_session,dumps
    from backend.movies.catalog import get_movie
    from backend.sessions.service import active_session,session_state,choose_movie
    session_id=active_session()['id']
    movie=get_movie('arrival'); movie.update(title='Old English fallback',match=90)
    with db_session() as db:
        db.execute("UPDATE sessions SET recommendations=? WHERE id=?",(dumps([movie]),session_id))
    assert session_state(session_id)['recommendations'][0]['title']==get_movie('arrival')['russian_title']
    assert choose_movie(session_id)['title']==get_movie('arrival')['russian_title']


def test_old_selected_movie_is_hidden_from_offers_without_deleting_selection_or_history():
    from backend.database.db import db_session
    from backend.sessions.service import active_session,session_state
    session_id=active_session()['id']
    with db_session() as db:
        db.execute("UPDATE sessions SET selected_movie_id='arrival',status='selected' WHERE id=?",(session_id,))
        db.execute("UPDATE movies SET russian_title=NULL WHERE id='arrival'")
    assert session_state(session_id)['selected'] is None
    with db_session() as db:
        assert db.execute('SELECT selected_movie_id FROM sessions WHERE id=?',(session_id,)).fetchone()[0]=='arrival'
        db.execute("UPDATE sessions SET status='completed' WHERE id=?",(session_id,))
    assert session_state(session_id)['selected']['id']=='arrival'


def test_production_seed_does_not_fabricate_proof(monkeypatch,tmp_path):
    from types import SimpleNamespace
    import backend.database.db as database_module
    from backend.database.db import initialize,db_session
    from backend.movies.seed import seed_movies
    monkeypatch.setattr(database_module,'settings',SimpleNamespace(db_path=tmp_path/'isolated.db'))
    initialize(); seed_movies()
    with db_session() as db:
        assert db.execute('SELECT COUNT(*) FROM movies').fetchone()[0]>0
        from backend.movies.starter_verified import VERIFIED_STARTER
        rows = [dict(row) for row in db.execute('SELECT * FROM movies')]
        assert {row['id'] for row in rows if is_released(row)} == {proof['id'] for proof in VERIFIED_STARTER}
        for row in rows:
            if row['id'] not in {proof['id'] for proof in VERIFIED_STARTER}:
                assert row['russian_title'] is None and row['theatrical_release_date'] is None


def test_verified_metadata_survives_catalog_package_and_requires_new_reader(tmp_path):
    from contextlib import closing
    from backend.database.db import initialize,connect
    from backend.catalog_package import build_catalog_package,read_catalog_package,CatalogPackageError
    from backend.catalog_install import install_catalog
    from backend.auto_update import AvailableUpdate
    import hashlib
    source=tmp_path/'source'; initialize(source/'tonight.db')
    movie=verified(); movie.update(genres='[]',runtime=100,rating=8,vote_count=100)
    with closing(connect(source/'tonight.db')) as db:
        fields=list(movie)
        db.execute(f"INSERT INTO movies({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",list(movie.values())); db.commit()
    with pytest.raises(CatalogPackageError):
        build_catalog_package(source,tmp_path/'old.zip',version='8.0.0',min_app_version='1.6.7')
    archive=build_catalog_package(source,tmp_path/'new.zip',version='8.0.0',min_app_version='1.6.8')
    package=read_catalog_package(archive,app_version='1.6.8')
    assert is_released(package.movies[0])
    root=tmp_path/'app'; root.mkdir(); initialize(root/'data/tonight.db')
    candidate=AvailableUpdate('8.0.0','Tonight-catalog-8.0.0.zip',archive.stat().st_size,
        hashlib.sha256(archive.read_bytes()).hexdigest(),'https://github.com/vewi001/tonight/releases/download/catalog-v8.0.0/Tonight-catalog-8.0.0.zip')
    install_catalog(root,archive,candidate,app_version='1.6.8')
    with closing(connect(root/'data/tonight.db')) as db:
        row=db.execute('SELECT * FROM movies').fetchone()
        assert row['russian_title']==movie['russian_title'] and row['theatrical_release_type']==3
