"""Separate mutable user files from packaged application assets."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    assets: Path


def resolve_runtime_paths(
    module_file: Path,
    *,
    frozen: bool,
    executable: Path | None = None,
    bundle_dir: Path | None = None,
) -> RuntimePaths:
    """Return external writable root and read-only code/assets root."""
    source_root = module_file.resolve().parents[1]
    if not frozen:
        return RuntimePaths(root=source_root, assets=source_root)
    if executable is None or bundle_dir is None:
        raise ValueError("Frozen Tonight needs executable and bundle paths")
    return RuntimePaths(root=executable.resolve().parent, assets=bundle_dir.resolve())
