import shutil
import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('initial_count', [0, 100])
@pytest.mark.parametrize('finish', ['done', 'error', 'cancelled'])
def test_first_launch_download_and_ready_state(initial_count, finish):
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const handlers={},button={disabled:false,addEventListener:(name,fn)=>handlers[name]=fn};
const root={querySelector:s=>s==='[data-expand-start]'?button:null,querySelectorAll:()=>[]};
const sandbox={document:{querySelector:()=>root},localStorage:storage,sessionStorage:storage,
 location:{hostname:'localhost'},setTimeout:()=>1,clearTimeout:()=>{}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
const run=code=>vm.runInContext(code,sandbox);
run("shell=x=>x;render=()=>{};paintExpansion=()=>{};toast=()=>{};state.view='setup';state.expansionCount=20;");
run("state.setup={catalog_available:"+INITIAL+",catalog:"+INITIAL+"};state.expansion={phase:'idle',available:true};");
let html=run('renderSetup()');
assert(html.includes('Загрузить каталог')&&html.includes('Загрузить фильмы'));
assert(html.indexOf('data-expand-start')<html.indexOf('setup-list'));
assert.equal(html.includes('data-action="finish-setup"'),INITIAL>0);
run("let calls=[];api=async(path,options)=>{calls.push([path,options]);return {phase:'running',available:true,added:0,target:20};};bindExpansion();");
(async()=>{
 await handlers.click({currentTarget:button});
 const calls=run('calls');const start=calls.find(c=>c[1]?.method==='POST');
 assert.equal(start[0],'/api/catalog/expand');
 assert.equal(JSON.parse(start[1].body).count,20);
 assert.equal(start[1].headers['X-Tonight-Update'],'1');
 assert(run('catalogExpansionCard({setup:true})').includes('Загружаем фильмы'));
 run("state.expansion={phase:'running',available:true};api=async path=>path==='/api/catalog/expand'?{phase:'"+FINISH+"',available:true,added:20,posters:20,target:20,message:'finished'}:{catalog_available:"+INITIAL+"+20,catalog:"+INITIAL+"+20,posters:20};");
 await run('refreshExpansion()');
 html=run('renderSetup()');
 assert.equal(run('state.setup.catalog_available'),INITIAL+20);
 assert(html.includes('data-action="finish-setup"'));
 assert(html.includes('Загрузить фильмы'));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    script = f'const INITIAL={initial_count}, FINISH={json.dumps(finish)};\n' + script
    result = subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
