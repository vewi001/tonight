"""Frontend recovery and shortcut checks, independent of live network."""
import shutil
import subprocess
from pathlib import Path
import pytest


def test_lost_response_reuses_action_and_undo_restores_card():
    if not shutil.which('node'): pytest.skip('Node required')
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const root={querySelector:()=>null,querySelectorAll:()=>[]};
const sandbox={document:{querySelector:s=>s==='#app'?root:null},localStorage:storage,sessionStorage:storage,
 location:{hostname:'localhost'},setTimeout,clearTimeout,crypto:{getRandomValues:bytes=>{for(let i=0;i<bytes.length;i++)bytes[i]=i+1;return bytes;}},
 matchMedia:()=>({matches:true})};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
vm.runInContext(`render=()=>{};toast=()=>{};
state.user='lera';state.view='tinder';state.tinder={user:'lera',queue:[{id:'a',title:'A'},{id:'b',title:'B'}],seen:['a','b'],history:[]};
let calls=[],fail=true;
api=async(path,options)=>{calls.push({path,body:options.body&&JSON.parse(options.body)});if(fail){fail=false;throw Error('lost');}return {id:'test-request-unique'};};`,sandbox);
(async()=>{
 await vm.runInContext(`tinderAct('interest')`,sandbox);
 assert.equal(vm.runInContext('state.tinder.queue[0].id',sandbox),'a');
 await vm.runInContext(`tinderAct('interest')`,sandbox);
 assert.equal(vm.runInContext('calls[0].body.request_id===calls[1].body.request_id',sandbox),true);
 assert.match(vm.runInContext('calls[0].body.request_id',sandbox),/^[a-f0-9]{32}$/);
 assert.equal(vm.runInContext('state.tinder.queue[0].id',sandbox),'b');
 assert.equal(vm.runInContext('state.tinder.history.length',sandbox),1);
 await vm.runInContext('tinderUndo()',sandbox);
 assert.equal(vm.runInContext('state.tinder.queue[0].id',sandbox),'a');
 assert.equal(vm.runInContext('state.tinder.history.length',sandbox),0);
 sandbox.crypto.getRandomValues=()=>{throw Error('random unavailable');};
 await vm.runInContext(`tinderAct('dislike')`,sandbox);
 assert.equal(vm.runInContext('state.tinder.busy',sandbox),false);
 assert.equal(vm.runInContext('state.tinder.error',sandbox),'random unavailable');
 vm.runInContext(`let chosen=[];tinderAct=a=>chosen.push(a);tinderUndo=()=>chosen.push('undo');`,sandbox);
 sandbox.ignored={key:'ArrowRight',target:{closest:()=>true},preventDefault:()=>{throw Error('input intercepted');}};
 vm.runInContext('tinderKeydown(ignored)',sandbox);
 sandbox.shortcut={key:'ArrowUp',target:{closest:()=>false,matches:()=>false},preventDefault:()=>{}};
 vm.runInContext('tinderKeydown(shortcut)',sandbox);
 assert.equal(vm.runInContext('chosen.join()',sandbox),'watched');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result=subprocess.run(['node','-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stderr

