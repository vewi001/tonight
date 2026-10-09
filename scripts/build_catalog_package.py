"""Prepare an explicitly versioned, public catalog; never publish it automatically."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.catalog_package import CatalogPackageError, build_catalog_package


def main():
    parser = argparse.ArgumentParser(description='Подготовить отдельный публичный пакет каталога Tonight')
    parser.add_argument('--source-data',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--version',required=True)
    parser.add_argument('--min-app-version',required=True)
    parser.add_argument('--created-at',help='Фиксированное время UTC для воспроизводимой сборки')
    parser.add_argument('--include-media',action='store_true')
    parser.add_argument('--media-rights-reviewed',action='store_true')
    args = parser.parse_args()
    try:
        result = build_catalog_package(args.source_data,args.output,version=args.version,
                    min_app_version=args.min_app_version,created_at=args.created_at,
                    include_media=args.include_media,media_rights_reviewed=args.media_rights_reviewed)
    except (CatalogPackageError,OSError):
        parser.exit(1,'Не удалось подготовить пакет. Проверьте источник, параметры и новую выходную папку.\n')
    print(f'Пакет подготовлен: {result.name}. Публикация не выполнялась.')


if __name__=='__main__':
    main()
