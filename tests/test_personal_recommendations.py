from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.database.db import db_session, dumps
from backend.main import app
from backend.recommendation.personal import personal_recommendations, rank_movies
from backend.recommendation.taste_profile import reset_profile, exclude_genre, taste_signals
from backend.recommendation.avoidance import add_avoidance
from backend.sessions.service import active_session


def movie(id, **kwargs):
    return dict(id=id, title=id, genres=[], keywords=[], cast_names=[], director=None,
                year=None, rating=None, vote_count=0, **kwargs)


def candidate(id, **kwargs):
    data = movie(id)
    data.update(kwargs)
    return data


def signal(**kwargs):
    return {**candidate('evidence', **kwargs), 'value': 1.}


@pytest.mark.parametrize('field,value', [('genres', ['драма']), ('keywords', ['космос']),
                                        ('director', 'Режиссёр'), ('cast_names', ['Актёр']), ('year', 1996)])
def test_each_personal_factor_ranks_and_explains(field, value):
    matched = candidate('matched', **{field: value})
    other = candidate('other')
    result = rank_movies([other, matched], [signal(**{field: value})])
    assert result[0]['id'] == 'matched'
    assert result[0]['personalized']
    assert result[0]['ranking_factors']
    assert not result[1]['personalized']


def test_personal_taste_outweighs_popularity_and_negative_evidence_reverses_order():
    niche = candidate('niche', genres=['драма'], rating=6, vote_count=10)
    popular = candidate('popular', rating=10, vote_count=100000)
    evidence = signal(genres=['драма'])
    assert rank_movies([popular, niche], [evidence])[0]['id'] == 'niche'
    evidence['value'] = -1
    result = rank_movies([popular, niche], [evidence])
    assert result[0]['id'] == 'popular'
    assert not result[1]['personalized']


def test_cold_start_does_not_claim_personal_match_or_invent_rating():
    result = rank_movies([candidate('rated', rating=8, vote_count=1000), candidate('unknown')], [])
    assert all(not m['personalized'] for m in result)
    assert '8.0' in result[0]['recommendation_reason']
    assert 'недостаточно данных' in result[1]['recommendation_reason']
    assert all('match' not in m for m in result)


def test_diversity_and_exposure_penalties_are_deterministic():
    films = [candidate(str(i), genres=['драма'], rating=8, vote_count=1000) for i in range(8)]
    films.append(candidate('comedy', genres=['комедия'], rating=7, vote_count=1000))
    first = rank_movies(films, [], limit=4)
    assert 'comedy' in {m['id'] for m in first[:2]}
    assert first == rank_movies(list(reversed(films)), [], limit=4)
    next_day = rank_movies(films, [], exposure={m['id']: 1 for m in first}, limit=4)
    assert next_day[0]['id'] != first[0]['id']
    assert len({m['id'] for m in next_day}) == 4


def test_empty_sparse_and_missing_metadata_respect_exclusions():
    film = candidate('unknown', genres=None, keywords=None, cast_names=None)
    assert len(rank_movies([film], [])) == 1
    assert rank_movies([film], [], excluded={'unknown'}) == []
    assert rank_movies([film], [], max_runtime=90) == []
    assert rank_movies([], []) == []
    assert rank_movies([film], [], limit=0) == []
    assert rank_movies([candidate('x', genres=['драма'])], [], blocked_genres={'драма'}) == []


def swipe(user='lera', reaction='love', movie_id='arrival'):
    session = active_session()
    with db_session() as db:
        db.execute('INSERT OR REPLACE INTO swipes(session_id,user_id,movie_id,reaction,created_at) VALUES(?,?,?,?,datetime(\'now\'))',
                   (session['id'], user, movie_id, reaction))
    return session['id']


def test_iq_is_shared_and_respects_genre_corrections_and_reset():
    swipe()
    with db_session() as db:
        assert taste_signals(db, 'lera')[0]['value'] == 1
    assert not personal_recommendations('lera')['cold_start']
    exclude_genre('lera', 'sci-fi')
    with db_session() as db:
        assert 'sci-fi' not in taste_signals(db, 'lera')[0]['genres']
    reset_profile('lera')
    assert personal_recommendations('lera')['cold_start']
    with db_session() as db:
        assert db.execute('SELECT COUNT(*) FROM swipes').fetchone()[0] == 1


def test_ratings_override_swipes_and_immediately_change_recommendations():
    session_id = swipe()
    with db_session() as db:
        history_id = db.execute("INSERT INTO watch_history(session_id,movie_id,watched_at) VALUES(?,'arrival',datetime('now'))", (session_id,)).lastrowid
    client = TestClient(app)
    response = client.post(f'/api/history/{history_id}/feedback', json={'user_id': 'lera', 'rating': 1})
    assert response.status_code == 200
    with db_session() as db:
        assert taste_signals(db, 'lera')[0]['value'] == -1
    negative = client.get('/api/recommendations/personal/lera').json()
    client.post(f'/api/history/{history_id}/feedback', json={'user_id': 'lera', 'rating': 5})
    positive = client.get('/api/recommendations/personal/lera').json()
    assert negative['items'] != positive['items']
    assert 'arrival' not in {m['id'] for m in positive['items']}


def test_hidden_disliked_rejected_and_unreleased_are_never_offered():
    session_id = swipe(reaction='dislike')
    add_avoidance('lera', 'ex-machina')
    with db_session() as db:
        db.execute('UPDATE sessions SET rejected_movies=? WHERE id=?', (dumps(['knives-out']), session_id))
        db.execute("UPDATE movies SET theatrical_release_date='2099-01-01' WHERE id='interstellar'")
    items = personal_recommendations('lera', limit=100)['items']
    assert not {'arrival', 'ex-machina', 'knives-out', 'interstellar'} & {m['id'] for m in items}


def test_api_preferences_and_users_are_isolated():
    session_id = swipe()
    with db_session() as db:
        db.execute("INSERT INTO participants(session_id,user_id,disliked_genres,moods,joined_at) VALUES(?,'lera',?, ?,datetime('now'))",
                   (session_id, dumps(['sci-fi']), dumps(['laugh'])))
    data = personal_recommendations('lera')
    assert all('sci-fi' not in m['genres'] for m in data['items'])
    assert personal_recommendations('nikita')['cold_start']
    assert TestClient(app).get('/api/recommendations/personal/unknown').status_code == 400


def test_daily_history_stability_rotation_and_bounded_storage():
    day = date(2026, 10, 15)
    first = personal_recommendations('lera', reference_day=day)
    assert first == personal_recommendations('lera', reference_day=day)
    tomorrow = personal_recommendations('lera', reference_day=day + timedelta(days=1))
    assert [m['id'] for m in first['items']] != [m['id'] for m in tomorrow['items']]
    personal_recommendations('lera', reference_day=day + timedelta(days=9))
    with db_session() as db:
        assert db.execute('SELECT MIN(day) FROM personal_impressions').fetchone()[0] > day.isoformat()


def test_missing_catalog_metadata_and_small_catalog_api():
    with db_session() as db:
        db.execute("UPDATE movies SET release_status=NULL WHERE id<>'arrival'")
        db.execute("UPDATE movies SET rating=NULL,keywords='null',cast_names='null',director=NULL WHERE id='arrival'")
    result = personal_recommendations('lera')
    assert result['limited']
    assert len(result['items']) == 1
    assert not result['items'][0]['personalized']
    with db_session() as db:
        db.execute('UPDATE movies SET release_status=NULL')
    assert personal_recommendations('lera')['items'] == []


def test_unknown_reaction_does_not_create_preference_and_new_reaction_replaces_old():
    swipe(reaction='unseen')
    assert personal_recommendations('lera')['cold_start']
    swipe(reaction='love')
    swipe(reaction='dislike')
    with db_session() as db:
        evidence = taste_signals(db, 'lera')
    assert len(evidence) == 1 and evidence[0]['value'] == -1


def test_personal_discovery_obeys_existing_franchise_order():
    with db_session() as db:
        db.execute("UPDATE movies SET franchise_key='personal-test',franchise_order=1 WHERE id='arrival'")
        db.execute("UPDATE movies SET franchise_key='personal-test',franchise_order=2 WHERE id='ex-machina'")
    assert 'ex-machina' not in {m['id'] for m in personal_recommendations('lera', limit=100)['items']}


def test_existing_evening_recommendations_count_as_recent_offers():
    day = date(2026, 10, 15)
    first = personal_recommendations('lera', reference_day=day)
    movie_id = first['items'][0]['id']
    session_id = swipe(reaction='unseen')
    with db_session() as db:
        db.execute("INSERT INTO participants(session_id,user_id,joined_at) VALUES(?,'lera',datetime('now'))", (session_id,))
        db.execute('UPDATE sessions SET recommendations=?,updated_at=? WHERE id=?',
                   (dumps([{'id': movie_id}]), '2026-10-14T20:00:00', session_id))
    second = personal_recommendations('lera', reference_day=day)
    assert first['items'][0]['id'] != second['items'][0]['id']


def test_impression_history_is_deleted_with_personal_data(tmp_path):
    from backend.config import settings
    from backend.privacy import delete_personal_data
    personal_recommendations('lera')
    with db_session() as db:
        assert db.execute('SELECT COUNT(*) FROM personal_impressions').fetchone()[0] > 0
    delete_personal_data(settings.db_path, tmp_path / 'backups')
    with db_session() as db:
        assert db.execute('SELECT COUNT(*) FROM personal_impressions').fetchone()[0] == 0
