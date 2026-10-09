from contextlib import closing
import asyncio

from fastapi.testclient import TestClient
import pytest

from backend import main
from backend.auto_update import AvailableUpdate
import backend.catalog_manager as catalog
from backend.database.db import initialize,connect
from backend.update_guard import acquire_update_lease

HEADERS = {'X-Tonight-Update':'1'}


@pytest.fixture
def manager(tmp_path,monkeypatch):
    initialize(tmp_path/'data/tonight.db')
    manager = catalog.CatalogUpdateManager(tmp_path,'1.6.6')
    monkeypatch.setattr(main,'catalog_updates',manager)
    monkeypatch.setattr(catalog,'fetch_catalog_update',lambda current:AvailableUpdate(
        '1.0.0','Tonight-catalog-1.0.0.zip',100,'0'*64,
        'https://github.com/vewi001/tonight/releases/download/catalog-v1.0.0/Tonight-catalog-1.0.0.zip'))
    return manager


def test_local_summary_and_check_have_independent_catalog_version(manager):
    with TestClient(main.app) as client:
        response = client.get('/api/catalog')
        assert response.status_code==200
        data = response.json()
        assert data['summary']['movie_count']>0
        assert data['summary']['catalog_version'] is None
        assert data['summary']['last_successful_update'] is None
        assert client.post('/api/catalog/updates/check',headers=HEADERS).json()['available_version']=='1.0.0'
        assert str(manager.root) not in str(data)


@pytest.mark.parametrize('path',['check','install','recover'])
@pytest.mark.parametrize('headers',[{},dict(HEADERS,Origin='https://example.com')])
def test_catalog_actions_reject_foreign_requests(manager,path,headers):
    with TestClient(main.app) as client:
        assert client.post('/api/catalog/updates/'+path,headers=headers).status_code==403


def test_phone_with_evening_code_cannot_manage_catalog(manager):
    with TestClient(main.app) as local:
        code = local.get('/api/invite').json()['access_code']
    with TestClient(main.app,client=('192.168.1.20',1234)) as phone:
        headers = dict(HEADERS,**{'X-Tonight-Code':code})
        assert phone.get('/api/catalog',headers=headers).status_code==403
        for action in ('check','install','recover'):
            assert phone.post('/api/catalog/updates/'+action,headers=headers).status_code==403


def test_rebinding_hostname_cannot_install_catalog(manager):
    with TestClient(main.app,base_url='http://evil.example') as client:
        assert client.post('/api/catalog/updates/install',headers=dict(HEADERS,Origin='http://evil.example')).status_code==403


def test_install_requires_offer_and_shared_lock_and_tracks_worker(manager,monkeypatch):
    calls = []
    async def worker(update):
        calls.append(update.version)
        manager.run_reserved(update)
    monkeypatch.setattr(main,'_run_catalog_update',worker)
    monkeypatch.setattr(catalog,'download_catalog',lambda *a,**k:(_ for _ in ()).throw(ValueError('offline')))
    with TestClient(main.app) as client:
        assert client.post('/api/catalog/updates/install',headers=HEADERS).status_code==409
        client.post('/api/catalog/updates/check',headers=HEADERS)
        with acquire_update_lease(manager.root):
            assert client.post('/api/catalog/updates/install',headers=HEADERS).status_code==409
        assert client.post('/api/catalog/updates/install',headers=HEADERS).status_code==202
    assert calls==['1.0.0'] and manager.status()['phase']=='error'
    assert not main._catalog_jobs


def test_startup_recovery_precedes_bootstrap_and_failure_does_not_block_evening(manager,monkeypatch):
    calls = []
    original = manager.recover
    def recover():
        calls.append('recover')
        return original()
    monkeypatch.setattr(manager,'recover',recover)
    monkeypatch.setattr(main,'initialize',lambda:calls.append('initialize'))
    monkeypatch.setattr(main,'bootstrap_catalog',lambda root:calls.append('bootstrap'))
    monkeypatch.setattr(main,'seed_movies',lambda:calls.append('seed'))
    monkeypatch.setattr(catalog,'recover_catalog_install',lambda *a,**k:(_ for _ in ()).throw(ValueError('bad ledger')))
    with TestClient(main.app) as client:
        assert calls[:4]==['recover','initialize','bootstrap','seed']
        assert client.get('/api/health').status_code==200
        assert client.get('/api/sessions/active').status_code==200
        assert client.post('/api/catalog/updates/install',headers=HEADERS).status_code==409
        assert client.post('/api/catalog/updates/recover',headers=HEADERS).json()['phase']=='recovery_error'


def test_backup_restore_import_and_privacy_deletion_wait_for_update_lock(manager,monkeypatch):
    monkeypatch.setattr(main,'ROOT',manager.root)
    def forbidden(*a,**k):
        pytest.fail('Personal database operation must not run during an update')
    monkeypatch.setattr(main,'restore_backup',forbidden)
    monkeypatch.setattr(main,'delete_personal_data',forbidden)
    with TestClient(main.app) as client, acquire_update_lease(manager.root):
        assert client.post('/api/backup').status_code==409
        assert client.post('/api/backups/example.db/restore',json={'confirmed':True}).status_code==409
        assert client.post('/api/backups/import?confirmed=true',content=b'fixture').status_code==409
        assert client.post('/api/privacy/delete',json={'confirmation':'УДАЛИТЬ ВСЕ ДАННЫЕ'}).status_code==409


def test_shutdown_waits_for_real_catalog_worker_thread(manager,monkeypatch):
    import threading
    entered,finish = threading.Event(),threading.Event()
    def worker(update):
        entered.set()
        assert finish.wait(5)
    monkeypatch.setattr(manager,'run_reserved',worker)
    async def scenario():
        context = main.lifespan(main.app)
        await context.__aenter__()
        job = asyncio.create_task(main._run_catalog_update(object()))
        main._catalog_jobs.add(job)
        job.add_done_callback(main._catalog_jobs.discard)
        exiting = None
        try:
            assert await asyncio.to_thread(entered.wait,3)
            exiting = asyncio.create_task(context.__aexit__(None,None,None))
            await asyncio.sleep(0.02)
            assert not exiting.done() and not job.done()
        finally:
            finish.set()
            if exiting is None:
                await context.__aexit__(None,None,None)
            else:
                await asyncio.wait_for(exiting,3)
        assert job.done() and not main._catalog_jobs
    asyncio.run(scenario())


def test_unfinished_corrupt_journal_blocks_personal_database_changes(manager,monkeypatch):
    monkeypatch.setattr(main,'ROOT',manager.root)
    pending = manager.root/'CatalogUpdates/pending.json'
    pending.parent.mkdir()
    pending.write_bytes(b'corrupt journal')
    with TestClient(main.app) as client:
        assert client.post('/api/backup').status_code==409
        assert client.post('/api/backups/example.db/restore',json={'confirmed':True}).status_code==409
        assert client.post('/api/privacy/delete',json={'confirmation':'УДАЛИТЬ ВСЕ ДАННЫЕ'}).status_code==409
    assert pending.read_bytes()==b'corrupt journal'
