"""Browser-independent checks for rule mutations, expiry refresh and stale decks."""
import shutil
import subprocess
from pathlib import Path
import pytest


def test_exclusion_ui_state_and_confirmation():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script=r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const root={querySelector:()=>null,querySelectorAll:()=>[]};
const box={document:{querySelector:s=>s==='#app'?root:null},localStorage:storage,sessionStorage:storage,
location:{hostname:'localhost'},setTimeout:()=>1,clearTimeout:()=>{},URLSearchParams,structuredClone,
window:{confirm:()=>false}};
vm.createContext(box);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),box);
vm.runInContext(`
state.user='lera';state.session={id:7};state.view='taste';let renders=0,calls=[];
render=()=>renders++;toast=()=>{};
let server={user:'lera',session_id:7,expires:'today',permanent:[],temporary:[],options:{genre:['драма','хоррор'],keyword:['space'],director:[]},disinterest:[]};
api=async(path,opts)=>{calls.push({path,opts});return structuredClone(server);};
`,box);
(async()=>{
 await vm.runInContext('refreshExclusions()',box);
 assert.equal(vm.runInContext('renders',box),1);
 await vm.runInContext('refreshExclusions()',box);
 assert.equal(vm.runInContext('renders',box),1); // unchanged poll cannot replace a typing field
 vm.runInContext(`state.tonight={user:'lera',step:4,filters:{},data:{items:[{id:'old'}]}};
state.tinder={user:'lera',queue:[{id:'old'}],history:[],seen:['old']};
state.roulette={user:'lera',movie:{id:'old'},spinning:true,seen:['old'],accepted:'old'};`,box);
 await vm.runInContext("mutateExclusion('temporary',{kind:'genre',value:'хоррор'})",box);
 const call=vm.runInContext('calls.find(c=>c.opts?.method===\'POST\')',box);
 assert.equal(call.path,'/api/exclusions/lera');
 assert.deepEqual(JSON.parse(call.opts.body),{kind:'genre',value:'хоррор',scope:'temporary',session_id:7});
 assert(!vm.runInContext('calls.some(c=>/movies|swipe|feedback|reset/.test(c.path))',box));
 assert.equal(vm.runInContext('state.tinder.queue.length',box),0);
 assert.equal(vm.runInContext('state.roulette.movie',box),null);
 assert.equal(vm.runInContext('state.tonight.data',box),null);
 const count=vm.runInContext('calls.length',box);
 await vm.runInContext("mutateExclusion('permanent',null,false,true)",box);
 assert.equal(vm.runInContext('calls.length',box),count); // cancelled clear is inert
 vm.runInContext('window.confirm=()=>true',box);
 await vm.runInContext("mutateExclusion('permanent',null,false,true)",box);
 assert(vm.runInContext("calls.some(c=>c.opts?.method==='DELETE'&&c.path.includes('confirmed=true'))",box));
 vm.runInContext(`server.temporary=[{kind:'genre',value:'драма'}]`,box);
 await vm.runInContext('refreshExclusions()',box);
 assert.equal(vm.runInContext('state.exclusions.temporary.length',box),1);
 vm.runInContext('server.temporary=[];server.session_id=null;',box); // evening expiry
 await vm.runInContext('refreshExclusions()',box);
 assert.equal(vm.runInContext('state.exclusions.temporary.length',box),0);
 assert(vm.runInContext("temporaryExclusions().includes('Новый вечер')",box));
 vm.runInContext(`server.session_id=7;server.permanent=[{kind:'movie',value:'x',title:'<script>unsafe</script>'}]`,box);
 await vm.runInContext('refreshExclusions()',box);
 assert(!vm.runInContext("permanentExclusions().includes('<script>unsafe</script>')",box));
 assert(vm.runInContext("permanentExclusions().includes('&lt;script&gt;')",box));
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result=subprocess.run(['node','-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
