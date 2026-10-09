import subprocess
import sys

import pytest

from backend.update_guard import acquire_update_lease, UpdateBusyError, UpdateGuardError


def test_shared_lock_blocks_second_job_and_close_is_idempotent(tmp_path):
    first = acquire_update_lease(tmp_path)
    try:
        with pytest.raises(UpdateBusyError):
            acquire_update_lease(tmp_path)
    finally:
        first.close()
    first.close()
    with acquire_update_lease(tmp_path):
        pass


def test_independent_installations_do_not_block_each_other(tmp_path):
    other = tmp_path/'other'
    other.mkdir()
    with acquire_update_lease(tmp_path), acquire_update_lease(other):
        pass


def test_other_process_cannot_acquire_lock_while_parent_holds_it(tmp_path):
    code = 'from pathlib import Path; from backend.update_guard import acquire_update_lease, UpdateBusyError; import sys\ntry:\n acquire_update_lease(Path(sys.argv[1]))\nexcept UpdateBusyError:\n sys.exit(9)'
    with acquire_update_lease(tmp_path):
        result = subprocess.run([sys.executable,'-c',code,str(tmp_path)],capture_output=True,timeout=15)
    assert result.returncode==9, result.stderr.decode(errors='replace')


def test_process_exit_releases_lock_without_explicit_cleanup(tmp_path):
    code = 'from pathlib import Path; from backend.update_guard import acquire_update_lease; import sys, os; lease=acquire_update_lease(Path(sys.argv[1])); os._exit(0)'
    subprocess.run([sys.executable,'-c',code,str(tmp_path)],check=True,capture_output=True,timeout=15)
    with acquire_update_lease(tmp_path):
        pass


def test_linked_path_is_rejected(tmp_path,monkeypatch):
    import backend.update_guard as guard
    monkeypatch.setattr(guard,'_is_link',lambda path:path.name=='.tonight-update.lock')
    with pytest.raises(UpdateGuardError):
        acquire_update_lease(tmp_path)
