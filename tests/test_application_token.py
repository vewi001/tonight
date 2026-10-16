import json
import os
from pathlib import Path
import subprocess
import sys

from backend.application_token import application_token


def test_public_source_default_and_packaged_key_precedence(tmp_path):
    (tmp_path/'app').mkdir()
    (tmp_path/'app/tmdb-public.json').write_text(json.dumps({'token':' public-test '}))
    assert application_token(tmp_path)=='public-test'
    (tmp_path/'app-tmdb.json').write_text(json.dumps({'token':'build-test'}))
    assert application_token(tmp_path)=='build-test'
    for invalid in ['{}','[]','{bad',json.dumps({'token':' '}),'x'*4097]:
        (tmp_path/'app-tmdb.json').write_text(invalid)
        assert application_token(tmp_path)=='public-test'
    (tmp_path/'app/tmdb-public.json').unlink()
    assert application_token(tmp_path)==''


def test_clean_source_start_enables_download_and_env_can_override():
    root=Path(__file__).resolve().parents[1]
    env={k:v for k,v in os.environ.items() if k not in {'TMDB_READ_TOKEN','TONIGHT_DB'}}
    script = """
from backend.config import settings
from backend.application_token import application_token
from backend.main import app
from fastapi.testclient import TestClient
from pathlib import Path
key=application_token(Path.cwd())
assert key
assert settings.tmdb_read_token==key
response=TestClient(app).get('/api/catalog/expand')
assert response.status_code==200 and response.json()['available']
assert key not in response.text
"""
    result=subprocess.run([sys.executable,'-c',script],cwd=root,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    env['TMDB_READ_TOKEN']=' personal-test '
    result=subprocess.run([sys.executable,'-c',"from backend.config import settings; assert settings.tmdb_read_token=='personal-test'"],cwd=root,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_builder_bundles_default_without_build_env(tmp_path,monkeypatch):
    import scripts.build_portable as builder
    from types import ModuleType
    monkeypatch.delenv('TMDB_READ_TOKEN',raising=False)
    monkeypatch.setattr(builder,'ROOT',tmp_path)
    (tmp_path/'app').mkdir()
    (tmp_path/'app/tmdb-public.json').write_text(json.dumps({'token':'public-build-test'}))
    stage=tmp_path/'stage';stage.mkdir()
    calls=[]
    installer=ModuleType('PyInstaller');installer.__path__=[]
    entry=ModuleType('PyInstaller.__main__');entry.run=lambda args:calls.append(args)
    installer.__main__=entry
    monkeypatch.setitem(sys.modules,'PyInstaller',installer)
    monkeypatch.setitem(sys.modules,'PyInstaller.__main__',entry)
    builder._build('desktop.py','Tonight',stage,tmp_path/'work',assets=True)
    assert json.loads((stage/'app-tmdb.json').read_text())['token']=='public-build-test'
    assert any('app-tmdb.json' in arg for arg in calls[0])
