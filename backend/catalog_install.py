"""Catalog installation with a DB commit marker and owned-media recovery."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import uuid
import zipfile

from backend.auto_update import AvailableUpdate
from backend.backups import create_backup
from backend.catalog_database import merge_catalog_movies
from backend.catalog_discovery import select_catalog_update
from backend.catalog_media import sanitize_catalog_image
from backend.catalog_package import EXTENSIONS, IDENTIFIER, MAX_RELEASE_BYTES, _version, read_catalog_package
from backend.catalog_recovery import (CatalogInstallError, CatalogRecoveryError, checked, lease_context,
                                     paths, recover_catalog_install, recover_locked, write_journal)
from backend.database.db import connect
from backend.update_guard import UpdateLease


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _candidate(update):
    return select_catalog_update([{'tag_name':'catalog-v'+update.version,'draft':False,'prerelease':False,
                                  'assets':[{'name':update.name,'size':update.size,'digest':'sha256:'+update.sha256,
                                             'browser_download_url':update.url}]}],None)


def _write_bytes(path,content):
    with path.open('xb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _snapshot(archive,private,update):
    total,digest = 0,hashlib.sha256()
    with archive.open('rb') as source, private.open('xb') as destination:
        while chunk:=source.read(64*1024):
            total += len(chunk)
            if total>update.size:
                raise CatalogInstallError('Размер пакета каталога изменился. Скачайте его заново.')
            digest.update(chunk)
            destination.write(chunk)
        destination.flush()
        os.fsync(destination.fileno())
    if total!=update.size or digest.hexdigest()!=update.sha256:
        raise CatalogInstallError('Пакет каталога не прошёл проверку. Скачайте его заново.')


def install_catalog(root: Path, archive: Path, update: AvailableUpdate, *, app_version: str,
                    database: Path | None = None, lease: UpdateLease | None = None, checkpoint=None) -> dict:
    """Internal worker API; checkpoint is for failure tests, never an HTTP input.

    An injected lease stays caller-owned. Version/date change only in the final
    SQLite commit; downloaded SQL is never used. Recovery preserves backups and
    post-crash personal changes. Caller must run startup recovery before UI.
    """
    try:
        root,database,updates = paths(root,database)
        if not database.is_file():
            raise CatalogInstallError('Сначала запустите Tonight для создания локальной базы.')
        update = _candidate(update)
        _version(app_version)
        with lease_context(root,lease):
            recover_locked(root,database)
            return _install_locked(root,database,updates,archive,update,app_version,checkpoint or (lambda phase:None))
    except CatalogInstallError:
        raise
    except Exception:
        raise CatalogInstallError('Не удалось установить каталог. Личные данные сохранены; повторите после закрытия других окон Tonight.') from None


def _install_locked(root,database,updates,archive,update,app_version,checkpoint):
    updates.mkdir(parents=True,exist_ok=True)
    job_id = uuid.uuid4().hex
    job = checked(root,f'CatalogUpdates/{job_id}')
    job.mkdir()
    staging = checked(root,f'CatalogUpdates/{job_id}/media')
    staging.mkdir()
    record = {'format':1,'job_id':job_id,'version':update.version,'installed_at':_now(),
              'database':database.relative_to(root).as_posix(),'media':[]}
    db = None
    result = None
    try:
        write_journal(root,updates,record)
        private = checked(root,f'CatalogUpdates/{job_id}/package.zip')
        _snapshot(archive,private,update)
        package = read_catalog_package(private,app_version=app_version)
        if package.version!=update.version:
            raise CatalogInstallError('Версия каталога не совпадает с выбранным релизом.')
        prepared,total = [],0
        with zipfile.ZipFile(private) as bundle:
            for index,name in enumerate(package.media_files):
                suffix = Path(name).suffix
                content = sanitize_catalog_image(bundle.read(name),suffix)
                total += len(content)
                if total>MAX_RELEASE_BYTES:
                    raise CatalogInstallError('Очищенные медиа превышают ограничение размера.')
                stage_name = f'{index:05d}{suffix}'
                _write_bytes(checked(root,f'CatalogUpdates/{job_id}/media/{stage_name}'),content)
                prepared.append((name,{'stage':stage_name,'size':len(content),'sha256':hashlib.sha256(content).hexdigest()}))
        checkpoint('prepared')
        db = connect(database)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('BEGIN IMMEDIATE')
        current = db.execute("SELECT value FROM app_meta WHERE key='catalog_version'").fetchone()
        if current is not None and tuple(map(int,_version(current[0]).split('.')))>=tuple(map(int,package.version.split('.'))):
            raise CatalogInstallError('Этот или более новый каталог уже установлен.')
        create_backup(database,checked(root,'data/backups'),prefix='catalog-before-'+job_id)
        mapping = merge_catalog_movies(db,package.movies)
        occupied = set()
        for name,item in prepared:
            source_name = Path(name)
            local_id = mapping[source_name.stem]
            if not IDENTIFIER.fullmatch(local_id):
                raise CatalogInstallError('Локальный идентификатор фильма небезопасен для медиа.')
            # Validate a device name too, not just the identifier regex.
            from backend.release import _safe_relative
            _safe_relative(local_id+source_name.suffix)
            group = (source_name.parts[0],local_id.casefold())
            alternatives = [checked(root,f'data/{group[0]}/{local_id}{suffix}') for suffix in EXTENSIONS]
            if group in occupied or any(path.exists() for path in alternatives):
                continue
            occupied.add(group)
            record['media'].append(dict(item,target=f'{group[0]}/{local_id}{source_name.suffix}'))
        write_journal(root,updates,record)
        checkpoint('journaled')
        for item in record['media']:
            target = checked(root,'data/'+item['target'])
            target.parent.mkdir(parents=True,exist_ok=True)
            stage = checked(root,f"CatalogUpdates/{job_id}/media/{item['stage']}")
            os.link(stage,target)  # Atomic no-overwrite; stage inode proves ownership.
            checkpoint('media_linked')
        record['installed_at'] = _now()
        write_journal(root,updates,record)
        checkpoint('pre_commit')
        db.executemany('INSERT INTO app_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                       [('catalog_version',package.version),('catalog_updated_at',record['installed_at']),('catalog_install_job_id',job_id)])
        result = {'version':package.version,'movie_count':db.execute('SELECT COUNT(*) FROM movies').fetchone()[0],
                  'media_added':len(record['media'])}
        db.commit()
        checkpoint('post_commit')
        recover_locked(root,database)
        return result
    except Exception:
        if db is not None:
            db.rollback()
        try:
            state = recover_locked(root,database)
        except Exception:
            raise CatalogRecoveryError('Установка прервана; восстановление не завершено. Сохраните резервные копии и перезапустите Tonight.') from None
        if state=='committed' and result is not None:
            return result
        raise CatalogInstallError('Каталог не установлен. Личные данные сохранены; проверьте пакет и повторите обновление.') from None
    finally:
        if db is not None:
            db.close()
