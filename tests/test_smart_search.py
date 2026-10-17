"""Query grammar, real filtering, existing IQ/policies and the protected API."""
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.database.db import db_session, dumps
from backend.main import app
from backend.movies.catalog import search_movies
from backend.movies.search_query import SearchCriteria, SmartSearchIn, conflicts, interpret, refine, _interpret
from backend.movies.smart_search import search, source_candidates, theme_evidence
from backend.recommendation.avoidance import add_avoidance
from backend.recommendation.exclusions import change_rule
from backend.recommendation.taste_profile import taste_signals
from backend.sessions.service import active_session, session_access_code


def query(text='', criteria=None, **kwargs):
    return search('lera', SmartSearchIn(query=text, criteria=criteria, **kwargs))


@pytest.mark.parametrize('text,expected', [
    ('Хочу детектив', ['детектив']), ('комедию', ['комедия']), ('научную фантастику', ['sci-fi']),
    ('ужасы', ['хоррор']), ('романтический фильм', ['романтика']), ('анимацию', ['мультфильм']),
    ('боевик и приключения', ['боевик', 'приключения']),
])
def test_genre_synonyms(text, expected):
    assert interpret(text)['criteria'].hard.genres == expected


@pytest.mark.parametrize('text,excluded', [
    ('Без ужасов', ['хоррор']), ('Без фантастики', ['sci-fi']), ('Не хочу ужасы', ['хоррор']),
    ('без ужасов и фантастики', ['хоррор', 'sci-fi']), ('без ужасов, фантастики', ['хоррор', 'sci-fi']),
    ('без мистики и ужасов', ['хоррор']),
])
def test_negations(text, excluded):
    c = interpret(text)['criteria']
    assert c.hard.excluded_genres == excluded
    assert c.hard.genres == []


def test_negation_ends_with_clause_and_absence_is_not_prohibition():
    c = interpret('без ужасов, но комедию')['criteria']
    assert c.hard.excluded_genres == ['хоррор']
    assert c.hard.genres == ['комедия']
    assert not interpret('детектив')['criteria'].hard.exclude_watched
    assert not interpret('детектив')['criteria'].hard.excluded_genres


@pytest.mark.parametrize('text,minutes', [('полтора часа', 90), ('90 минут', 90), ('до двух часов', 120),
    ('не больше 100 минут', 100), ('не более 100 минут', 100), ('1 час 30 минут', 90),
    ('до 1,5 часов', 90), ('короче 100 минут', 99)])
def test_duration(text, minutes):
    assert interpret(text)['criteria'].hard.max_runtime == minutes


def test_runtime_range_and_intersection():
    c = interpret('от 90 до 120 минут')['criteria']
    assert (c.hard.min_runtime, c.hard.max_runtime) == (90, 120)
    c = interpret('до двух часов, не больше 100 минут')['criteria']
    assert c.hard.max_runtime == 100


@pytest.mark.parametrize('text,low,high', [('не старше 2010 года', 2010, None), ('после 2015 года', 2016, None),
    ('с 2010 по 2020 год', 2010, 2020), ('2010–2020', 2010, 2020), ('до 2000 года', None, 1999),
    ('в 2019 году', 2019, 2019), ('не позже 2020 года', None, 2020)])
def test_years(text, low, high):
    c = interpret(text)['criteria'].hard
    assert (c.min_year, c.max_year) == (low, high)


def test_combination_and_unsupported_traits_are_honest():
    data = interpret('Хочу напряжённый детектив без мистики до двух часов')
    c = data['criteria']
    assert c.hard.genres == ['детектив']
    assert c.soft.themes == ['tense']
    assert c.hard.max_runtime == 120
    assert c.hard.excluded_genres == []  # mysticism is not the mystery genre
    assert any('мистик' in note for note in data['notes'])
    assert 'без' not in data['unparsed']


def test_unknown_typos_and_empty_do_not_return_fake_popular_films():
    for text in ('', '   ', 'абракадабра', 'коммедия', 'что-нибудь попроще', 'менее мрачным'):
        assert not query(text)['items']
    data = query('детектив абракадабра')
    assert data['items']
    assert data['unparsed'] == 'абракадабра'
    assert query('без космоса')['items'] == []


def test_rating_and_watched_grammar():
    c = interpret('Весёлую комедию после 2015 года с хорошим рейтингом')['criteria']
    assert c.hard.min_rating == 7
    assert c.hard.min_year == 2016
    assert c.soft.themes == ['funny']
    assert interpret('рейтинг от 8,2')['criteria'].hard.min_rating == 8.2
    assert interpret('Фантастику про космос, которую я ещё не смотрел')['criteria'].hard.exclude_watched


def test_limits_models_and_cache_do_not_leak_mutations():
    with pytest.raises(ValidationError):
        SmartSearchIn(query='x' * 501)
    with pytest.raises(ValueError):
        interpret('x' * 501)
    with pytest.raises(ValidationError):
        SearchCriteria.model_validate({'hard': {'genres': ['imaginary']}})
    with pytest.raises(ValidationError):
        SearchCriteria.model_validate({'hard': {'min_rating': float('nan')}})
    a = interpret('детектив')['criteria']
    a.hard.genres.clear()
    assert interpret('детектив')['criteria'].hard.genres == ['детектив']
    for n in range(280):
        interpret(f'детектив {n}')
    assert _interpret.cache_info().currsize <= 256


def test_conflicts_fail_closed():
    for text in ('комедия без комедии', 'после 2020 года до 2010 года', 'не меньше 120 минут до 90 минут'):
        data = query(text)
        assert data['conflicts']
        assert not data['items']


def test_hard_limits_hold_for_every_result_and_queries_differ():
    data = query('комедию без ужасов до двух часов после 2015 года рейтинг от 7')
    assert data['items']
    for m in data['items']:
        assert 'комедия' in m['genres'] and 'хоррор' not in m['genres']
        assert m['runtime'] <= 120 and m['year'] >= 2016 and m['rating'] >= 7
        assert m['search_reasons']
        assert 'атмосфер' not in ' '.join(m['search_reasons'])
        assert m['rating_source'] is None  # seed scores have no verified source
    comedies = {m['id'] for m in query('комедия')['items']}
    horror = {m['id'] for m in query('ужасы')['items']}
    assert comedies != horror


def test_missing_mandatory_metadata_never_matches():
    with db_session() as db:
        db.execute("UPDATE movies SET runtime=NULL, genres='[]', rating=NULL WHERE id='palm-springs'")
    for text in ('до 120 минут', 'без ужасов', 'рейтинг от 7'):
        assert 'palm-springs' not in {m['id'] for m in query(text)['items']}


def test_no_results_diagnostics_and_no_silent_relaxation():
    data = query('детектив до 1 минуты')
    assert not data['items'] and data['diagnostics']
    assert any(d['excluded'] > 0 for d in data['diagnostics'])
    assert data['criteria']['hard']['max_runtime'] == 1


def test_similar_known_title_uses_real_metadata_and_excludes_source():
    data = query('Что-то похожее на Прибытие, но попроще')
    assert not data['needs_source'] and data['items']
    assert data['source']['id'] == 'arrival'
    assert all(m['id'] != 'arrival' for m in data['items'])
    assert any('попроще' in note for note in data['notes'])
    for m in data['items']:
        assert any('Сходство' in r for r in m['search_reasons'])
        assert not any('сходство по атмосфере' in r.casefold() or 'похожий финал' in r.casefold() for r in m['search_reasons'])


def test_ambiguous_titles_and_typos_require_choice():
    with db_session() as db:
        db.execute("UPDATE movies SET title='Прибытие',russian_title='Прибытие' WHERE id='knives-out'")
    data = query('похожее на Прибытие')
    assert data['needs_source'] and not data['items']
    assert {m['id'] for m in data['sources']} == {'arrival', 'knives-out'}
    c = SearchCriteria.model_validate(data['criteria'])
    c.soft.source_id = 'arrival'
    chosen = query('похожее на Прибытие', criteria=c)
    assert not chosen['needs_source'] and chosen['source']['id'] == 'arrival'
    typo = query('похожее на Прибыте')
    assert typo['needs_source'] and typo['sources'] and not typo['items']
    assert query('похожее на неизвестный фильм')['needs_source']


def test_genre_word_in_reference_title_is_not_a_filter():
    c = interpret('похожее на «Боевик», но без ужасов')['criteria']
    assert c.soft.similar_title == 'боевик'
    assert c.hard.genres == [] and c.hard.excluded_genres == ['хоррор']


def test_themes_and_moods_need_literal_catalog_evidence():
    assert theme_evidence({'keywords': ['космос']}, 'space')
    assert not theme_evidence({'overview': 'Захватывающий фильм.'}, 'tense')
    assert not theme_evidence({'overview': 'Удивительный финал.'}, 'twists')
    for text, theme in [('про космос', 'space'), ('лёгкое на вечер вдвоём', 'light'),
                         ('фильм с неожиданными поворотами', 'twists')]:
        data = query(text)
        assert data['items']
        assert all(theme_evidence(m, theme) for m in data['items'])


def test_iq_ranks_inside_explicit_genre_and_respects_existing_avoidance():
    sid = active_session()['id']
    with db_session() as db:
        db.execute('INSERT INTO swipes VALUES(?,?,?,?,?)', (sid, 'lera', 'arrival', 'love', 'now'))
        evidence = taste_signals(db, 'lera')
    data = query('комедия')
    assert all('комедия' in m['genres'] for m in data['items'])
    assert not data['cold_start']
    assert any(m['personalized'] for m in data['items'])
    add_avoidance('lera', data['items'][0]['id'])
    changed = query('комедия')
    assert changed['items'][0]['id'] != data['items'][0]['id']
    assert data['items'][0]['id'] not in {m['id'] for m in changed['items']}
    with db_session() as db:
        assert taste_signals(db, 'lera') == evidence


def test_policies_watched_expiry_and_fresh_results_after_same_query():
    sid = active_session()['id']
    before = query('комедия')
    blocked = before['items'][0]['id']
    change_rule('lera', 'permanent', kind='movie', value=blocked)
    change_rule('lera', 'temporary', kind='genre', value='романтика', session_id=sid)
    after = query('комедия')
    assert blocked not in {m['id'] for m in after['items']}
    assert all('романтика' not in m['genres'] for m in after['items'])
    watched = after['items'][0]['id']
    with db_session() as db:
        db.execute("INSERT INTO viewer_movie_actions VALUES(?,?,?,?)", ('lera', watched, 'watched', 'now'))
    assert watched not in {m['id'] for m in query('комедия которую я не смотрел')['items']}
    # No condition means watched is allowed unless policy says otherwise.
    assert watched in {m['id'] for m in query('комедия')['items']}
    with db_session() as db:
        db.execute("UPDATE sessions SET status='completed' WHERE id=?", (sid,))
    assert query('комедия')['policies']['temporary'] == 0
    assert query('комедия')['policies']['permanent'] == 1


def test_edit_one_criterion_and_refine_keep_other_conditions():
    c = interpret('детектив без ужасов до двух часов')['criteria']
    c.hard.max_runtime = 100
    edited = query('детектив без ужасов до двух часов', criteria=c)
    assert edited['criteria']['hard']['max_runtime'] == 100
    assert all(m['runtime'] <= 100 for m in edited['items'])
    data = query('только после 2020 года', criteria=c, refine=True)
    assert data['criteria']['hard']['genres'] == ['детектив']
    assert data['criteria']['hard']['excluded_genres'] == ['хоррор']
    assert data['criteria']['hard']['max_runtime'] == 100
    assert data['criteria']['hard']['min_year'] == 2021
    unchanged = query('сделай менее мрачным', criteria=c, refine=True)
    assert unchanged['criteria'] == c.model_dump()
    assert unchanged['notes']


def test_safe_text_unchanged_title_search_and_read_only_api():
    client = TestClient(app)
    before = [m['id'] for m in search_movies('Достать ножи')]
    response = client.post('/api/search/smart/lera', json={'query': "комедия; DROP TABLE movies; <script>alert(1)</script>"})
    assert response.status_code == 200
    assert response.json()['unparsed']
    assert [m['id'] for m in search_movies('Достать ножи')] == before
    assert client.get('/api/movies/search', params={'q': 'Достать ножи'}).json()['items'][0]['id'] == before[0]
    assert client.post('/api/search/smart/lera', json={'query': 'a' * 501}).status_code == 422
    assert client.post('/api/search/smart/unknown', json={'query': 'комедия'}).status_code == 400
    assert client.post('/api/search/smart/lera', json={'criteria': {'hard': {'max_runtime': -1}}}).status_code == 422


def test_remote_search_requires_existing_evening_code():
    sid = active_session()['id']
    remote = TestClient(app, client=('192.168.1.55', 5555))
    assert remote.post('/api/search/smart/lera', json={'query': 'комедия'}).status_code == 403
    assert remote.post('/api/search/smart/lera', json={'query': 'комедия'},
                       headers={'X-Tonight-Code': session_access_code(sid)}).status_code == 200
