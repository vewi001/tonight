from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

from backend.auto_update import AvailableUpdate
from backend.catalog_install import install_catalog, recover_catalog_install, CatalogInstallError
from backend.database.db import connect, initialize
from backend.catalog_package import build_catalog_package


def fixture(tmp_path,version='1.0.0'):
    source,root = tmp_path/'source',tmp_path/'app'
    root.mkdir(exist_ok=True)
    initialize(root/'data/tonight.db')
    initialize(source/'tonight.db')
    with closing(connect(source/'tonight.db')) as db:
        db.execute("INSERT OR IGNORE INTO movies(id,title,year,genres,tmdb_id,overview) VALUES('remote','Film',2020,'[]',12,'provider')")
        db.commit()
    (source/'posters').mkdir(exist_ok=True)
    with Image.new('RGB',(8,8),'red') as image:
        image.save(source/'posters/remote.jpg')
    archive = build_catalog_package(source,tmp_path/f'{version}.zip',version=version,min_app_version='1.6.6',
                                    include_media=True,media_rights_reviewed=True)
    name = f'Tonight-catalog-{version}.zip'
    update = AvailableUpdate(version,name,archive.stat().st_size,hashlib.sha256(archive.read_bytes()).hexdigest(),
                            f'https://github.com/vewi001/tonight/releases/download/catalog-v{version}/{name}')
    return root,archive,update


def apply(root,archive,update,**kwargs):
    return install_catalog(root,archive,update,app_version='1.6.6',**kwargs)


def test_install_preserves_personal_rows_ids_env_and_creates_backup(tmp_path):
    root,archive,update = fixture(tmp_path)
    (root/'.env').write_bytes(b'private token')
    (root/'.venv').mkdir()
    (root/'.venv/keep').write_bytes(b'runtime')
    with closing(connect(root/'data/tonight.db')) as db:
        db.execute("INSERT INTO movies(id,title,year,genres,tmdb_id,overview) VALUES('local','My title',2020,'[]',12,'personal')")
        db.execute("INSERT INTO watch_history(id,movie_id,watched_at) VALUES(1,'local','now')")
        db.execute("INSERT INTO feedback VALUES(1,'lera',5,'now')")
        db.commit()
    result = apply(root,archive,update)
    assert result['version']=='1.0.0' and result['media_added']==1
    assert (root/'data/posters/local.jpg').is_file()
    assert not (root/'data/posters/remote.jpg').exists()
    assert (root/'.env').read_bytes()==b'private token' and (root/'.venv/keep').read_bytes()==b'runtime'
    with closing(connect(root/'data/tonight.db')) as db:
        assert db.execute('SELECT id,title,overview FROM movies').fetchone()[:]==('local','My title','personal')
        assert db.execute('SELECT movie_id FROM watch_history').fetchone()[0]=='local'
        assert db.execute('SELECT rating FROM feedback').fetchone()[0]==5
        assert dict(db.execute('SELECT key,value FROM app_meta'))['catalog_version']=='1.0.0'
    assert list((root/'data/backups').glob('catalog-before-*.db'))
    assert not (root/'CatalogUpdates/pending.json').exists()


def test_existing_media_and_repeat_install_are_preserved(tmp_path):
    root,archive,update = fixture(tmp_path)
    (root/'data/posters').mkdir()
    (root/'data/posters/remote.png').write_bytes(b'personal image')
    assert apply(root,archive,update)['media_added']==0
    assert (root/'data/posters/remote.png').read_bytes()==b'personal image'
    with pytest.raises(CatalogInstallError):
        apply(root,archive,update)


@pytest.mark.parametrize('phase',['prepared','journaled','media_linked','pre_commit','post_commit'])
def test_real_process_crash_recovery_preserves_later_personal_changes(tmp_path,phase):
    root,archive,update = fixture(tmp_path)
    code = '''import sys,os,hashlib
from pathlib import Path
from backend.auto_update import AvailableUpdate
from backend.catalog_install import install_catalog
root,archive,phase=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
name='Tonight-catalog-1.0.0.zip'
update=AvailableUpdate('1.0.0',name,archive.stat().st_size,hashlib.sha256(archive.read_bytes()).hexdigest(),'https://github.com/vewi001/tonight/releases/download/catalog-v1.0.0/'+name)
install_catalog(root,archive,update,app_version='1.6.6',checkpoint=lambda p:os._exit(73) if p==phase else None)
'''
    result = subprocess.run([sys.executable,'-c',code,str(root),str(archive),phase],capture_output=True,timeout=30)
    assert result.returncode==73, result.stderr.decode(errors='replace')
    with closing(connect(root/'data/tonight.db')) as db:
        db.execute("UPDATE users SET name='Later personal change' WHERE id='lera'")
        db.commit()
    recovered = recover_catalog_install(root)
    committed = phase=='post_commit'
    assert recovered==('committed' if committed else 'aborted')
    with closing(connect(root/'data/tonight.db')) as db:
        assert db.execute("SELECT name FROM users WHERE id='lera'").fetchone()[0]=='Later personal change'
        assert db.execute('SELECT COUNT(*) FROM movies').fetchone()[0]==int(committed)
    assert (root/'data/posters/remote.jpg').exists()==committed
    assert recover_catalog_install(root) is None


def test_mid_operation_exception_rolls_back_database_and_media(tmp_path):
    root,archive,update = fixture(tmp_path)
    def fail(phase):
        if phase=='media_linked':
            raise RuntimeError('private internal error')
    with pytest.raises(CatalogInstallError) as error:
        apply(root,archive,update,checkpoint=fail)
    assert 'private' not in str(error.value)
    assert not (root/'data/posters/remote.jpg').exists()
    with closing(connect(root/'data/tonight.db')) as db:
        assert db.execute('SELECT COUNT(*) FROM movies').fetchone()[0]==0


def test_wrong_digest_and_incompatible_app_never_change_local_database(tmp_path):
    root,archive,update = fixture(tmp_path)
    bad = AvailableUpdate(update.version,update.name,update.size,'0'*64,update.url)
    with pytest.raises(CatalogInstallError):
        apply(root,archive,bad)
    with pytest.raises(CatalogInstallError):
        install_catalog(root,archive,update,app_version='1.6.5')
    with closing(connect(root/'data/tonight.db')) as db:
        assert db.execute('SELECT COUNT(*) FROM movies').fetchone()[0]==0


def interrupted(root,archive,update,phase='media_linked'):
    def stop(current):
        if current==phase:
            raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        apply(root,archive,update,checkpoint=stop)


def test_recovery_preserves_replaced_personal_media(tmp_path):
    root,archive,update = fixture(tmp_path)
    interrupted(root,archive,update)
    target = root/'data/posters/remote.jpg'
    target.unlink()
    target.write_bytes(b'my later poster')
    assert recover_catalog_install(root)=='aborted'
    assert target.read_bytes()==b'my later poster'


def test_committed_recovery_restores_missing_link_from_stage(tmp_path):
    root,archive,update = fixture(tmp_path)
    interrupted(root,archive,update,'post_commit')
    (root/'data/posters/remote.jpg').unlink()
    assert recover_catalog_install(root)=='committed'
    with Image.open(root/'data/posters/remote.jpg') as image:
        assert image.size==(8,8)


def test_invalid_journal_extension_is_rejected_without_deleting_files(tmp_path):
    root,archive,update = fixture(tmp_path)
    interrupted(root,archive,update)
    pending = root/'CatalogUpdates/pending.json'
    record = json.loads(pending.read_bytes())
    record['media'][0]['stage']='00000.png'
    pending.write_text(json.dumps(record),encoding='utf-8')
    with pytest.raises(CatalogInstallError):
        recover_catalog_install(root)
    assert pending.exists() and (root/'data/posters/remote.jpg').exists()


def test_borrowed_lease_stays_owned_by_caller_and_rejects_closed_or_wrong_root(tmp_path):
    from backend.update_guard import acquire_update_lease, UpdateBusyError
    root,archive,update = fixture(tmp_path)
    with acquire_update_lease(root) as lease:
        assert apply(root,archive,update,lease=lease)['version']=='1.0.0'
        with pytest.raises(UpdateBusyError):
            acquire_update_lease(root)
    with pytest.raises(CatalogInstallError):
        apply(root,archive,update,lease=lease)
    other = tmp_path/'other'
    other.mkdir()
    with acquire_update_lease(other) as lease:
        with pytest.raises(CatalogInstallError):
            apply(root,archive,update,lease=lease)


def test_target_created_after_planning_is_not_overwritten_or_deleted(tmp_path):
    root,archive,update = fixture(tmp_path)
    target = root/'data/posters/remote.jpg'
    def collision(phase):
        if phase=='journaled':
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(b'personal concurrent poster')
    with pytest.raises(CatalogInstallError):
        apply(root,archive,update,checkpoint=collision)
    assert target.read_bytes()==b'personal concurrent poster'
    with closing(connect(root/'data/tonight.db')) as db:
        assert db.execute('SELECT COUNT(*) FROM movies').fetchone()[0]==0


def test_catalog_safety_backups_are_removed_by_personal_data_deletion(tmp_path):
    from backend.privacy import delete_personal_data
    root,archive,update = fixture(tmp_path)
    apply(root,archive,update)
    assert list((root/'data/backups').glob('*.db'))
    result = delete_personal_data(root/'data/tonight.db',root/'data/backups')
    assert result['backups_deleted']==1
    assert not list((root/'data/backups').glob('*.db'))
    with closing(connect(root/'data/tonight.db')) as db:
        assert db.execute('SELECT COUNT(*) FROM movies').fetchone()[0]==1
