"""Copy only hash-pinned public release files into a shareable mirror folder."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.auto_update import DOWNLOAD_PREFIX
from backend.release import _safe_relative


def prepare(output, files):
    if output.exists() or output.is_symlink():
        raise ValueError('Папка назначения уже существует')
    checked = []
    for source, url, size, digest in files:
        if not url.startswith(DOWNLOAD_PREFIX):
            raise ValueError('Ожидается опубликованный файл Tonight')
        relative = _safe_relative(url[len(DOWNLOAD_PREFIX):])
        if len(relative.parts) != 2 or relative.suffix != '.zip':
            raise ValueError('Неправильный путь файла зеркала')
        with source.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != digest or source.stat().st_size != size:
            raise ValueError('Контрольная сумма файла не совпала')
        checked.append((source, relative, digest))
    output.mkdir(parents=True)
    sums = []
    for source, relative, digest in checked:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open('rb') as incoming, target.open('xb') as destination:
            shutil.copyfileobj(incoming, destination)
        sums.append(digest + '  ' + relative.as_posix())
    (output / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', encoding='utf-8')
    (output / 'README.txt').write_text(
        'Загрузите эту папку целиком на Яндекс Диск, сохранив вложенные папки.\n'
        'Откройте доступ по ссылке к самой папке Tonight-mirror и отправьте ссылку в чат.\n'
        'Архивы распаковывать или переименовывать не нужно.\n', encoding='utf-8')
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--inventory', type=Path, required=True, help='Local paths and published URL/size/SHA-256 records')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    items = json.loads(args.inventory.read_text(encoding='utf-8'))
    prepare(args.output, [(Path(x['local_path']), x['url'], x['size'], x['sha256']) for x in items])
    print('Verified mirror folder prepared. Upload was not performed.')
