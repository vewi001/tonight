"""Shared nonblocking OS lease for application/catalog update jobs."""
from __future__ import annotations

import os
from pathlib import Path
import threading

from backend.release import _is_link


class UpdateGuardError(ValueError):
    pass


class UpdateBusyError(UpdateGuardError):
    pass


class UpdateLease:
    def __init__(self,stream,root):
        self._stream = stream
        self._root = root.resolve()
        self._mutex = threading.Lock()

    def ensure_root(self,root):
        with self._mutex:
            if self._stream is None or self._root!=root.resolve():
                raise UpdateGuardError('Блокировка установки недействительна для этой папки.')

    def close(self):
        with self._mutex:
            if self._stream is not None:
                # Closing the descriptor releases the OS lock on both platforms.
                self._stream.close()
                self._stream = None

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()


def acquire_update_lease(root: Path) -> UpdateLease:
    """Caller retains lease across worker threads; process death releases it.

    The persistent marker is never evidence of an active job. Local folder must
    already exist, and all parents/marker must be free of symlink/junctions.
    """
    root = root.absolute()
    path = root/'.tonight-update.lock'
    stream = None
    try:
        if not root.is_dir() or any(_is_link(item) for item in (path,root,*root.parents)):
            raise UpdateGuardError('Папка обновления недоступна или является ссылкой.')
        descriptor = os.open(path,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        stream = os.fdopen(descriptor,'r+b',buffering=0)
        if _is_link(path):
            raise UpdateGuardError('Файл блокировки обновления не может быть ссылкой.')
        try:
            if os.name=='nt':
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise UpdateBusyError('Уже выполняется обновление приложения или каталога. Подождите немного.') from None
        return UpdateLease(stream,root)
    except OSError:
        if stream is not None:
            stream.close()
        raise UpdateGuardError('Не удалось защитить установку от одновременного обновления.') from None
    except BaseException:
        if stream is not None:
            stream.close()
        raise
