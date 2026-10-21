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
 setInterval:()=>1,setTimeout:()=>1,clearTimeout:()=>{},requestAnimationFrame:()=>{},URLSearchParams,URL,
 history:{replaceState:(_a,_b,url)=>sandbox.cleanedUrl=String(url)}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
vm.runInContext(`render=()=>{};shell=x=>x;connectWs=()=>{};refreshUpdateStatus=()=>{};
let requests=[];api=async(path)=>{requests.push(path);return {id:7,status:'choosing',participants:{}}};
state.session={id:7,status:'choosing'};`,sandbox);
const run=code=>vm.runInContext(code,sandbox);
(async()=>{
 let html=run('renderHome()');assert.match(html,/data-choice-mode="taste"/);assert.doesNotMatch(html,/data-mm-open|data-smart-query/);
 await run("go('choices')");assert.equal(run('state.view'),'choices');
 html=run('renderChoices()');assert.equal((html.match(/data-choice-mode=/g)||[]).length,5);
 assert.doesNotMatch(html,/data-mm-open|data-smart-query/);assert.equal(run('requests.length'),0);
 assert.doesNotMatch(html,/Movie Match|Вдвоём по ссылке|data-choice-mode="match"/);
 run("openChoiceMode('tonight')");assert.equal(run('state.view'),'home');assert.equal(run('state.pendingChoice'),'tonight');
 assert.match(run('renderHome()'),/Кто будет выбирать/);
 await run("selectUser('lera')");assert.equal(run('state.view'),'tonight');assert.equal(run('state.pendingChoice'),null);
 assert.deepEqual(Array.from(run('requests')),['/api/sessions/7/join','/api/sessions/7']);
 html=run('renderHome()');assert.match(html,/data-choice-mode="taste"/);assert.match(html,/data-view="choices"/);
 assert.doesNotMatch(html,/data-mm-open|data-smart-query|mm-entry|other-modes/);
 run("openChoiceMode('roulette')");assert.equal(run('state.view'),'roulette');
 run("state.tinder={user:'lera',loaded:true,queue:[]};openChoiceMode('tinder')");assert.equal(run('state.view'),'tinder');
 await run("openChoiceMode('taste')");assert.equal(run('state.view'),'vibe');assert.match(run('renderVibe()'),/data-view="quick"/);
 // Exercise the real input binding, then navigate away without submitting it.
 run(`state.expansion={phase:'done'};state.personalPending=true;state.exclusionsPending=true;let listeners={};root.querySelector=s=>s==='[data-smart-query] textarea'?{addEventListener:(event,fn)=>listeners[event]=fn}:null;root.querySelectorAll=()=>[];openChoiceMode('smart');smartSearch.bind();listeners.input({target:{value:'детектив до двух часов'}});`);
 assert.match(run('renderSearch()'),/детектив до двух часов/);
 await run("go('choices')");run("openChoiceMode('smart')");
 assert.match(run('renderSearch()'),/детектив до двух часов/);assert.match(run('renderSearch()'),/← Способы выбора/);
 assert.equal(run('requests.length'),2);
 // Normal bootstrap still loads the shared session.
 run("state.user=null;state.session=null");await run("init({destination:'choices'})");
 assert.equal(run('state.view'),'choices');assert.equal(run('state.session.id'),7);
 // The primary action also continues automatically for a fresh viewer.
 run("state.user=null;state.pendingChoice=null");await run("openChoiceMode('taste')");
 assert.match(run('renderHome()'),/data-user="lera"/);
 await run("selectUser('lera')");assert.equal(run('state.view'),'vibe');
 // Old invitations show the normal home without resuming or creating a room.
 memory.set('tonight:movie-match','preserved-old-room');memory.set('tonight:match-saved','preserved-saved-list');
 sandbox.location={hostname:'localhost',pathname:'/',search:'?join=1&room=old',href:'http://localhost/?join=1&room=old'};
 run('requests=[];state.user=null');await run('init()');
 assert.equal(run('state.view'),'home');assert.equal(sandbox.cleanedUrl,'http://localhost/');
 assert.match(run('renderHome()'),/старой ссылке больше недоступен/);
 assert.equal(memory.get('tonight:movie-match'),'preserved-old-room');assert.equal(memory.get('tonight:match-saved'),'preserved-saved-list');
 assert(!run('requests.some(path=>path.includes("/new")||path.includes("/match"))'));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
