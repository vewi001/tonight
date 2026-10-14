"""Create public discovery metadata from an audited app update archive."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.auto_update import DOWNLOAD_PREFIX,select_app_manifest
from backend.release import read_release


def build_app_manifest(archive: Path,output: Path):
    release=read_release(archive)
    with archive.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    name=f'Tonight-update-{release.version}.zip'
    payload=dict(format_version=1,app_version=release.version,
        archive_url=f'{DOWNLOAD_PREFIX}v{release.version}/{name}',
        size_bytes=archive.stat().st_size,sha256=digest)
    select_app_manifest(payload,'0.0.0')
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8') as stream:
        stream.write(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    return payload


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Prepare the app update manifest; never publish')
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    build_app_manifest(args.archive,args.output)
    print('Verified app manifest prepared')
