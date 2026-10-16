"""State-machine checks complement the browser smoke test."""
import shutil
import subprocess
from pathlib import Path
import pytest


def test_result_committed_before_animation_repeats_and_session_acceptance():
    if not shutil.which('node'): pytest.skip('Node required')
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let persisted={},timers=[],handlers={};
const storage={getItem:k=>persisted[k]||null,setItem:(k,v)=>persisted[k]=v,removeItem:k=>delete persisted[k]};
const root={querySelector:s=>s==='[data-r-accept]'?{addEventListener:(name,fn)=>handlers.accept=fn}:null,querySelectorAll:()=>[]};
const box={document:{querySelector:s=>s==='#app'?root:null},localStorage:storage,sessionStorage:storage,
 location:{hostname:'localhost'},setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout:()=>{},matchMedia:()=>({matches:false})};
vm.createContext(box);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),box);
vm.runInContext(`render=()=>{};state.user='lera';openRoulette();let calls=[];
api=async(path,opts)=>{calls.push({path,body:JSON.parse(opts.body)});return {items:[{id:calls.length===1?'a':'b',title:'Real',genres:[],recommendation_reason:'Catalog'}]};};`,box);
(async()=>{
 await vm.runInContext('spinRoulette()',box);
 assert.equal(vm.runInContext('state.roulette.movie.id',box),'a');
 assert.equal(vm.runInContext('state.roulette.spinning',box),true);
 assert.equal(vm.runInContext('state.roulette.seen.join()',box),'a');
 await vm.runInContext('spinRoulette()',box);
 assert.equal(vm.runInContext('calls.length',box),1);
 vm.runInContext('finishRoulette(state.roulette);bindRoulette()',box);
 handlers.accept();
 assert.equal(vm.runInContext('state.roulette.accepted',box),'a');
 assert.equal(vm.runInContext('calls.length',box),1); // no fake watched action
 await vm.runInContext('spinRoulette()',box);
 assert.equal(vm.runInContext('calls[1].body.seen_ids.join()',box),'a');
 assert.equal(vm.runInContext('state.roulette.movie.id',box),'b');
 vm.runInContext('finishRoulette(state.roulette)',box);
 assert.equal(vm.runInContext('state.roulette.movie.id',box),'b');
 vm.runInContext('state.roulette=null;openRoulette()',box);
 assert.equal(vm.runInContext('state.roulette.seen.join()',box),'a,b');
 assert.equal(vm.runInContext('state.roulette.accepted',box),'a');
 vm.runInContext(`state.roulette.movie={id:'b'};api=async()=>{throw Error('offline');};`,box);
 await vm.runInContext("rouletteAction('dislike')",box);
 assert.equal(vm.runInContext('state.roulette.movie.id',box),'b');
 assert.equal(vm.runInContext('state.roulette.error',box),'offline');
 vm.runInContext(`api=async()=>({items:[],watchlist_count:0});`,box);
 await vm.runInContext('spinRoulette()',box);
 assert.equal(vm.runInContext('state.roulette.empty',box),true);
 assert.equal(vm.runInContext('state.roulette.movie',box),null);
 vm.runInContext(`state.user='nikita';openRoulette()`,box);
 assert.equal(vm.runInContext('state.roulette.seen.length',box),0);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run(['node','-e',script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
