"""Keep mode discovery separate from starting a session or submitting a search."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_discovery_routes_preserve_drafts_and_continue_after_profile_selection():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const memory=new Map(),storage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};
const sandbox={document:{querySelector:()=>({})},localStorage:storage,sessionStorage:storage,location:{hostname:'localhost'},AbortController,
 setInterval:()=>1,setTimeout:()=>1,clearTimeout:()=>{},requestAnimationFrame:()=>{},URLSearchParams};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
vm.runInContext(`render=()=>{};shell=x=>x;connectWs=()=>{};refreshUpdateStatus=()=>{};
let requests=[];api=async(path)=>{requests.push(path);return {id:7,status:'choosing'}};
state.session={id:7,status:'choosing'};`,sandbox);
const run=code=>vm.runInContext(code,sandbox);
(async()=>{
 let html=run('renderHome()');assert.match(html,/data-user="lera"/);assert.doesNotMatch(html,/data-mm-open|data-smart-query/);
 await run("go('choices')");assert.equal(run('state.view'),'choices');
 html=run('renderChoices()');assert.equal((html.match(/data-choice-mode=/g)||[]).length,6);
 assert.doesNotMatch(html,/data-mm-open|data-smart-query/);assert.equal(run('requests.length'),0);
 run("openChoiceMode('match')");assert.equal(run('state.view'),'match-start');assert.equal(run('requests.length'),0);
 run("openChoiceMode('tonight')");assert.equal(run('state.view'),'home');assert.equal(run('state.pendingChoice'),'tonight');
 assert.match(run('renderHome()'),/Кто будет выбирать/);
 await run("selectUser('lera')");assert.equal(run('state.view'),'tonight');assert.equal(run('state.pendingChoice'),null);
 assert.deepEqual(Array.from(run('requests')),['/api/sessions/7/join','/api/sessions/7']);
 html=run('renderHome()');assert.match(html,/data-choice-mode="tonight"/);assert.match(html,/data-view="choices"/);
 assert.doesNotMatch(html,/data-mm-open|data-smart-query|mm-entry|other-modes/);
 run("openChoiceMode('roulette')");assert.equal(run('state.view'),'roulette');
 run("state.tinder={user:'lera',loaded:true,queue:[]};openChoiceMode('tinder')");assert.equal(run('state.view'),'tinder');
 run("openChoiceMode('taste')");assert.equal(run('state.view'),'taste-start');assert.match(run('renderTasteStart()'),/data-view="quick"/);
 // Exercise the real input binding, then navigate away without submitting it.
 run(`state.expansion={phase:'done'};state.personalPending=true;state.exclusionsPending=true;let listeners={};root.querySelector=s=>s==='[data-smart-query] textarea'?{addEventListener:(event,fn)=>listeners[event]=fn}:null;root.querySelectorAll=()=>[];openChoiceMode('smart');smartSearch.bind();listeners.input({target:{value:'детектив до двух часов'}});`);
 assert.match(run('renderSearch()'),/детектив до двух часов/);
 await run("go('choices')");run("openChoiceMode('smart')");
 assert.match(run('renderSearch()'),/детектив до двух часов/);assert.match(run('renderSearch()'),/← Способы выбора/);
 assert.equal(run('requests.length'),2);
 // Returning from a direct room invitation bootstraps normal session data.
 run("state.user=null;state.session=null");await run("init({destination:'choices'})");
 assert.equal(run('state.view'),'choices');assert.equal(run('state.session.id'),7);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
