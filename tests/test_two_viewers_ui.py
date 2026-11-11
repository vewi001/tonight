"""Execute browser state handlers with controlled network ordering."""
import shutil
import subprocess
from pathlib import Path

import pytest


CASES = {
    'late_catalog_selection_preserves_new_profile_and_navigation': r'''
      run("document.querySelectorAll=()=>[];state.view='search';let finish;api=()=>new Promise(r=>finish=r);"
        +"let pending=selectCatalogMovie('arrival');state.user='nikita';state.view='roulette';finish({id:'arrival'});");
      await run('pending');assert.equal(run('state.user'),'nikita');assert.equal(run('state.view'),'roulette');
    ''',
    'late_rating_does_not_open_dialog_for_another_profile': r'''
      run("state.view='feedback';state.historyId=12;state.feedbackCompany='couple';let finish;api=()=>new Promise(r=>finish=r);"
        +"let pending=saveFeedback(5);state.user='nikita';state.view='search';finish({ok:true});");
      await run('pending');assert.equal(run('state.view'),'search');assert.equal(run('state.user'),'nikita');
    ''',
    'old_evening_frame_cannot_reverse_in_progress_restart': r'''
      run("connectWs();const oldSocket=state.ws;applyRealtimeSession({id:2,revision:1,status:'choosing',participants:{}});"
        +"oldSocket.onmessage({data:JSON.stringify({type:'session_restarted',session:{id:1,revision:99,status:'completed'}})});");
      assert.equal(run('state.session.id'),2);assert.equal(run('state.session.status'),'choosing');
    ''',
    'old_reconnection_response_cannot_reverse_restart': r'''
      run("const ws={url:'ws://localhost/ws/session/1/lera',close:()=>{}};state.ws=ws;"
        +"let finish;api=()=>new Promise(r=>finish=r);let pending=restoreAfterReconnect(ws,true);"
        +"applyRealtimeSession({id:2,revision:1,status:'choosing',participants:{}});finish({id:1,status:'completed'});");
      await run('pending');assert.equal(run('state.session.id'),2);
    ''',
    'old_reaction_cannot_unlock_new_profile_request': r'''
      run("let finish=[];api=()=>new Promise(r=>finish.push(r));state.view='swipe';state.deck=[film];let old=react('like');"
        +"state.user='nikita';state.reactionRequest++;reacting=false;let newer=react('love');finish[0]({movies:[],total:20});");
      await run('old');assert.equal(run('reacting'),true);
      run("finish[1]({total:20,movies:[{...film,id:'new'}],session:{id:1,revision:2,status:'choosing'}})");
      await run('newer');assert.equal(run('reacting'),false);assert.equal(run('state.deck[0].id'),'new');
    ''',
    'lost_reply_resyncs_without_socket_reconnect': r'''
      run("state.view='swipe';state.deck=[film];api=async(path,options)=>{"
        +"if(options?.method==='POST')throw new Error('lost reply');"
        +"return {total:20,movies:[{...film,id:'next'}],session:{id:1,revision:2,status:'choosing',participants:{lera:{progress:1}}}}};");
      await run("react('like')");assert.equal(run('state.deck[0].id'),'next');
      assert.equal(run('state.view'),'swipe');assert.equal(run('reacting'),false);
    ''',
    'profile_change_during_restart_preserves_new_viewer': r'''
      run("state.view='results';let finish;api=()=>new Promise(r=>finish=r);let pending=restartSession();"
        +"state.user='nikita';state.view='search';finish({id:2,status:'choosing'});");
      await run('pending');assert.equal(run('state.user'),'nikita');
      assert.equal(run('state.view'),'search');assert.equal(run('state.session.id'),1);
    ''',
    'continuation_restores_saved_stop_genres': r'''
      run("state.view='home';state.session.participants={lera:{energy:'low',moods:['cozy'],max_runtime:90,min_year:1980,disliked_genres:['хоррор']}};"
        +"api=async()=>({total:20,movies:[film]});");
      await run('continueSession()');assert.equal(run('state.view'),'swipe');
      assert.equal(run('state.prefs.disliked_genres[0]'),'хоррор');assert.equal(run('state.prefs.max_runtime'),90);
    ''',
    'shared_transitions_and_old_revisions': r'''
      run("state.view='selected';state.session={id:1,revision:5,status:'selected',selected:{id:'a'}};");
      run("applyRealtimeSession({id:1,revision:6,status:'recommended',selected:null})");
      assert.equal(run('state.view'),'results');assert.equal(run('state.session.selected'),null);
      assert.equal(run("applyRealtimeSession({id:1,revision:5,status:'selected',selected:{id:'a'}})"),false);
      assert.equal(run('state.view'),'results');
      run("applyRealtimeSession({id:1,revision:7,status:'watching',selected:{id:'b'}})");
      assert.equal(run('state.view'),'watching');
      run("applyRealtimeSession({id:1,revision:8,status:'completed',selected:{id:'b'}})");
      assert.equal(run('state.view'),'home');
      run("state.view='search';applyRealtimeSession({id:1,revision:9,status:'completed'})");
      assert.equal(run('state.view'),'search');
    ''',
    'late_deck_after_profile_change': r'''
      run("let finish;api=()=>new Promise(r=>finish=r);state.view='filters';let pending=loadDeck();"
        +"state.user='nikita';state.deck=[{id:'nikita-film'}];finish({total:20,movies:[{id:'lera-film'}]});");
      await run('pending');assert.equal(run('state.deck[0].id'),'nikita-film');
      assert.equal(run('state.view'),'filters');
    ''',
    'late_reaction_after_restart': r'''
      run("let finish;api=()=>new Promise(r=>finish=r);state.view='swipe';state.deck=[film];let pending=react('like');"
        +"state.session={id:2,revision:0,status:'choosing'};state.deck=[];state.view='vibe';"
        +"finish({total:20,movies:[{id:'old-film'}],session:{id:1,revision:2,status:'choosing'}});");
      await run('pending');assert.equal(run('state.session.id'),2);
      assert.equal(run('state.deck.length'),0);assert.equal(run('state.view'),'vibe');
    ''',
    'repaint_does_not_unlock_duplicate_reaction': r'''
      run("let finish,calls=0;api=()=>{calls++;return new Promise(r=>finish=r)};"
        +"state.view='swipe';state.deck=[film];let pending=react('like');renderSwipe();");
      await run("react('dislike')");assert.equal(run('calls'),1);
      assert(run('renderSwipe()').includes('disabled'));
      run("finish({total:20,movies:[{...film,id:'next'}],session:{id:1,revision:2,status:'choosing'}})");
      await run('pending');assert.equal(run('reacting'),false);
      assert.equal(run('state.deck[0].id'),'next');
    ''',
    'newer_deck_wins_and_navigation_survives': r'''
      run("let finish=[];api=()=>new Promise(r=>finish.push(r));state.view='filters';"
        +"let old=loadDeck(),newer=loadDeck();finish[1]({total:20,movies:[{id:'new'}]});");
      await run('newer');run("finish[0]({total:4,movies:[{id:'old'}]})");await run('old');
      assert.equal(run('state.deck[0].id'),'new');assert.equal(run('state.total'),20);
      run("finish=[];state.view='swipe';let navigation=loadDeck();state.view='search';finish[0]({total:20,movies:[{id:'fresh'}]});");
      await run('navigation');assert.equal(run('state.view'),'search');
    ''',
    'reconnection_recovers_lost_reaction_response': r'''
      run("state.view='swipe';state.deck=[{id:'already-answered'}];"
        +"const ws={url:'ws://localhost/ws/session/1/lera',close:()=>{}};state.ws=ws;"
        +"const current={id:1,revision:3,status:'choosing',participants:{lera:{energy:'low',progress:1,ready:false}}};"
        +"let requests=[];api=async path=>{requests.push(path);return path.includes('/swipe/')?"
        +"{total:20,movies:[{id:'next-unanswered'}],session:current}:path.endsWith('/join')?{}:current};");
      await run('restoreAfterReconnect(ws,true)');
      assert.equal(run('state.deck[0].id'),'next-unanswered');assert.equal(run('state.total'),20);
      assert.equal(run('state.connected'),true);assert.equal(run('state.view'),'swipe');
      assert(run('requests').some(p=>p.endsWith('/swipe/lera')));
    ''',
    'reconnection_follows_new_evening_without_old_cards': r'''
      run("state.view='swipe';state.deck=[film];state.prefs.disliked_genres=['хоррор'];"
        +"const ws={url:'ws://localhost/ws/session/1/lera',close:()=>{}};state.ws=ws;let connects=0;connectWs=()=>connects++;"
        +"api=async()=>({id:2,revision:1,status:'choosing',participants:{lera:{ready:false}}});");
      await run('restoreAfterReconnect(ws,true)');assert.equal(run('state.session.id'),2);
      assert.equal(run('state.deck.length'),0);assert.equal(run('state.view'),'vibe');
      assert.equal(run('state.prefs.disliked_genres.length'),0);assert.equal(run('connects'),1);
    ''',
    'late_selection_response_does_not_stop_viewing': r'''
      run("state.view='results';let finish;api=path=>path.endsWith('/choose')?new Promise(r=>finish=r):"
        +"Promise.resolve({id:1,revision:2,status:'selected',selected:{id:'a'}});let pending=choose();"
        +"applyRealtimeSession({id:1,revision:3,status:'watching',selected:{id:'a'}});finish({id:'a'});");
      await run('pending');assert.equal(run('state.view'),'watching');
      assert.equal(run('state.session.status'),'watching');assert.equal(run('state.session.revision'),3);
    ''',
    'shortage_is_visible_and_keeps_filters': r'''
      run("state.view='filters';state.prefs.disliked_genres=['хоррор'];api=async()=>{"
        +"const error=new Error('Доступно карточек: 4 из 20. Ослабьте стоп-жанры или пополните каталог.');error.status=409;throw error;};");
      await run('loadDeck()');assert.equal(run('state.view'),'filters');
      assert.equal(run('state.prefs.disliked_genres[0]'),'хоррор');
      assert.match(run('renderFilters()'),/4 из 20/);assert.match(run('renderFilters()'),/Пополнить каталог/);
    ''',
    'late_failed_join_does_not_sign_out_new_viewer': r'''
      run("let reject;api=()=>new Promise((_r,j)=>reject=j);let pending=selectUser('lera');state.user='nikita';reject(new Error('old join'));");
      await run('pending');assert.equal(run('state.user'),'nikita');
    ''',
    'old_socket_cannot_modify_new_profile': r'''
      run("connectWs();const oldSocket=state.ws;state.user='nikita';connectWs();"
        +"oldSocket.onmessage({data:JSON.stringify({type:'state',session:{id:1,revision:99,status:'completed'}})});");
      assert.equal(run('state.user'),'nikita');assert.equal(run('state.session.status'),'choosing');
    ''',
    'partner_counter_and_saved_preferences_are_independent': r'''
      run("state.view='waiting';state.total=7;state.session.participants={"
        +"lera:{ready:true,total:20,energy:'low',moods:['cozy'],max_runtime:90,min_year:2000,disliked_genres:['хоррор']},"
        +"nikita:{progress:3,total:20,ready:false,energy:'high',moods:['mystery'],max_runtime:150,min_year:null,disliked_genres:['романтика']}};");
      assert.match(run('renderWaiting()'),/3 \/ 20/);assert(!run('renderWaiting()').includes('3 / 7'));
      run('restorePreferences()');assert.equal(run('state.prefs.max_runtime'),90);
      run("state.user='nikita';restorePreferences()");assert.equal(run('state.prefs.max_runtime'),150);
      assert.equal(run('state.prefs.min_year'),null);assert.equal(run('state.prefs.disliked_genres[0]'),'романтика');
    ''',
    'failed_reaction_keeps_current_card_and_unlocks_retry': r'''
      run("state.view='swipe';state.deck=[film];api=async()=>{throw new Error('offline')};");
      await run("react('like')");assert.equal(run('state.deck[0].id'),'film');
      assert.equal(run('reacting'),false);assert.equal(run('state.view'),'swipe');
    ''',
    'second_tab_finishing_syncs_first_tab': r'''
      run("state.view='swipe';state.session.participants={lera:{progress:19,ready:false,total:20}};connectWs();"
        +"let calls=0;api=async()=>{calls++;return {total:20,movies:[],session:{id:1,revision:4,status:'choosing',participants:{lera:{progress:20,ready:true,total:20}}}}};"
        +"state.ws.onmessage({data:JSON.stringify({type:'progress',session:{id:1,revision:4,status:'choosing',participants:{lera:{progress:20,ready:true,total:20}}}})});");
      await new Promise(r=>setImmediate(r));
      assert.equal(run('state.view'),'waiting');assert.equal(run('state.deck.length'),0);assert.equal(run('calls'),1);
    ''',
    'stale_movie_action_contains_visible_movie_id': r'''
      run("state.view='selected';state.session.selected={id:'film/one'};");
      for(const action of ['decline','choose-another','start-watching','watched']){
        assert.equal(run("movieActionPath('"+action+"')"),'/api/sessions/1/'+action+'?expected_movie_id=film%2Fone');
      }
    ''',
}


@pytest.mark.parametrize('case', CASES)
def test_two_viewer_browser_state(case):
    if not shutil.which('node'):
        pytest.skip('Node required')
    setup = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const card={style:{},disabled:false,classList:{add:()=>{}}};
class FakeSocket{constructor(url){this.url=url;}close(){}send(){}}
const sandbox={document:{querySelector:()=>card},localStorage:storage,sessionStorage:storage,
  location:{hostname:'localhost',host:'localhost',protocol:'http:'},WebSocket:FakeSocket,
  AbortController,setInterval:()=>1,clearInterval:()=>{},setTimeout:()=>1,clearTimeout:()=>{},
  requestAnimationFrame:()=>{},URLSearchParams,URL};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
const run=code=>vm.runInContext(code,sandbox);
run("render=()=>{};renderRealtime=()=>{};shell=x=>x;toast=()=>{};"
  +"state.user='lera';state.session={id:1,revision:1,status:'choosing',participants:{}};"
  +"const film={id:'film',title:'Film',year:2020,runtime:90,genres:['драма'],overview:'',poster_url:'/poster'};");
'''
    script = setup + '\n(async()=>{\n' + CASES[case] + '\n})().catch(e=>{console.error(e);process.exitCode=1});'
    result = subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
