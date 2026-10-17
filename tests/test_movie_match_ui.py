"""Exercise client recovery and race handling with transport/DOM doubles."""
import shutil
import subprocess

import pytest


def test_network_recovery_clears_error_stale_snapshots_are_ignored_and_busy_vote_cannot_double_send():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const memory=new Map([['tonight:match-device','a'.repeat(64)],['tonight:movie-match',JSON.stringify({id:1,room:'test-room-invitation-000000',link:'http://localhost/?room=test-room-invitation-000000'})]]);
const storage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};
const movie={id:'a',title:'Первый фильм',genres:['драма'],year:2020,runtime:100,rating:8,overview:'Описание'};
const base={id:1,room:'test-room-invitation-000000',version:5,phase:'voting',me:0,filters:{max_runtime:null,min_rating:0,min_year:null,max_year:null,included_genres:[],excluded_genres:[],exclude_watched:true},people:[{ready:true,progress:0},{ready:true,progress:0}],matches:[],proposal:null,confirmed:[],card:movie,remaining:2,saved:[]};
let homeReloaded=false,browsed=false;
let fail=false,hold=false,pending=[],writes=0,response=structuredClone(base),html='',client,buttons=[];
const voteButton={dataset:{mmAction:'vote',mid:'a',vote:'yes'},addEventListener:(kind,fn)=>voteButton.click=fn};
const homeButton={addEventListener:(kind,fn)=>homeButton.click=fn};
const backButton={addEventListener:(kind,fn)=>backButton.click=fn};
const root={querySelector:s=>s==='[data-mm-home]'?homeButton:s==='[data-mm-back]'?backButton:null,querySelectorAll:s=>s==='[data-mm-action]'?[voteButton]:[]};
const sockets=[];class WS{constructor(){sockets.push(this);this.readyState=1;}close(){this.closed=true;}send(){}}
const sandbox={document:{hidden:false,addEventListener:()=>{}},window:{addEventListener:()=>{}},
 localStorage:storage,location:{origin:'http://localhost',hostname:'localhost',protocol:'http:',host:'localhost',search:'',href:'http://localhost/',reload:()=>homeReloaded=true},history:{replaceState:()=>{}},URL,URLSearchParams,AbortSignal,structuredClone,WebSocket:WS,
 setTimeout:()=>1,clearTimeout:()=>{},setInterval:()=>1,clearInterval:()=>{},
 fetch:async(path,options)=>{if(options.method==='POST')writes++;if(fail)throw Error('Failed to fetch');if(hold)return new Promise(resolve=>pending.push(resolve));return {ok:true,json:async()=>structuredClone(response)};}};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/movie-match.js','utf8'),sandbox);
sandbox.options={state:{view:'home',user:null,presence:{}},root,render:()=>{html=client.content();client.bind();},shell:x=>x,esc:x=>String(x??''),poster:()=>'',toast:()=>{},onBrowse:()=>{browsed=true;sandbox.options.state.view='choices';}};
client=vm.runInContext('createMovieMatch(options)',sandbox);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 assert(client.hasSession());
 assert.equal(await client.resume({fromLinkOnly:true}),false);
 assert.equal(sockets.length,0);assert.equal(writes,0);
 await client.resume();assert.match(html,/Первый фильм/);
 fail=true;sockets[0].onmessage({data:JSON.stringify({type:'match_changed'})});await flush();
 assert.match(html,/Нет связи с Tonight/);assert.doesNotMatch(html,/Failed to fetch/);
 fail=false;sockets[0].onmessage({data:JSON.stringify({type:'match_changed'})});await flush();
 assert.doesNotMatch(html,/Нет связи с Tonight/);
 hold=true;const first=voteButton.click();const second=voteButton.click();assert.equal(writes,1);
 response={...base,version:6,card:{...movie,id:'b',title:'Следующий фильм'},people:[{ready:true,progress:1},{ready:true,progress:0}],remaining:1};
 pending.shift()({ok:true,json:async()=>structuredClone(response)});await first;await second;
 assert.match(html,/Следующий фильм/);
 hold=false;response={...base,version:5};sockets[0].onmessage({data:JSON.stringify({type:'match_changed'})});await flush();
 assert.match(html,/Следующий фильм/);assert.doesNotMatch(html,/Первый фильм/);
 backButton.click();assert(browsed);assert(sockets[0].closed);assert(memory.has('tonight:movie-match'));assert.equal(writes,1);
 // Invitation links still enter directly, while browsing tools preserves the room.
 sandbox.location.search='?room=test-room-invitation-000000';
 assert.equal(await client.resume({fromLinkOnly:true}),true);assert.equal(writes,2);
 homeButton.click();assert.equal(homeReloaded,true);assert.equal(memory.has('tonight:movie-match'),false);
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result=subprocess.run(['node','-e',script],capture_output=True,text=True,encoding='utf-8')
    assert result.returncode == 0, result.stdout+result.stderr
