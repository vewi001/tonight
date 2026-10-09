"""Single catalog job coordinator; no public paths or credential-bearing errors."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from pathlib import Path
import threading
import time
import uuid

from backend.auto_update import UpdateError
from backend.catalog_discovery import fetch_catalog_update
from backend.catalog_download import CatalogCompatibilityUpdateError, CatalogIntegrityUpdateError, download_catalog
from backend.catalog_install import install_catalog
from backend.catalog_package import _version
from backend.catalog_recovery import CatalogRecoveryError, checked, paths, recover_catalog_install
from backend.database.db import connect
from backend.update_guard import acquire_update_lease, UpdateGuardError

ACTIVE = {'checking','downloading','installing'}


class CatalogUpdateManager:
    def __init__(self,root: Path,app_version: str,*,database: Path | None = None):
        self.root,_,_ = paths(root)
        self.database = database or self.root/'data/tonight.db'
        self.app_version = _version(app_version)
        self._lock = threading.RLock()
        self._current = None
        self._update = None
        self._phase = 'idle'
        self._message = ''
        self._progress = 0
        self._last_check = None
        self._lease = None
        self._worker_claimed = False

    def status(self):
        with self._lock:
            return {'current_version':self._current,'available_version':self._update.version if self._update else None,
                    'phase':self._phase,'download_bytes':self._progress,
                    'total_bytes':self._update.size if self._update else None,'message':self._message}

    def _read_current(self):
        paths(self.root,self.database)
        if not self.database.is_file():
            return None  # Startup recovery precedes initial DB creation.
        with closing(connect(self.database)) as db:
            row = db.execute("SELECT value FROM app_meta WHERE key='catalog_version'").fetchone()
        return _version(row[0]) if row else None

    def recover(self):
        with self._lock:
            if self._phase in ACTIVE or self._lease is not None:
                return self.status()
            try:
                recover_catalog_install(self.root,database=self.database)
                self._current = self._read_current()
            except Exception:
                self._phase = 'recovery_error'
                self._update = None
                self._message = 'Восстановление каталога не завершено. Не удаляйте резервные копии; закройте другие окна Tonight и повторите.'
            else:
                self._phase = 'idle'
                self._message = ''
                self._last_check = None
            return self.status()

    def check(self,*,force=False):
        with self._lock:
            if self._phase in ACTIVE or self._phase=='recovery_error' or self._lease is not None:
                return self.status()
            interval = 60 if force else 6*3600
            if self._last_check is not None and time.monotonic()-self._last_check<interval:
                return self.status()
            self._phase = 'checking'
            self._message = 'Проверяем обновления каталога…'
            self._update = None
        try:
            current = self._read_current()
            update = fetch_catalog_update(current)
        except Exception:
            with self._lock:
                self._phase = 'error'
                self._message = 'Не удалось проверить каталог. Продолжайте вечер и попробуйте позже.'
        else:
            with self._lock:
                self._current,self._update = current,update
                self._phase = 'available' if update else 'current'
                self._message = f'Доступен каталог {update.version}' if update else 'Новых пакетов каталога нет'
        finally:
            with self._lock:
                self._last_check = time.monotonic()
        return self.status()

    def reserve_download(self):
        with self._lock:
            if self._phase in ACTIVE or self._phase=='recovery_error' or self._update is None or self._lease is not None:
                raise UpdateError('Сначала проверьте каталог и дождитесь завершения текущей операции.')
            try:
                self._lease = acquire_update_lease(self.root)
            except UpdateGuardError as error:
                raise UpdateError(str(error)) from None
            self._worker_claimed = False
            self._update = replace(self._update)  # Fresh reservation identity, even on retry.
            self._phase = 'downloading'
            self._message = 'Скачиваем и проверяем каталог…'
            self._progress = 0
            return self._update

    def run_reserved(self,update):
        # Reject duplicate/stale workers before finally: they must never release
        # the lease belonging to an already running worker.
        with self._lock:
            if self._phase!='downloading' or self._lease is None or self._worker_claimed or update is not self._update:
                raise UpdateError('Эта операция обновления уже выполняется или завершена.')
            self._worker_claimed = True
            lease = self._lease
        downloaded = None
        def progress(received,total):
            with self._lock:
                self._progress = received
        try:
            destination = checked(self.root,'CatalogDownloads/'+uuid.uuid4().hex)
            downloaded = download_catalog(update,destination,app_version=self.app_version,progress=progress)
            with self._lock:
                self._phase = 'installing'
                self._message = 'Добавляем фильмы и постеры. Личные данные сохраняются…'
            install_catalog(self.root,downloaded,update,app_version=self.app_version,database=self.database,lease=lease)
            with self._lock:
                self._current = update.version
                self._update = None
                self._phase = 'done'
                self._message = 'Каталог обновлён. История, оценки и личные настройки сохранены.'
                self._last_check = None
        except Exception as error:
            with self._lock:
                self._phase = 'recovery_error' if isinstance(error,CatalogRecoveryError) else 'error'
                if isinstance(error,CatalogCompatibilityUpdateError):
                    self._update = None
                    self._message = f'Для этого каталога нужен Tonight {error.minimum} или новее. Обновите приложение, затем снова проверьте каталог.'
                elif isinstance(error,CatalogIntegrityUpdateError):
                    self._message = 'Каталог не прошёл проверку и не установлен. Повторите загрузку; если ошибка повторится, попробуйте позже.'
                else:
                    self._message = ('Восстановление каталога не завершено. Сохраните резервные копии и перезапустите Tonight.'
                                     if self._phase=='recovery_error' else
                                     'Каталог не обновлён. Проверьте подключение и обновление Tonight, затем повторите.')
        finally:
            try:
                if downloaded is not None:
                    path = checked(self.root,downloaded.relative_to(self.root))
                    path.unlink(missing_ok=True)
            except (OSError,ValueError):
                pass  # Private ZIP may remain; never undo a successful commit.
            lease.close()
            with self._lock:
                self._lease = None
        return self.status()
