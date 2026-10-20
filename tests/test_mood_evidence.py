"""Editorial control set: catalog premises, including comedy about atrocities.

These expectations are independent of the implementation's genre mapping.
Being an eligible candidate is deliberately not a certification of cozy tone.
"""
import json
from pathlib import Path

import pytest
from backend.database.db import db_session, dumps
from backend.main import TonightModeIn
from backend.recommendation.personal import personal_recommendations

CONTROL = json.loads((Path(__file__).parent / 'fixtures/mood_control.json').read_text(encoding='utf-8'))['items']


@pytest.mark.parametrize('case', CONTROL, ids=lambda c: c['movie']['id'])
def test_catalog_premise_and_uncertainty_control(case):
    m = case['movie']
    with db_session() as db:
        db.execute('DELETE FROM movies')
        db.execute('''INSERT INTO movies(id,title,russian_title,overview,genres,keywords,year,runtime,
            rating,vote_count,release_status,theatrical_release_date,theatrical_release_type,theatrical_release_country)
            VALUES(?,?,?,?,?,?,?,?,8,1000,'Released','2000-01-01',3,'US')''',
            (m['id'],m['title'],m['title'],m['overview'],dumps(m['genres']),dumps(m['keywords']),m['year'],m['runtime']))
    result = personal_recommendations('lera', 5, tonight=TonightModeIn(mood='cozy',company='solo').model_dump())
    assert bool(result['items']) is case['cozy_candidate']
    if result['items']:
        reason = result['items'][0]['recommendation_reason']
        assert 'Приблизительно' in reason and 'не подтверждён' in reason
        assert not result['items'][0]['personalized']


@pytest.mark.parametrize('overview,keywords', [
    ('Семья оказывается в концлагере.', []),
    ('История дружбы.', ['holocaust (shoah)', 'feel-good']),
    ('Комедия о смертельно больном человеке.', ['friendship']),
    ('История на фоне войны.', ['family']),
])
@pytest.mark.parametrize('mood', ['cozy','laugh'])
def test_light_discovery_never_overrules_explicit_heavy_subjects(overview, keywords, mood):
    from backend.recommendation.mood import mood_evidence
    movie = {'genres':['комедия','семейный'], 'overview':overview, 'keywords':keywords}
    assert not mood_evidence(movie, mood, {'комедия','семейный'})[0]


def test_attributed_theme_is_evidence_not_a_guarantee_and_missing_data_is_uncertain():
    from backend.recommendation.mood import mood_evidence
    movie = {'genres':['комедия'], 'keywords':['feel-good']}
    yes, weight, reason = mood_evidence(movie, 'cozy', {'комедия'})
    assert yes and weight > 0 and '«feel-good»' in reason and 'не гарантия' in reason
    movie['keywords'] = []
    assert 'не подтверждён' in mood_evidence(movie, 'cozy', {'комедия'})[2]


def test_cozy_does_not_relax_runtime_year_genres_or_watched_for_positive_tag():
    with db_session() as db:
        db.execute("UPDATE movies SET keywords=?,runtime=121,year=1999", (dumps(['feel-good']),))
    filters=TonightModeIn(mood='cozy',company='solo',max_runtime=120,min_year=2000).model_dump()
    assert not personal_recommendations('lera',5,tonight=filters)['items']
    with db_session() as db:
        db.execute('UPDATE movies SET runtime=90,year=2020,genres=?', (dumps(['комедия']),))
        db.execute("INSERT INTO viewer_movie_actions(user_id,movie_id,action,created_at) SELECT 'lera',id,'watched',CURRENT_TIMESTAMP FROM movies")
    assert not personal_recommendations('lera',5,tonight=filters)['items']
    filters['exclude_watched']=False
    filters['excluded_genres']=['комедия']
    assert not personal_recommendations('lera',5,tonight=filters)['items']
