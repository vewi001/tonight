import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from backend.main import app


def test_search_pagination_is_disjoint_and_keeps_conditions():
    client = TestClient(app)
    first = client.post('/api/search/smart/lera', json={'query':'Комедию до двух часов'}).json()
    assert len(first['items']) == 12 and first['total'] > 12
    second = client.post('/api/search/smart/lera', json={'criteria':first['criteria'],'offset':12}).json()
    assert first['total'] == second['total']
    assert not {m['id'] for m in first['items']} & {m['id'] for m in second['items']}
    assert all(m['runtime'] <= 120 and 'комедия' in m['genres'] for m in first['items']+second['items'])
    assert client.post('/api/search/smart/lera', json={'query':'комедию','offset':-1}).status_code == 422


def test_shared_choice_starts_real_solo_evening_without_saving_or_watching():
    client = TestClient(app)
    sid = client.get('/api/sessions/active').json()['id']
    client.post(f'/api/sessions/{sid}/join', json={'user_id':'lera'})
    mid = client.post('/api/search/smart/lera',json={'query':'Комедию до двух часов'}).json()['items'][0]['id']
    for _ in range(2):
        response = client.post(f'/api/sessions/{sid}/select-catalog/{mid}',json={'company':'solo','user_id':'lera'})
        assert response.status_code == 200
    selected = client.get(f'/api/sessions/{sid}').json()
    assert selected['status'] == 'selected' and selected['selected']['id'] == mid
    assert selected['viewing_company'] == 'solo' and selected['solo_user_id'] == 'lera'
    assert client.post(f'/api/sessions/{sid}/select-catalog/{mid}',json={'company':'couple','user_id':'lera'}).status_code == 200
    together = client.get(f'/api/sessions/{sid}').json()
    assert together['viewing_company'] == 'couple' and together['solo_user_id'] is None
    from backend.database.db import db_session
    with db_session() as db:
        for table in ('watch_history','watchlist','viewer_movie_actions','feedback'):
            assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0


def test_shared_frontend_choice_serializes_double_click_and_recovers_errors():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const root={querySelector:()=>null,querySelectorAll:()=>[]};
const storage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const box={document:{querySelector:s=>s==='#app'?root:null,querySelectorAll:()=>[]},localStorage:storage,sessionStorage:storage};
vm.createContext(box);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),box);
vm.runInContext(`render=()=>{};toast=()=>{};state.user='lera';state.view='search';state.session={id:1,status:'choosing'};
let calls=[],resolve;api=async(path,opts)=>{calls.push({path,body:opts?.body&&JSON.parse(opts.body)});
if(opts)return new Promise(r=>resolve=r);return {id:1,status:'selected',selected:{id:'a'}};};`,box);
(async()=>{
 const first=vm.runInContext("selectCatalogMovie('a')",box);
 await vm.runInContext("selectCatalogMovie('a')",box);
 assert.equal(vm.runInContext('calls.length',box),1);
 vm.runInContext('resolve({})',box);await first;
 assert.equal(vm.runInContext('state.view',box),'selected');
 assert.equal(vm.runInContext('state.selectionReturn',box),'search');
 assert.equal(vm.runInContext('calls[0].body.company',box),'solo');
 assert.equal(vm.runInContext('calls.length',box),2);
 vm.runInContext(`state.view='roulette';api=async()=>{throw Error('offline')};`,box);
 await vm.runInContext("selectCatalogMovie('b')",box);
 assert.equal(vm.runInContext('state.view',box),'roulette');
 assert.equal(vm.runInContext('state.movieSelecting',box),false);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(['node','-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
