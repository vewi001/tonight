"""Real source seed, deliberately without conftest's synthetic confirmations."""
from fastapi.testclient import TestClient

from backend.database.db import db_session
from backend.main import app
from backend.movies.catalog import eligible_movie_count, is_released
from backend.movies.seed import seed_movies
from backend.recommendation.personal import personal_recommendations


def test_clean_source_has_verified_offline_starter_for_both_profiles():
    with db_session() as db:
        db.execute('DELETE FROM movies')
    assert seed_movies() == 72
    assert eligible_movie_count() == 20
    for user in ('lera', 'nikita'):
        offers = personal_recommendations(user)
        assert offers['items']
        assert all(is_released(movie) for movie in offers['items'])
    with db_session() as db:
        assert db.execute('SELECT count(*) FROM movies WHERE russian_title IS NULL').fetchone()[0] == 52


def test_zero_eligible_catalog_never_claims_ready(monkeypatch):
    import backend.main as main
    async def no_ollama():
        return {'available': False, 'model_installed': False}
    monkeypatch.setattr(main, 'ollama_health', no_ollama)
    with db_session() as db:
        db.execute('UPDATE movies SET russian_title=NULL')
    client = TestClient(app)
    setup = client.get('/api/setup/status').json()
    assert setup['catalog'] == 72 and setup['catalog_available'] == 0
    diagnostics = client.get('/api/diagnostics').json()
    assert not diagnostics['summary']['ok']
    assert 'Нет подтверждённых фильмов' in diagnostics['summary']['text']


def test_seed_does_not_replace_previously_imported_metadata():
    with db_session() as db:
        db.execute("UPDATE movies SET source='tmdb',russian_title=NULL WHERE id='arrival'")
    seed_movies()
    with db_session() as db:
        assert db.execute("SELECT russian_title FROM movies WHERE id='arrival'").fetchone()[0] is None


def test_verified_starter_does_not_overwrite_manual_edits_or_quarantine():
    with db_session() as db:
        db.execute('DELETE FROM movies')
    seed_movies()
    with db_session() as db:
        db.execute("UPDATE movies SET tmdb_id=NULL,title='Моя правка',russian_title=NULL,release_status=NULL,release_date=NULL,theatrical_release_date=NULL,theatrical_release_type=NULL,theatrical_release_country=NULL WHERE id='arrival'")
        db.execute("UPDATE movies SET tmdb_id=NULL,russian_title=NULL WHERE id='memento'")
        before = [tuple(row) for row in db.execute("SELECT * FROM movies WHERE id IN ('arrival','memento') ORDER BY id")]
    seed_movies()
    with db_session() as db:
        assert [tuple(row) for row in db.execute("SELECT * FROM movies WHERE id IN ('arrival','memento') ORDER BY id")] == before


def test_all_five_source_choices_work_when_outbound_http_is_unavailable(monkeypatch):
    import httpx
    def offline(*args, **kwargs):
        raise httpx.ConnectError('offline test')
    async def async_offline(*args, **kwargs):
        raise httpx.ConnectError('offline test')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', offline)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', async_offline)
    with db_session() as db:
        db.execute('DELETE FROM movies')
    seed_movies()
    client = TestClient(app)
    assert client.get('/api/setup/status').json()['catalog_available'] == 20
    sid = client.get('/api/sessions/active').json()['id']
    for user in ('lera', 'nikita'):
        assert client.get(f'/api/recommendations/personal/{user}').json()['items']
        for path, payload in [
            (f'/api/search/smart/{user}', {'query': 'Детектив без ужасов до двух часов'}),
            (f'/api/roulette/{user}/pick', {}),
            (f'/api/tinder/{user}/recommendations', {'seen_ids': []}),
            (f'/api/tonight/{user}/recommendations', {'mood': 'cozy', 'company': 'solo'}),
        ]:
            response = client.post(path, json=payload)
            assert response.status_code == 200, response.text
            assert response.json()['items'], path
        assert client.post(f'/api/sessions/{sid}/preferences', json={
            'user_id': user, 'moods': ['cozy'], 'energy': 'medium',
            'max_runtime': None, 'min_year': None}).status_code == 200
        deck = client.get(f'/api/sessions/{sid}/swipe/{user}').json()
        assert deck['total'] > 0 and deck['movies']
