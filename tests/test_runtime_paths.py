from __future__ import annotations

from pathlib import Path

from backend.runtime_paths import resolve_runtime_paths


def test_source_runtime_uses_project_root_for_assets_and_user_data(tmp_path: Path):
    module = tmp_path / "project" / "backend" / "config.py"

    paths = resolve_runtime_paths(module, frozen=False)

    assert paths.root == tmp_path / "project"
    assert paths.assets == tmp_path / "project"


def test_frozen_runtime_keeps_data_next_to_exe_but_reads_packaged_assets(tmp_path: Path):
    module = tmp_path / "project" / "backend" / "config.py"
    executable = tmp_path / "Tonight" / "Tonight.exe"
    bundle = tmp_path / "temporary-bundle"

    paths = resolve_runtime_paths(module, frozen=True, executable=executable, bundle_dir=bundle)

    assert paths.root == executable.parent
    assert paths.assets == bundle
