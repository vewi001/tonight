"""TEST ONLY source browser fixture: real HTTP interruption/Range, artificial data.

Never bundle this entry point with Tonight. Change mode.txt in the printed
isolated root to success/interrupted/resume/corrupt/offline/check-offline.
"""
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE))
root = Path(tempfile.mkdtemp(prefix='delivery-browser-',dir=SOURCE/'work'))
os.environ.update(TMDB_READ_TOKEN='',CATALOG_AUTO_UPDATE='0',TONIGHT_OPEN_BROWSER='0',
                  TONIGHT_DB=str(root/'data/tonight.db'),OLLAMA_URL='http://127.0.0.1:1',OLLAMA_TIMEOUT='0.05')

import httpx
import uvicorn
from backend import main
import backend.auto_update as app_updates
import backend.catalog_discovery as discovery
import backend.catalog_download as downloader
from backend.catalog_package import build_catalog_package
from backend.database.db import connect,initialize
from backend.release import APP_VERSION

main.ROOT = root
main.bootstrap_catalog = lambda _:None
main.catalog_updates = main.CatalogUpdateManager(root,APP_VERSION,database=root/'data/tonight.db')
main.updates.root = root
app_updates.fetch_latest_update = lambda _:None
initialize(root/'data/tonight.db')
with closing(connect(root/'data/tonight.db')) as db:
    db.execute("INSERT INTO movies(id,title,year,genres) VALUES('private-film','Private film',2020,'[]')")
    db.execute("INSERT INTO watch_history(id,movie_id,watched_at) VALUES(999,'private-film','synthetic')")
    db.execute("INSERT INTO app_meta VALUES('private-setting','keep')")
    db.commit()
(root/'.env').write_text('SYNTHETIC_SETTING=keep\n',encoding='utf-8')
(root/'.venv').mkdir(); (root/'.venv/marker').write_bytes(b'keep')
source = root/'fixture-source'; initialize(source/'tonight.db')
with closing(connect(source/'tonight.db')) as db:
    # Several MB of valid, incompressible JSON give visible progress in the UI.
    for index in range(650):
        overview = hashlib.shake_256(str(index).encode()).hexdigest(1700)
        db.execute("INSERT INTO movies(id,title,year,genres,overview) VALUES(?,?,2020,'[]',?)",
                   (f'fixture-{index}',f'Fixture film {index}',overview))
    db.commit()
packets = {}
for version in ('8.0.0','8.1.0','8.2.0','8.3.0'):
    path=build_catalog_package(source,root/f'{version}.zip',version=version,min_app_version=APP_VERSION,
                               created_at='2026-10-14T00:00:00Z')
    packets[version]=path.read_bytes()
(root/'mode.txt').write_text('success',encoding='utf-8')
seen=[]


def mode(): return (root/'mode.txt').read_text(encoding='utf-8').strip()
def version(): return {'success':'8.0.0','interrupted':'8.1.0','resume':'8.1.0','corrupt':'8.2.0'}.get(mode(),'8.3.0')


class Server(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        current=mode(); selected=version(); packet=packets[selected]
        seen.append({'mode':current,'path':self.path,'range':self.headers.get('Range')})
        if self.path=='/manifest':
            if current=='check-offline': self.send_error(503); return
            name=f'Tonight-catalog-{selected}.zip'
            payload=dict(format_version=1,catalog_version=selected,min_app_version=APP_VERSION,
                         archive_url=f'{downloader.DOWNLOAD_PREFIX}catalog-v{selected}/{name}',
                         size_bytes=len(packet),sha256=hashlib.sha256(packet).hexdigest(),published_at='2026-10-14T00:00:00Z')
            data=json.dumps(payload).encode()
            self.send_response(200); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data); return
        if current=='offline': self.send_error(503); return
        offset=int((self.headers.get('Range') or 'bytes=0-')[6:-1])
        if current=='interrupted' and offset:
            self.send_error(503); return
        self.send_response(206 if offset else 200)
        self.send_header('Content-Length',str(len(packet)-offset))
        if offset: self.send_header('Content-Range',f'bytes {offset}-{len(packet)-1}/{len(packet)}')
        self.end_headers()
        data=packet[offset:]
        if current=='corrupt': data=bytes([data[0]^1])+data[1:]
        if current=='interrupted': data=data[:len(data)//3]
        try:
            for start in range(0,len(data),16384):
                self.wfile.write(data[start:start+16384]); self.wfile.flush(); time.sleep(.03)
            if current=='interrupted': self.connection.shutdown(socket.SHUT_RDWR)
        except (BrokenPipeError,ConnectionResetError,OSError): pass
        (root/'requests.json').write_text(json.dumps(seen,indent=2),encoding='utf-8')


server=ThreadingHTTPServer(('127.0.0.1',0),Server)
threading.Thread(target=server.serve_forever,daemon=True).start()


class LocalTransport(httpx.BaseTransport):
    def __init__(self): self.inner=httpx.HTTPTransport(trust_env=False)
    def handle_request(self,request):
        assert 'authorization' not in request.headers and 'cookie' not in request.headers
        path='/manifest' if str(request.url)==discovery.MANIFEST_URL else '/archive'
        assert str(request.url)==discovery.MANIFEST_URL or str(request.url).startswith(downloader.DOWNLOAD_PREFIX)
        mapped=httpx.Request(request.method,f'http://127.0.0.1:{server.server_port}{path}',headers=request.headers,extensions=request.extensions)
        return self.inner.handle_request(mapped)
    def close(self): self.inner.close()


def client(): return httpx.Client(transport=LocalTransport(),trust_env=False,timeout=httpx.Timeout(30,connect=10))
discovery._client=client
downloader._client=client


def watch():
    previous=mode()
    while True:
        time.sleep(.1)
        current=mode()
        if current!=previous:
            with main.catalog_updates._lock: main.catalog_updates._last_check=None
            previous=current


threading.Thread(target=watch,daemon=True).start()
print('ISOLATED ROOT:',root,flush=True)
try:
    uvicorn.run(main.app,host='127.0.0.1',port=8794,log_level='warning')
finally:
    server.shutdown(); server.server_close()
    with closing(connect(root/'data/tonight.db')) as db:
        assert db.execute("SELECT movie_id FROM watch_history WHERE id=999").fetchone()[0]=='private-film'
        assert db.execute("SELECT value FROM app_meta WHERE key='private-setting'").fetchone()[0]=='keep'
    assert (root/'.env').read_text(encoding='utf-8')=='SYNTHETIC_SETTING=keep\n'
    assert (root/'.venv/marker').read_bytes()==b'keep'
    print('PASS: artificial private history/settings/env/runtime preserved',flush=True)
