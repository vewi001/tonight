"""Build the Windows portable Tonight folder and its matching local update zip."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.catalog_bundle import stage_catalog_bundle
from backend.release import APP_VERSION, create_portable_archive, create_release_archive


def portable_readme(version: str) -> str:
    return f'''Tonight {version} — локальное приложение для совместного выбора фильма.

Запуск: распакуйте всю папку и откройте Tonight.exe. Python и TMDB-токен
не нужны. Каталог, постеры, фоны и ссылки на трейлеры уже включены.
Видео открывается через YouTube; наличие ссылки не гарантирует доступность.
Телефон подключается по QR в той же Wi-Fi-сети.

В разделе «Каталог» на основном компьютере доступны отдельные действия:
«Обновить каталог» — добавить карточки и недостающие медиа без перезапуска;
«Обновить приложение» — скачать программу и перезапустить Tonight.
Пакеты каталога проверяются на совместимость, размер и SHA-256.
У пользователей нет токена автора; свой TMDB-токен нужен только для
самостоятельного получения новых данных напрямую из TMDB.

Для ручного обновления программы закройте Tonight и откройте
«Обновить Tonight.exe». Для этой версии пакет — Tonight-update-{version}.zip,
не полный portable ZIP. Проверенные релизы и следующие версии:
https://github.com/vewi001/tonight/releases

Личные история, оценки, вкусы и списки хранятся в data/. Сохраняйте эту папку,
.env и .venv при обновлении или переносе. Страховочные копии — data/backups/.
Откат программы не откатывает базу: это защищает новые оценки и историю.
После вечера нажмите «Остановить Tonight» в маленьком окне приложения.

Исходники: https://github.com/vewi001/tonight
Код лицензирован Apache-2.0. Это не лицензия на постеры, данные или трейлеры
третьих сторон. Подробнее о данных и внешних запросах — PRIVACY.txt.
This product uses the TMDB API but is not endorsed or certified by TMDB.
'''


def new_staging_directory(root: Path) -> Path:
    root = root.resolve()
    work = root / 'work'
    if work.is_symlink() or (work.exists() and bool(getattr(work.lstat(), 'st_file_attributes', 0) & 0x400)):
        raise SystemExit('Сборочная папка work не должна быть ссылкой.')
    if not work.resolve().is_relative_to(root):
        raise SystemExit('Сборочная папка должна находиться внутри проекта.')
    work.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='portable-stage-', dir=work))


def update_payload_files(output: Path) -> list[str]:
    return ["Tonight.exe", "Обновить Tonight.exe", ".env.example", "README.txt", "PRIVACY.txt"] + sorted(
        path.relative_to(output).as_posix() for path in (output / "catalog").rglob("*") if path.is_file()
    )


def _build(script: str, name: str, stage: Path, work: Path, *, assets: bool = False) -> None:
    try:
        import PyInstaller.__main__
    except ImportError as exc:
        raise SystemExit("Установите сборочные зависимости: .\\.venv\\Scripts\\python.exe -m pip install -r requirements-build.txt") from exc
    args = [
        str(ROOT / script), "--onefile", "--windowed", "--name", name,
        "--distpath", str(stage), "--workpath", str(work / name), "--specpath", str(work / "spec"),
        "--noconfirm", "--clean", "--log-level", "ERROR",
        "--hidden-import=PIL.JpegImagePlugin", "--hidden-import=PIL.PngImagePlugin",
        "--hidden-import=PIL.WebPImagePlugin",
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
    stage = new_staging_directory(ROOT)
    work = ROOT / "work" / "pyinstaller"
    _build("desktop.py", "Tonight", stage, work, assets=True)
    _build("updater.py", "Обновить Tonight", stage, work)
    output.mkdir(parents=True)
    for item in stage.iterdir():
        shutil.move(str(item), output / item.name)
    shutil.copy2(ROOT / ".env.example", output / ".env.example")
    (output / 'README.txt').write_text(portable_readme(APP_VERSION),encoding='utf-8')
    shutil.copy2(ROOT / "PRIVACY.md", output / "PRIVACY.txt")
    default_catalog = ROOT / "outputs" / "Tonight-MVP-evening-tools" / "data"
    catalog_source = Path(os.getenv("TONIGHT_CATALOG_SOURCE", str(default_catalog))).resolve()
    staged = stage_catalog_bundle(catalog_source, output / "catalog")
    if staged["movies"] < 100 or staged["media"] < 100:
        raise SystemExit("Для переносимой сборки нужен полный локальный каталог с постерами и фонами.")
    release_files = update_payload_files(output)
    create_release_archive(output, output.parent / f"Tonight-update-{APP_VERSION}.zip", version=APP_VERSION, files=release_files)
    create_portable_archive(output, output.parent / f"Tonight-portable-{APP_VERSION}.zip")
    print(output)


if __name__ == "__main__":
    main()
