"""Build the Windows portable Tonight folder and its matching local update zip."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.catalog_bundle import stage_catalog_bundle
from backend.release import APP_VERSION, create_portable_archive, create_release_archive


def portable_readme(version: str) -> str:
    return f'''Tonight {version} — локальный помощник выбора фильма одному или вместе.

Запуск: распакуйте всю папку и откройте Tonight.exe. Python и TMDB-токен
не нужны. Каталог, постеры, фоны и ссылки на трейлеры уже включены.
Видео открывается через YouTube; наличие ссылки не гарантирует доступность.
Телефон подключается по QR в той же Wi-Fi-сети.

Кинорулетка: «Реши за меня», три режима и быстрые ограничения поверх Tonight IQ.
«Беру этот» сохраняет решение без отметки просмотра; анимацию можно пропустить.
Кино-Tinder: свайпы интереса, отказа и просмотра с возможностью отмены.

Tonight Mode: настроение, время, компания и фильтры. Год выбирается кнопками.
Для одиночного вечера выберите «Один», затем «Смотреть одному» на карточке
и «Начать одиночный вечер». Второй зритель не требуется. После фильма
можно поставить личную оценку. Встроенного видеоплеера нет.

В разделе «Каталог и обновления» на основном компьютере доступны отдельные действия:
«Обновить каталог» — добавить карточки и недостающие медиа без перезапуска;
«Обновить приложение» — скачать только программу и перезапустить Tonight.
Каталог и изображения повторно не скачиваются. При обрыве обновления
приложения нажмите «Продолжить загрузку»: сохранённая часть используется снова.
Пакеты каталога проверяются на совместимость, размер и SHA-256.
С 1.8.0 для известной версии скачиваются только изменения, если они доступны.
Поддерживается зеркало на Яндекс Диске с возвратом к GitHub при ошибке.
В разделе каталога есть «Больше фильмов и постеров»: выберите 20, 50 или 100 фильмов.
Загрузку можно начать с компьютера или подключённого телефона. Фильмы
сохраняются на компьютере; телефон можно закрыть. Есть прогресс и остановка.
По решению владельца в приложение включён отдельный ключ Tonight для TMDB.
Пользователю вводить ключ не нужно. Личный ключ в .env имеет приоритет.

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
    # The existing catalog has its own updater; never send its media again with
    # every program patch. The complete portable archive still includes it.
    return ["Tonight.exe", "Обновить Tonight.exe", ".env.example", "README.txt", "PRIVACY.txt"]


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
        token = os.getenv('TMDB_READ_TOKEN', '').strip()
        if token:
            token_asset = stage / 'app-tmdb.json'
            token_asset.write_text(json.dumps({'token':token}), encoding='utf-8')
            args.append(f"--add-data={token_asset}{os.pathsep}.")
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
        if item.name == 'app-tmdb.json':
            continue  # Included inside the EXE; never copy local environment files.
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
