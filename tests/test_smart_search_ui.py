"""Exercise races and viewer isolation, not just HTML implementation strings."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_search_cancels_stale_requests_handles_errors_and_isolates_viewers():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage={getItem:()=>null,setItem:()=>{}};
const sandbox={document:{querySelector:()=>({})},localStorage:storage,sessionStorage:storage,
 location:{hostname:'localhost'},AbortController,FormData:class{constructor(form){this.form=form;}get(key){return this.form.values[key];}}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
vm.runInContext(`
const listeners={},requests=[];
const form={values:{query:'детектив'},addEventListener:(event,fn)=>listeners['form-'+event]=fn};
const input={addEventListener:(event,fn)=>listeners['input-'+event]=fn,focus:()=>{}};
const clear={addEventListener:(event,fn)=>listeners.clear=fn};
const status={textContent:''},submit={textContent:''};
const fakeRoot={querySelector:s=>s==='[data-smart-query]'?form:s==='[data-smart-query] textarea'?input:s==='[data-smart-clear]'?clear:s==='[data-smart-status]'?status:s==='[data-smart-query] button[type="submit"]'?submit:null,querySelectorAll:()=>[]};
const viewer={user:'lera',view:'search'};
const searchUI=createSmartSearch({state:viewer,root:fakeRoot,api:(path,opts)=>new Promise((resolve,reject)=>requests.push({path,opts,resolve,reject})),render:()=>{},esc,poster:()=>'',tonightRating:()=>'',tonightSynopsis:()=>'',toast:()=>{}});
function send(q){form.values.query=q;searchUI.bind();listeners['form-submit']({preventDefault:()=>{},currentTarget:form});}
const criteria={hard:{genres:['детектив'],excluded_genres:[],min_runtime:null,max_runtime:120,min_year:null,max_year:null,min_rating:null,exclude_watched:false},soft:{themes:[],similar_title:null,source_id:null}};
function response(marker){return {criteria,notes:[marker],conflicts:[],items:[],sources:[],diagnostics:[],total:0,catalog_count:0};}
`,sandbox);
(async()=>{
 await vm.runInContext(`send('детектив');send('комедия');requests[1].resolve(response('CURRENT'));`,sandbox);
 await Promise.resolve();await Promise.resolve();
 assert(vm.runInContext('requests[0].opts.signal.aborted',sandbox));
 vm.runInContext(`requests[0].resolve(response('STALE'));`,sandbox);
 await Promise.resolve();await Promise.resolve();
 let html=vm.runInContext('searchUI.content()',sandbox);
 assert(html.includes('CURRENT')&&!html.includes('STALE'));
 // A network failure remains actionable and all text is escaped.
 vm.runInContext(`send('новый запрос');requests[2].reject(Error('<script>bad</script>'));`,sandbox);
 await Promise.resolve();await Promise.resolve();
 html=vm.runInContext('searchUI.content()',sandbox);
 assert(html.includes('&lt;script&gt;bad')&&!html.includes('<script>bad'));
 vm.runInContext(`send('детектив');searchUI.bind();listeners.clear();requests[3].resolve(response('CLEARED'));`,sandbox);
 await Promise.resolve();await Promise.resolve();
 assert(!vm.runInContext('searchUI.content()',sandbox).includes('CLEARED'));
 // Editing while processing cancels without replacing the input node.
 vm.runInContext(`send('детектив');searchUI.bind();listeners['input-input']({target:{value:'комедия'}});`,sandbox);
 assert(vm.runInContext('requests[4].opts.signal.aborted',sandbox));
 vm.runInContext(`send('детектив');viewer.user='nikita';searchUI.bind();requests[5].resolve(response('OTHER_VIEWER'));`,sandbox);
 await Promise.resolve();await Promise.resolve();
 html=vm.runInContext('searchUI.content()',sandbox);
 assert(!html.includes('OTHER_VIEWER')&&!html.includes('CURRENT'));
 vm.runInContext(`send('комедия');`,sandbox);
 assert(vm.runInContext('requests[6].path',sandbox).endsWith('/nikita'));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
