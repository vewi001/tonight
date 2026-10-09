"""Validated recovery ledger; never restore a stale DB over personal changes."""
from __future__ import annotations

from contextlib import closing, nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from backend.catalog_package import IDENTIFIER, MAX_RELEASE_BYTES, MAX_RELEASE_FILES, _date, _unique_object, _version
from backend.catalog_media import MAX_IMAGE_BYTES
from backend.database.db import connect
from backend.release import _is_link, _safe_relative
from backend.update_guard import UpdateLease, acquire_update_lease

JOB = re.compile('[a-f0-9]{32}\\Z')
STAGE = re.compile(r'[0-9]{5}\.(jpg|jpeg|png|webp)\Z')
MAX_JOURNAL_BYTES = 2*1024*1024


class CatalogInstallError(ValueError):
    pass


class CatalogRecoveryError(CatalogInstallError):
    pass


def checked(root: Path,relative: str | Path) -> Path:
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise CatalogInstallError('Небезопасный путь установки каталога.')
    target = root/relative
    if any(_is_link(path) for path in (target,*target.parents)) or not target.resolve().is_relative_to(root):
        raise CatalogInstallError('Обновление каталога не может использовать ссылки-папки.')
    return target


def paths(root,database=None):
    root = root.absolute()
    if not root.is_dir() or any(_is_link(path) for path in (root,*root.parents)):
        raise CatalogInstallError('Папка Tonight недоступна или является ссылкой.')
    root = root.resolve()
    database = Path(database) if database is not None else root/'data/tonight.db'
    if not database.is_absolute():
        database = root/database
    try:
        database = checked(root,database.relative_to(root))
    except ValueError:
        raise CatalogInstallError('Для обновления каталог должен храниться внутри папки Tonight.') from None
    if database.suffix!='.db':
        raise CatalogInstallError('Не удалось определить локальную базу каталога.')
    updates = checked(root,'CatalogUpdates')
    return root,database,updates


def lease_context(root,lease):
    if lease is None:
        return acquire_update_lease(root)
    if not isinstance(lease,UpdateLease):
        raise CatalogInstallError('Недействительная блокировка обновления.')
    lease.ensure_root(root)
    return nullcontext(lease)


def write_journal(root,updates,record):
    target = checked(root,'CatalogUpdates/pending.json')
    content = json.dumps(record,ensure_ascii=False,separators=(',',':')).encode()
    if len(content)>MAX_JOURNAL_BYTES:
        raise CatalogInstallError('Журнал установки превышает ограничение размера.')
    descriptor,name = tempfile.mkstemp(prefix='.journal-',dir=updates)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor,'wb') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary,target)
    finally:
        temporary.unlink(missing_ok=True)


def read_journal(root,database):
    pending = checked(root,'CatalogUpdates/pending.json')
    if not pending.exists():
        return None
    if not pending.is_file() or pending.stat().st_size>MAX_JOURNAL_BYTES:
        raise CatalogRecoveryError('Журнал каталога повреждён. Сохраните резервные копии и обратитесь за помощью.')
    record = json.loads(pending.read_bytes(),object_pairs_hook=_unique_object)
    if (not isinstance(record,dict) or set(record)!={'format','job_id','version','installed_at','database','media'}
            or type(record['format']) is not int or record['format']!=1
            or not isinstance(record['job_id'],str) or not JOB.fullmatch(record['job_id'])
            or record['database']!=database.relative_to(root).as_posix()):
        raise CatalogRecoveryError('Не удалось безопасно прочитать журнал каталога.')
    _version(record['version']); _date(record['installed_at'])
    media = record['media']
    if not isinstance(media,list) or len(media)>MAX_RELEASE_FILES:
        raise CatalogRecoveryError('Некорректный состав журнала каталога.')
    targets,stages,total = set(),set(),0
    for item in media:
        if not isinstance(item,dict) or set(item)!={'target','stage','size','sha256'}:
            raise CatalogRecoveryError('Некорректная запись медиа в журнале.')
        name = _safe_relative(item['target'])
        if (len(name.parts)!=2 or name.parts[0] not in {'posters','backdrops'}
                or not IDENTIFIER.fullmatch(name.stem) or name.suffix not in {'.jpg','.jpeg','.png','.webp'}
                or not isinstance(item['stage'],str) or not STAGE.fullmatch(item['stage'])
                or Path(item['stage']).suffix!=name.suffix
                or type(item['size']) is not int or not 0<item['size']<=MAX_IMAGE_BYTES
                or not isinstance(item['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',item['sha256'])
                or item['target'].casefold() in targets or item['stage'].casefold() in stages):
            raise CatalogRecoveryError('Небезопасная запись медиа в журнале.')
        targets.add(item['target'].casefold()); stages.add(item['stage'].casefold())
        total += item['size']
        if total>MAX_RELEASE_BYTES:
            raise CatalogRecoveryError('Медиа в журнале превышают ограничение размера.')
    return record


def matches(path,item):
    if not path.is_file() or path.stat().st_size!=item['size']:
        return False
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()==item['sha256']


def cleanup_stage(root,job_id):
    directory = checked(root,f'CatalogUpdates/{job_id}/media')
    if directory.exists():
        entries = list(directory.iterdir())
        if len(entries)>MAX_RELEASE_FILES:
            raise CatalogRecoveryError('Папка подготовки каталога имеет неожиданный состав.')
        for path in entries:
            checked(root,path.relative_to(root))
            if not STAGE.fullmatch(path.name) or not path.is_file():
                raise CatalogRecoveryError('Папка подготовки каталога имеет неожиданный состав.')
        for path in entries:
            path.unlink()
        directory.rmdir()
    archive = checked(root,f'CatalogUpdates/{job_id}/package.zip')
    if archive.exists():
        archive.unlink()


def recover_locked(root,database):
    record = read_journal(root,database)
    if record is None:
        return None
    if not database.is_file():
        raise CatalogRecoveryError('Локальная база не найдена. Сохраните резервные копии каталога.')
    with closing(connect(database)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            marker = db.execute("SELECT value FROM app_meta WHERE key='catalog_install_job_id'").fetchone()
            committed = marker is not None and marker[0]==record['job_id']
            for item in record['media']:
                target = checked(root,'data/'+item['target'])
                stage = checked(root,f"CatalogUpdates/{record['job_id']}/media/{item['stage']}")
                if committed:
                    if not target.exists():
                        if not matches(stage,item):
                            raise CatalogRecoveryError('Не удалось восстановить медиа. Сохраните резервные копии каталога.')
                        target.parent.mkdir(parents=True,exist_ok=True)
                        os.link(stage,target)
                elif target.exists() and stage.exists() and os.path.samefile(stage,target) and matches(target,item):
                    # Same inode proves ownership; a later replacement/edit is preserved.
                    target.unlink()
            cleanup_stage(root,record['job_id'])
            checked(root,'CatalogUpdates/pending.json').unlink()
            db.commit()
            return 'committed' if committed else 'aborted'
        except BaseException:
            db.rollback()
            raise


def recover_catalog_install(root: Path, *, database: Path | None = None, lease: UpdateLease | None = None):
    try:
        root,database,updates = paths(root,database)
        if not checked(root,'CatalogUpdates/pending.json').exists():
            return None
        with lease_context(root,lease):
            return recover_locked(root,database)
    except Exception:
        raise CatalogRecoveryError('Восстановление каталога не завершено. Не удаляйте резервные копии; повторите после закрытия Tonight.') from None
