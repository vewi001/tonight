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


def test_shared_review_keeps_saved_reaction_values_and_keyboard_controls():
    """Changing the watched-film wording must not reinterpret stored ratings."""
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage={getItem:()=>null,setItem:()=>{}};
const listeners={};
const card={focus:()=>{},addEventListener:(event,fn)=>listeners[event]=fn};
const sandbox={document:{querySelector:s=>s==='#swipe-card'?card:{}},
 localStorage:storage,sessionStorage:storage,location:{hostname:'localhost'}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
const values=vm.runInContext('reactionMap.map(x=>x[0]).join(",")',sandbox);
assert.equal(values,'love,like,okay,dislike,unseen');
vm.runInContext('let submitted=[];react=value=>submitted.push(value);bindSwipeGestures();',sandbox);
for(const key of ['ArrowUp','ArrowRight','ArrowDown','ArrowLeft','?']) {
 listeners.keydown({key,target:{closest:()=>false},preventDefault:()=>{}});
}
assert.equal(vm.runInContext('submitted.join(",")',sandbox),values);
// A focused real button owns Enter/arrows; the card must not submit twice.
listeners.keydown({key:'ArrowRight',target:{closest:()=>true},preventDefault:()=>{throw Error('button intercepted');}});
assert.equal(vm.runInContext('submitted.length',sandbox),5);
'''
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_roulette_reveal_uses_one_server_result_and_ignores_old_speed_preference():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let saved='',timers=[],requests=0,reduced=false;
const root={querySelector:()=>null,querySelectorAll:()=>[]};
const storage={getItem:()=>null,setItem:(k,v)=>saved=v};
const sandbox={document:{querySelector:()=>root},localStorage:storage,sessionStorage:storage,
 location:{hostname:'localhost'},matchMedia:()=>({matches:reduced}),
 setTimeout:(fn,ms)=>{timers.push({fn,ms});return 1;},clearTimeout:()=>{}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
sandbox.choose=async()=>{requests++;return {items:[{id:'winner',title:'Результат сервера'}]};};
vm.runInContext(`render=()=>{};api=choose;state.user='lera';state.view='roulette';
state.roulette={user:'lera',filters:{included_genres:[],excluded_genres:[]},seen:[],short:true};`,sandbox);
(async()=>{
 await vm.runInContext('spinRoulette()',sandbox);
 assert.equal(requests,1);assert.equal(timers[0].ms,2200);
 assert.equal(vm.runInContext('state.roulette.movie.id',sandbox),'winner');
 assert(!saved.includes('short'));
 const html=vm.runInContext('renderRoulette()',sandbox);
 assert(html.includes('roulette-draw'));assert(!html.includes('data-r-short'));assert(!html.includes('data-r-skip'));
 await vm.runInContext('spinRoulette()',sandbox);assert.equal(requests,1);
 timers[0].fn();
 assert.equal(vm.runInContext('state.roulette.spinning',sandbox),false);
 assert.equal(vm.runInContext('state.roulette.movie.id',sandbox),'winner');
 reduced=true;
 await vm.runInContext('spinRoulette()',sandbox);
 assert.equal(timers[1].ms,0);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
