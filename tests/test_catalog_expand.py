import io
import json
import socket
import sqlite3
import ssl

import httpx
import pytest
from PIL import Image
from tests.http_client import TestClient

from backend.database.db import initialize,connect
from backend.movies.catalog_expand import CatalogExpansion,ExpansionError
from backend.movies.catalog import is_released
from backend.update_guard import acquire_update_lease,UpdateGuardError


def provider(request):
    if request.url.host=='image.tmdb.org':
        assert 'authorization' not in request.headers
        stream=io.BytesIO();Image.new('RGB',(10,10),'red').save(stream,format='PNG')
        return httpx.Response(200,content=stream.getvalue())
    assert request.headers['Authorization']=='Bearer app-test-token'
    if request.url.path.endswith(('/top_rated','/popular','/week')):
        page=int(request.url.params.get('page','1'))
        return httpx.Response(200,json={'total_pages':500,'results':[{'id':910000+page*100+i,'poster_path':'/test.png'} for i in range(20)]})
    movie_id=int(request.url.path.rsplit('/',1)[1])
    return httpx.Response(200,json=dict(id=movie_id,title='Фильм '+str(movie_id),original_title='Film '+str(movie_id),
        original_language='en',release_date='2000-01-01',status='Released',runtime=100,vote_average=7.5,vote_count=100,
        genres=[{'id':35,'name':'Комедия'}],poster_path='/test.png',translations={'translations':[
            {'iso_639_1':'ru','iso_3166_1':'RU','data':{'title':'Фильм '+str(movie_id)}}]},
        release_dates={'results':[{'iso_3166_1':'US','release_dates':[{'type':3,'release_date':'2000-01-01T00:00:00Z'}]}]}))


def expansion(tmp_path, handler=provider):
    database=tmp_path/'data/tonight.db';initialize(database)
    manager=CatalogExpansion(tmp_path,database,lambda:'app-test-token',
        client_factory=lambda:httpx.Client(transport=httpx.MockTransport(handler)))
    return manager,database


def test_adds_released_movies_posters_and_next_click_continues(tmp_path,monkeypatch):
    manager,database=expansion(tmp_path)
    monkeypatch.setattr(manager.cancelled,'wait',lambda _:False)
    with connect(database) as db:
        db.execute("insert or replace into app_meta values('catalog_version','1.2.0')")
    manager.reserve(20);manager.run()
    assert manager.status()['phase']=='done'
    assert manager.status()['added']==manager.status()['posters']==20
    with connect(database) as db:
        assert all(is_released(dict(r)) for r in db.execute('select * from movies'))
        assert db.execute("select value from app_meta where key='catalog_version'").fetchone()[0]=='1.2.0'
        first=db.execute('select id from movies limit 1').fetchone()[0]
        db.execute('update movies set overview=? where id=?',('My personal edit',first))
        db.execute("insert into watchlist(movie_id,saved_at,saved_by) values(?,'today','lera')",(first,))
    (tmp_path/'data/posters'/f'{first}.png').write_bytes(b'my existing image')
    manager.reserve(20);manager.run()
    with connect(database) as db:
        assert db.execute('select count(*) from movies').fetchone()[0]==40
        assert db.execute('select overview from movies where id=?',(first,)).fetchone()[0]=='My personal edit'
        assert db.execute('select count(*) from watchlist').fetchone()[0]==1
    assert (tmp_path/'data/posters'/f'{first}.png').read_bytes()==b'my existing image'
    assert list((tmp_path/'data/backups').glob('before-tmdb-additions-*.db'))


def test_cancel_keeps_added_movie_and_releases_shared_lock(tmp_path):
    manager,database=expansion(tmp_path)
    def handler(request):
        if request.url.path.rsplit('/',1)[-1].isdigit():manager.cancel()
        return provider(request)
    manager.client_factory=lambda:httpx.Client(transport=httpx.MockTransport(handler))
    manager.reserve(20);manager.run()
    assert manager.status()['phase']=='cancelled'
    assert manager.status()['added']==1
    with acquire_update_lease(tmp_path):pass


def test_no_key_duplicate_job_and_update_lock(tmp_path):
    manager,_=expansion(tmp_path)
    manager.token=lambda:''
    with pytest.raises(ExpansionError):manager.reserve(20)
    manager.token=lambda:'app-test-token'
    with acquire_update_lease(tmp_path):
        with pytest.raises(UpdateGuardError):manager.reserve(20)
    manager.reserve(20)
    with pytest.raises(ExpansionError):manager.reserve(20)
    manager.cancel();manager.run()
    assert 'app-test-token' not in str(manager.status())


def test_missing_poster_does_not_lose_movie(tmp_path,monkeypatch):
    def handler(request):
        return httpx.Response(404) if request.url.host=='image.tmdb.org' else provider(request)
    manager,database=expansion(tmp_path,handler)
    monkeypatch.setattr(manager.cancelled,'wait',lambda _:False)
    manager.reserve(20);manager.run()
    assert manager.status()['phase']=='done'
    assert manager.status()['added']==20 and manager.status()['image_errors']==20


def test_bad_key_or_network_does_not_expose_token(tmp_path):
    manager,_=expansion(tmp_path,lambda request:httpx.Response(401))
    manager.reserve(20);manager.run()
    assert manager.status()['phase']=='error' and 'app-test-token' not in str(manager.status())
    with acquire_update_lease(tmp_path):pass


def test_network_failure_preserves_catalog_and_retry_can_complete(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import backend.database.db as database_module
    from backend.movies.seed import seed_movies
    online = False
    def handler(request):
        if not online:
            raise httpx.ConnectError('offline test')
        return provider(request)
    manager,database = expansion(tmp_path,handler)
    monkeypatch.setattr(database_module, 'settings', SimpleNamespace(db_path=database))
    assert seed_movies() == 72
    monkeypatch.setattr(manager.cancelled,'wait',lambda _:False)
    with connect(database) as db:
        before = [tuple(row) for row in db.execute('SELECT * FROM movies')]
        assert sum(is_released(dict(row)) for row in db.execute('SELECT * FROM movies')) == 20
    manager.reserve(20);manager.run()
    assert manager.status()['phase']=='error'
    with connect(database) as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM movies')]==before
    online = True
    manager.reserve(20);manager.run()
    assert manager.status()['phase']=='done' and manager.status()['added']==20
    with connect(database) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


@pytest.mark.parametrize('kind', [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError])
def test_temporary_transport_failure_retries_same_request_and_completes(tmp_path, monkeypatch, kind):
    requests = []
    def handler(request):
        requests.append(str(request.url))
        if len(requests) == 1:
            raise kind('temporary failure')
        return provider(request)
    manager, database = expansion(tmp_path, handler)
    monkeypatch.setattr(manager.cancelled, 'wait', lambda _:False)
    manager.reserve(20)
    manager.run()
    assert requests[0] == requests[1]
    assert manager.status()['phase'] == 'done'
    assert manager.status()['added'] == 20
    with connect(database) as db:
        assert db.execute('SELECT COUNT(*) FROM movies').fetchone()[0] == 20


def test_interrupted_response_body_retries_from_start(tmp_path, monkeypatch):
    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"results":['
            raise httpx.ReadError('connection reset')
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(200, stream=Interrupted())
        return provider(request)
    manager, _ = expansion(tmp_path, handler)
    monkeypatch.setattr(manager.cancelled, 'wait', lambda _:False)
    manager.reserve(20)
    manager.run()
    assert calls[0] == calls[1]
    assert manager.status()['phase'] == 'done'
    assert manager.status()['added'] == 20


@pytest.mark.parametrize('kind, code', [
    ('timeout', 'timeout'), ('dns', 'dns'), ('certificate', 'certificate'),
    ('connection', 'connection'), ('invalid_response', 'invalid_response'),
])
def test_failure_identifies_cause_without_exposing_credentials(tmp_path, monkeypatch, kind, code):
    calls = []
    sensitive = 'app-test-token https://private.invalid/?api_key=secret'
    def handler(request):
        calls.append(request.url.path)
        if kind == 'timeout':
            raise httpx.ReadTimeout(sensitive)
        if kind == 'dns':
            raise httpx.ConnectError(sensitive) from socket.gaierror(11001, sensitive)
        if kind == 'certificate':
            raise httpx.ConnectError(sensitive) from ssl.SSLCertVerificationError(1, sensitive)
        if kind == 'invalid_response':
            return httpx.Response(200, text='<html>'+sensitive+'</html>')
        raise httpx.ConnectError(sensitive)
    manager, _ = expansion(tmp_path, handler)
    monkeypatch.setattr(manager.cancelled, 'wait', lambda _:False)
    manager.reserve(20)
    manager.run()
    state = manager.status()
    assert state['phase'] == 'error' and state['error_code'] == code
    assert len(calls) == (1 if kind in {'certificate', 'invalid_response'} else 3)
    text = (tmp_path/'data/logs/tmdb-download.log').read_text(encoding='utf-8')
    record = json.loads(text)
    assert record['code'] == code
    assert record['added'] == 0
    assert 'app-test-token' not in text+str(state)
    assert 'private.invalid' not in text+str(state)
    assert 'secret' not in text+str(state)
    with acquire_update_lease(tmp_path):pass


def test_cancel_during_retry_stops_without_another_request(tmp_path, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        raise httpx.ConnectError('temporary interruption')
    manager, _ = expansion(tmp_path, handler)
    def cancel_while_waiting(_):
        manager.cancel()
        return True
    monkeypatch.setattr(manager.cancelled, 'wait', cancel_while_waiting)
    manager.reserve(20)
    manager.run()
    assert manager.status()['phase'] == 'cancelled'
    assert len(calls) == 1
    assert not (tmp_path/'data/logs/tmdb-download.log').exists()
    with acquire_update_lease(tmp_path):pass


def test_backup_write_failure_is_reported_as_storage(tmp_path, monkeypatch):
    import backend.movies.catalog_expand as module
    manager, _ = expansion(tmp_path)
    def denied(*args, **kwargs):
        raise PermissionError('unwritable backup')
    monkeypatch.setattr(module, 'create_backup', denied)
    manager.reserve(20)
    manager.run()
    assert manager.status()['phase'] == 'error'
    assert manager.status()['error_code'] == 'storage'
    assert 'резервную копию' in manager.status()['message']


def test_tmdb_client_keeps_certificate_and_hostname_verification():
    from backend.movies.catalog_expand import tmdb_client
    with tmdb_client() as client:
        context = client._transport._pool._ssl_context
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True
        assert context.cert_store_stats()['x509_ca'] > 0


def test_phone_needs_evening_code_but_can_start_and_observe_same_job(tmp_path,monkeypatch):
    import backend.main as main
    manager,_=expansion(tmp_path)
    monkeypatch.setattr(main,'catalog_expansion',manager)
    monkeypatch.setattr(manager,'run',lambda:None)
    host=TestClient(main.app)
    code=host.get('/api/invite').json()['access_code']
    phone=TestClient(main.app,client=('192.168.1.15',12345))
    assert phone.get('/api/catalog/expand').status_code==403
    headers={'X-Tonight-Code':code,'X-Tonight-Update':'1'}
    response=phone.post('/api/catalog/expand',json={'count':20},headers=headers)
    assert response.status_code==202 and response.json()['phase']=='running'
    assert host.get('/api/catalog/expand').json()['phase']=='running'
    assert phone.post('/api/catalog/expand',json={'count':20},headers=headers).status_code==409
    assert phone.post('/api/catalog/expand',json={'count':500},headers=headers).status_code==422
    assert phone.post('/api/catalog/expand/cancel',headers={**headers,'Origin':'https://evil.example'}).status_code==403
    assert phone.post('/api/catalog/expand/cancel',headers=headers).status_code==200
    manager.lease.close()
