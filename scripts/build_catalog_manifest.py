"""Generate a public index locally; no credentials or publication."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.catalog_manifest import build_catalog_manifest


def main():
    parser = argparse.ArgumentParser(description='Prepare Tonight public catalog manifest')
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--published-at',required=True,help='Actual UTC release publication timestamp')
    args = parser.parse_args()
    try:
        result = build_catalog_manifest(args.archive,args.output,published_at=args.published_at)
    except (ValueError,OSError):
        parser.exit(1,'Unable to prepare manifest. Check the verified ZIP, UTC date and new output path.\n')
    print(f'Prepared {result.name}; publication was not performed.')


if __name__=='__main__': main()
