"""Actual production Tonight.exe smoke, isolated data, no token or publication."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE))
os.environ.update(TMDB_READ_TOKEN='',CATALOG_AUTO_UPDATE='0',TONIGHT_OPEN_BROWSER='0',
                  TONIGHT_HOST='127.0.0.1',TONIGHT_PORT='8795',OLLAMA_URL='http://127.0.0.1:1')
import httpx
from backend.database.db import connect,initialize
from backend.release import APP_VERSION

root=Path(tempfile.mkdtemp(prefix='delivery-exe-',dir=SOURCE/'work'))
shutil.copy2(SOURCE/'work/delivery-production-20261014/Tonight.exe',root/'Tonight.exe')
initialize(root/'data/tonight.db')
with closing(connect(root/'data/tonight.db')) as db:
    db.execute("INSERT INTO movies(id,title,year,genres,overview) VALUES('private-exe','Private EXE film',2020,'[]','My personal description')")
    db.execute("INSERT INTO users VALUES('synthetic-user','Synthetic viewer','S','synthetic')")
    db.execute("INSERT INTO watch_history(id,movie_id,watched_at) VALUES(999,'private-exe','synthetic')")
    db.execute("INSERT INTO feedback VALUES(999,'synthetic-user',5,'synthetic')")
    db.execute("INSERT INTO evening_feedback VALUES(999,'synthetic-user',1,'synthetic')")
    db.execute("INSERT INTO watchlist VALUES('private-exe','synthetic','synthetic-user','synthetic reason')")
    db.execute("INSERT INTO taste_genre_exclusions VALUES('synthetic-user','horror','synthetic')")
    db.execute("INSERT INTO app_meta VALUES('private-setting','keep')")
    db.commit()
environment=b'TMDB_READ_TOKEN=\nCATALOG_AUTO_UPDATE=0\nTONIGHT_OPEN_BROWSER=0\nTONIGHT_PORT=8795\n'
(root/'.env').write_bytes(environment)
(root/'.venv').mkdir(); (root/'.venv/marker').write_bytes(b'keep')
manifest=json.loads((SOURCE/'catalog/latest.json').read_bytes())
digest=manifest['sha256']; downloads=root/'CatalogDownloads'/digest[:16]; downloads.mkdir(parents=True)
# Seed just 1 MiB of the identical published package; production must really
# resume the public download and verify every remaining byte before installing.
with (SOURCE/'work/catalog-package-1.1.0/Tonight-catalog-1.1.0.zip').open('rb') as source:
    (downloads/(digest+'.part')).write_bytes(source.read(1024*1024))
print('ISOLATED EXE ROOT:',root,flush=True)
startup=subprocess.STARTUPINFO(); startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow=0
process=subprocess.Popen([str(root/'Tonight.exe')],cwd=root,env=os.environ.copy(),startupinfo=startup)
client=httpx.Client(base_url='http://127.0.0.1:8795',trust_env=False,timeout=60)


def wait(predicate,seconds=120):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            value=client.get('/api/catalog').json()
            if predicate(value): return value
        except (httpx.HTTPError,ValueError): pass
        time.sleep(.3)
    raise AssertionError('Isolated production EXE did not reach expected state')


try:
    wait(lambda p:'update' in p,seconds=60)
    before={}
    tables=('watch_history','feedback','evening_feedback','watchlist','taste_genre_exclusions')
    with sqlite3.connect(root/'data/tonight.db') as db:
        before={table:db.execute('SELECT * FROM '+table).fetchall() for table in tables}
    response=client.post('/api/catalog/updates/check',headers={'X-Tonight-Update':'1'})
    response.raise_for_status(); status=response.json()
    print('EXE CHECK:',json.dumps(status,ensure_ascii=False),flush=True)
    assert status['available_version']=='1.1.0', 'Public discovery failed; no install attempted'
    assert status['can_resume'] and status['download_bytes']==1024*1024
    client.post('/api/catalog/updates/install',headers={'X-Tonight-Update':'1'}).raise_for_status()
    result=wait(lambda p:p['update']['phase'] not in ('downloading','installing'),seconds=1200)
    assert result['update']['phase']=='done',result['update']
    assert result['summary']['catalog_version']=='1.1.0'
    with sqlite3.connect(root/'data/tonight.db') as db:
        for table,rows in before.items(): assert db.execute('SELECT * FROM '+table).fetchall()==rows,table
        assert db.execute("SELECT value FROM app_meta WHERE key='private-setting'").fetchone()[0]=='keep'
        assert db.execute("SELECT overview FROM movies WHERE id='private-exe'").fetchone()[0]=='My personal description'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert (root/'.env').read_bytes()==environment and (root/'.venv/marker').read_bytes()==b'keep'
    (root/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: real production EXE resumed public full-size package and installed; artificial personal data/env/runtime preserved',flush=True)
finally:
    client.close()
    executable=str(root/'Tonight.exe').replace("'","''")
    command="Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq '"+executable+"' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,timeout=25,
                   creationflags=subprocess.CREATE_NO_WINDOW,check=True)
    process.wait(timeout=15)
    print('Isolated production EXE stopped',flush=True)
