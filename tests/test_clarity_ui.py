"""Behavioral checks for preferences and interaction boundaries in the existing UI."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_tinder_preferences_survive_new_tab_and_remain_viewer_specific():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const values=new Map(), local={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)};
const session={getItem:()=>null,setItem:()=>{}};
const listeners={};
const root={querySelector:s=>s==='[data-kt-save]'?{addEventListener:(type,fn)=>listeners.save=fn}:null,querySelectorAll:()=>[]};
const sandbox={document:{querySelector:()=>root},localStorage:local,sessionStorage:session,location:{hostname:'localhost'}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
vm.runInContext(`render=()=>{};fetchTinder=()=>{};state.user='lera';openTinder();bindTinder();`,sandbox);
listeners.save({target:{checked:true}});
assert.equal(values.get('tonight:tinder-save:lera'),'1');
vm.runInContext(`state.user='nikita';openTinder();`,sandbox);
assert.equal(vm.runInContext('state.tinder.save',sandbox),false);
vm.runInContext(`state.tinder=null;state.user='lera';openTinder();`,sandbox);
assert.equal(vm.runInContext('state.tinder.save',sandbox),true);
vm.runInContext(`state.tinder.loaded=true;state.tinder.history=[];state.tinder.busy=false;state.tinder.detail=false;`,sandbox);
let html=vm.runInContext('renderTinder()',sandbox);
assert(html.includes('aria-label="Отменить последнее действие"'));
assert(html.includes('data-kt-new'));
assert(!html.includes('Tonight IQ · Первый зритель'));
assert(!html.includes('data-view="home">На главную'));
assert(vm.runInContext(`poster({poster_available:false,title:'',poster_url:'/api/unused'})`,sandbox).includes('Постер пока не загружен'));
assert(!vm.runInContext(`poster({poster_available:false,title:'',poster_url:'/api/unused'})`,sandbox).includes('<img'));
'''
    result = subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
