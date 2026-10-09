"""Build the Windows portable Tonight folder and its matching local update zip."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.catalog_bundle import stage_catalog_bundle
from backend.release import APP_VERSION, create_portable_archive, create_release_archive


def _build(script: str, name: str, stage: Path, work: Path, *, assets: bool = False) -> None:
    try:
        import PyInstaller.__main__
    except ImportError as exc:
        raise SystemExit("Установите сборочные зависимости: .\\.venv\\Scripts\\python.exe -m pip install -r requirements-build.txt") from exc
    args = [
        str(ROOT / script), "--onefile", "--windowed", "--name", name,
        "--distpath", str(stage), "--workpath", str(work / name), "--specpath", str(work / "spec"),
        "--noconfirm", "--clean", "--log-level", "ERROR",
    ]
    if assets:
        args.extend([
            f"--add-data={ROOT / 'frontend'}{os.pathsep}frontend",
            f"--add-data={ROOT / 'data' / 'art'}{os.pathsep}assets/art",
        ])
    PyInstaller.__main__.run(args)


def main() -> None:
    output = Path(os.getenv("TONIGHT_PORTABLE_OUTPUT", str(ROOT / "outputs" / f"Tonight-portable-{APP_VERSION}"))).resolve()
    if output.exists():
        raise SystemExit(f"Удалите или переименуйте существующую сборку: {output}")
    stage = ROOT / "work" / "portable-stage"
    work = ROOT / "work" / "pyinstaller"
    if stage.exists():
        shutil.rmtree(stage)
    _build("desktop.py", "Tonight", stage, work, assets=True)
    _build("updater.py", "Обновить Tonight", stage, work)
    output.mkdir(parents=True)
    for item in stage.iterdir():
        shutil.move(str(item), output / item.name)
    shutil.copy2(ROOT / ".env.example", output / ".env.example")
    shutil.copy2(ROOT / "README.md", output / "README.txt")
    shutil.copy2(ROOT / "PRIVACY.md", output / "PRIVACY.txt")
    default_catalog = ROOT / "outputs" / "Tonight-MVP-evening-tools" / "data"
    catalog_source = Path(os.getenv("TONIGHT_CATALOG_SOURCE", str(default_catalog))).resolve()
    staged = stage_catalog_bundle(catalog_source, output / "catalog")
    if staged["movies"] < 100 or staged["media"] < 100:
        raise SystemExit("Для переносимой сборки нужен полный локальный каталог с постерами и фонами.")
    release_files = ["Tonight.exe", ".env.example", "README.txt", "PRIVACY.txt"] + [path.relative_to(output).as_posix() for path in (output / "catalog").rglob("*") if path.is_file()]
    create_release_archive(output, output.parent / f"Tonight-update-{APP_VERSION}.zip", version=APP_VERSION, files=release_files)
    create_portable_archive(output, output.parent / f"Tonight-portable-{APP_VERSION}.zip")
    print(output)


if __name__ == "__main__":
    main()
