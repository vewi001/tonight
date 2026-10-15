"""Prepare a delta and its index entry without publishing anything."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.catalog_delta import build_catalog_delta, delta_manifest

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--base', type=Path, required=True)
    p.add_argument('--target', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--index-output', type=Path, required=True)
    p.add_argument('--published-at', required=True)
    args = p.parse_args()
    result = build_catalog_delta(args.base, args.target, args.output)
    with args.index_output.open('x', encoding='utf-8') as stream:
        json.dump({'format_version': 1, 'deltas': [delta_manifest(result, args.published_at)]}, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print('Delta and index prepared; publication was not performed.')
