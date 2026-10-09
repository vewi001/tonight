from contextlib import closing
import threading

import pytest

import backend.catalog_manager as module
from backend.auto_update import AvailableUpdate, UpdateError
from backend.database.db import connect, initialize
from backend.update_guard import acquire_update_lease, UpdateBusyError


def fixture(tmp_path,monkeypatch):
    initialize(tmp_path/'data/tonight.db')
    update = AvailableUpdate('1.0.0','Tonight-catalog-1.0.0.zip',100,'0'*64,
        'https://github.com/vewi001/tonight/releases/download/catalog-v1.0.0/Tonight-catalog-1.0.0.zip')
    monkeypatch.setattr(module,'fetch_catalog_update',lambda current:update)
    return module.CatalogUpdateManager(tmp_path,'1.6.6'),update


def test_checks_cache_throttle_and_read_independent_version(tmp_path,monkeypatch):
    manager,update = fixture(tmp_path,monkeypatch)
    calls,now = [],[10.0]
    monkeypatch.setattr(module.time,'monotonic',lambda:now[0])
    monkeypatch.setattr(module,'fetch_catalog_update',lambda current:calls.append(current) or update)
    assert manager.check()['phase']=='available'
    manager.check(); manager.check(force=True)
    assert calls==[None]
    with closing(connect(tmp_path/'data/tonight.db')) as db:
        db.execute("INSERT INTO app_meta VALUES('catalog_version','0.9.0')")
        db.commit()
    now[0]+=61
    assert manager.check(force=True)['current_version']=='0.9.0'
    assert calls==[None,'0.9.0']


def test_check_failure_clears_offer_and_hides_raw_errors(tmp_path,monkeypatch):
    manager,update = fixture(tmp_path,monkeypatch)
    manager.check()
    manager._last_check = None
    def fail(current):
        raise RuntimeError('private token/path')
    monkeypatch.setattr(module,'fetch_catalog_update',fail)
    status = manager.check(force=True)
    assert status['phase']=='error' and status['available_version'] is None
    assert 'private' not in str(status) and str(tmp_path) not in str(status)
    with pytest.raises(UpdateError):
        manager.reserve_download()


def test_incompatible_job_suggests_app_update_and_clears_uninstallable_offer(tmp_path,monkeypatch):
    from backend.catalog_download import CatalogCompatibilityUpdateError
    manager,update = fixture(tmp_path,monkeypatch)
    manager.check()
    def fail(*args,**kwargs):
        raise CatalogCompatibilityUpdateError('2.0.0')
    monkeypatch.setattr(module,'download_catalog',fail)
    status = manager.run_reserved(manager.reserve_download())
    assert status['phase']=='error' and status['available_version'] is None
    assert '2.0.0' in status['message'] and 'Обновите приложение' in status['message']
    assert 'подключение' not in status['message']
    with pytest.raises(UpdateError):
        manager.reserve_download()
    with acquire_update_lease(tmp_path):
        pass


def test_integrity_job_has_safe_retry_without_internal_message(tmp_path,monkeypatch):
    from backend.catalog_download import CatalogIntegrityUpdateError
    manager,update = fixture(tmp_path,monkeypatch)
    manager.check()
    def fail(*args,**kwargs):
        raise CatalogIntegrityUpdateError('private token/path')
    monkeypatch.setattr(module,'download_catalog',fail)
    status = manager.run_reserved(manager.reserve_download())
    assert status['phase']=='error' and status['available_version']=='1.0.0'
    assert 'проверку' in status['message'] and 'загрузку' in status['message']
    assert 'private' not in status['message']


def test_job_holds_shared_lease_through_install_and_finishes_after_install(tmp_path,monkeypatch):
    manager,update = fixture(tmp_path,monkeypatch)
    manager.check()
    reserved = manager.reserve_download()
    with pytest.raises(UpdateBusyError):
        acquire_update_lease(tmp_path)
    with pytest.raises(UpdateError):
        manager.reserve_download()
    def download(candidate,destination,**kwargs):
        assert manager.status()['phase']=='downloading'
        kwargs['progress'](100,100)
        destination.mkdir(parents=True)
        target = destination/candidate.name
        target.write_bytes(b'fixture')
        return target
    def install(root,archive,candidate,**kwargs):
        assert manager.status()['phase']=='installing'
        with pytest.raises(UpdateBusyError):
            acquire_update_lease(root)
        kwargs['lease'].ensure_root(root)
        with closing(connect(root/'data/tonight.db')) as db:
            db.execute("INSERT INTO app_meta VALUES('catalog_version','1.0.0')")
            db.commit()
        return {'version':'1.0.0','movie_count':1,'media_added':1}
    monkeypatch.setattr(module,'download_catalog',download)
    monkeypatch.setattr(module,'install_catalog',install)
    assert manager.run_reserved(reserved)['phase']=='done'
    assert manager.status()['current_version']=='1.0.0'
    assert manager.status()['available_version'] is None
    with acquire_update_lease(tmp_path):
        pass
    assert not list((tmp_path/'CatalogDownloads').glob('*/*.zip'))


def test_download_error_releases_lock_and_can_retry(tmp_path,monkeypatch):
    manager,update = fixture(tmp_path,monkeypatch)
    manager.check()
    def fail(*args,**kwargs):
        raise RuntimeError('private secret')
    monkeypatch.setattr(module,'download_catalog',fail)
    assert manager.run_reserved(manager.reserve_download())['phase']=='error'
    assert 'secret' not in str(manager.status())
    with acquire_update_lease(tmp_path):
        pass
    # A failed download retains the known candidate, unlike a failed check.
    reserved = manager.reserve_download()
    manager.run_reserved(reserved)


def test_recovery_error_blocks_install_until_recovered(tmp_path,monkeypatch):
    manager,update = fixture(tmp_path,monkeypatch)
    def fail(*args,**kwargs):
        raise ValueError('private details')
    monkeypatch.setattr(module,'recover_catalog_install',fail)
    assert manager.recover()['phase']=='recovery_error'
    assert 'private' not in str(manager.status())
    manager.check()
    assert manager.status()['phase']=='recovery_error'
    with pytest.raises(UpdateError):
        manager.reserve_download()
    monkeypatch.setattr(module,'recover_catalog_install',lambda *a,**k:'aborted')
    assert manager.recover()['phase']=='idle'
    manager.check()
    assert manager.status()['phase']=='available'


def test_duplicate_worker_cannot_release_running_jobs_lease(tmp_path,monkeypatch):
    manager,update = fixture(tmp_path,monkeypatch)
    manager.check()
    reserved = manager.reserve_download()
    entered,finish = threading.Event(),threading.Event()
    def download(*a,**k):
        entered.set()
        assert finish.wait(5)
        raise ValueError('fixture stop')
    monkeypatch.setattr(module,'download_catalog',download)
    worker = threading.Thread(target=manager.run_reserved,args=(reserved,))
    worker.start()
    try:
        assert entered.wait(5)
        with pytest.raises(UpdateError):
            manager.run_reserved(reserved)
        with pytest.raises(UpdateBusyError):
            acquire_update_lease(tmp_path)
    finally:
        finish.set(); worker.join(5)
    assert not worker.is_alive()
    with acquire_update_lease(tmp_path):
        pass


def test_old_reservation_cannot_run_a_retry(tmp_path,monkeypatch):
    manager,update = fixture(tmp_path,monkeypatch)
    manager.check()
    def fail(*a,**k):
        raise ValueError('fixture')
    monkeypatch.setattr(module,'download_catalog',fail)
    old = manager.reserve_download()
    manager.run_reserved(old)
    new = manager.reserve_download()
    try:
        with pytest.raises(UpdateError):
            manager.run_reserved(old)
        with pytest.raises(UpdateBusyError):
            acquire_update_lease(tmp_path)
    finally:
        manager.run_reserved(new)


def test_manager_rejects_root_links_before_reading_database(tmp_path,monkeypatch):
    import backend.catalog_recovery as recovery
    alias = tmp_path/'alias'
    alias.mkdir()
    monkeypatch.setattr(recovery,'_is_link',lambda path:path==alias)
    with pytest.raises(ValueError):
        module.CatalogUpdateManager(alias,'1.6.6')


def test_manager_installs_real_verified_packet_and_preserves_personal_data(tmp_path,monkeypatch):
    import hashlib
    import httpx
    from PIL import Image
    from backend.catalog_package import build_catalog_package
    from backend.catalog_download import download_catalog
    root,source = tmp_path/'app',tmp_path/'source'
    root.mkdir()
    initialize(root/'data/tonight.db')
    initialize(source/'tonight.db')
    with closing(connect(source/'tonight.db')) as db:
        db.execute("INSERT INTO movies(id,title,year,genres,tmdb_id) VALUES('remote','Film',2020,'[]',12)")
        db.commit()
    with closing(connect(root/'data/tonight.db')) as db:
        db.execute("INSERT INTO movies(id,title,year,genres,tmdb_id) VALUES('local','Personal title',2020,'[]',12)")
        db.execute("INSERT INTO watch_history(id,movie_id,watched_at) VALUES(1,'local','now')")
        db.commit()
    (source/'posters').mkdir()
    with Image.new('RGB',(8,8),'red') as image:
        image.save(source/'posters/remote.jpg')
    packet = build_catalog_package(source,tmp_path/'fixture.zip',version='1.0.0',min_app_version='1.6.6',
                                   include_media=True,media_rights_reviewed=True).read_bytes()
    name = 'Tonight-catalog-1.0.0.zip'
    update = AvailableUpdate('1.0.0',name,len(packet),hashlib.sha256(packet).hexdigest(),
        'https://github.com/vewi001/tonight/releases/download/catalog-v1.0.0/'+name)
    monkeypatch.setattr(module,'fetch_catalog_update',lambda current:update)
    def download(candidate,destination,**kwargs):
        with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=packet))) as client:
            return download_catalog(candidate,destination,client=client,**kwargs)
    monkeypatch.setattr(module,'download_catalog',download)
    manager = module.CatalogUpdateManager(root,'1.6.6')
    manager.recover(); manager.check()
    assert manager.run_reserved(manager.reserve_download())['phase']=='done'
    assert manager.status()['current_version']=='1.0.0'
    assert (root/'data/posters/local.jpg').is_file()
    assert not (root/'CatalogUpdates/pending.json').exists()
    with closing(connect(root/'data/tonight.db')) as db:
        assert db.execute('SELECT id,title FROM movies').fetchone()[:]==('local','Personal title')
        assert db.execute('SELECT movie_id FROM watch_history').fetchone()[0]=='local'


def test_external_database_configuration_does_not_break_manager_or_touch_database(tmp_path):
    root = tmp_path/'app'
    root.mkdir()
    external = tmp_path/'external.db'
    initialize(external)
    original = external.read_bytes()
    manager = module.CatalogUpdateManager(root,'1.6.6',database=external)
    assert manager.recover()['phase']=='recovery_error'
    assert external.read_bytes()==original
