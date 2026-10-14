import shutil
import subprocess
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_manual_rating_uses_history_movie_without_changing_current_evening():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const sandbox={document:{querySelector:()=>({})},localStorage:storage,sessionStorage:storage,
location:{hostname:'localhost'},setTimeout:()=>{},clearTimeout:()=>{}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
vm.runInContext(`render=()=>{}; shell=x=>x; toast=()=>{};
state.user='lera'; state.view='selected'; state.session={id:7,status:'selected',selected:{title:'Текущий фильм'}};
let calls=[]; api=async(path,options)=>{calls.push(path);return {...state.session,status:'watching'}};`,sandbox);
(async()=>{
 await vm.runInContext('startWatching()',sandbox);
 assert.equal(vm.runInContext('state.view',sandbox),'watching');
 assert.equal(vm.runInContext('calls.length',sandbox),1);
 assert.match(vm.runInContext('renderWatching()',sandbox),/Просмотр окончен — оценить/);
 vm.runInContext("state.view='history'",sandbox);
 await vm.runInContext("go('watching')",sandbox);
 assert.equal(vm.runInContext('state.view',sandbox),'watching');
 vm.runInContext(`state.view='history'; api=async()=>({items:[{history_id:9,movie:{title:'Старый фильм'}}]});`,sandbox);
 await vm.runInContext('openHistoryRating(9)',sandbox);
 assert.equal(vm.runInContext('state.view',sandbox),'feedback');
 assert.equal(vm.runInContext('state.session.id',sandbox),7);
 assert.equal(vm.runInContext('state.session.status',sandbox),'watching');
 assert.match(vm.runInContext('renderFeedback()',sandbox),/Старый фильм/);
 assert.doesNotMatch(vm.runInContext('renderFeedback()',sandbox),/Текущий фильм/);
 vm.runInContext('api=async(path)=>{calls.push(path);return {}};',sandbox);
 await vm.runInContext('saveFeedback(4)',sandbox);
 assert.equal(vm.runInContext('calls[calls.length-1]',sandbox),'/api/history/9/feedback');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_main_typeface_is_bundled_and_inherited_by_all_text_controls():
    css=(ROOT/'frontend/styles.css').read_text(encoding='utf-8')
    assert 'src:url(\'/assets/fonts/NotoSans-Regular.woff2\')' in css
    assert 'font-weight:100 900' in css and 'font-synthesis:none' in css
    assert 'button, input, select, textarea { font:inherit;' in css
    assert all('Tonight Sans' in value or value.strip()=='inherit'
               for value in re.findall(r'font-family:([^;]+)',css))
    font=ROOT/'frontend/fonts/NotoSans-Regular.woff2'
    assert font.read_bytes()[:4]==b'wOF2'
    assert (ROOT/'frontend/fonts/OFL.txt').is_file()


def test_mobile_navigation_has_labels_disclosure_and_unchanged_permissions():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const sandbox={document:{querySelector:()=>({})},localStorage:storage,sessionStorage:storage,
location:{hostname:'localhost'},setTimeout:()=>{},clearTimeout:()=>{}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
let html=vm.runInContext('shell("test")',sandbox);
assert(html.includes('aria-controls="main-navigation"'));
assert(html.includes('aria-expanded="false"'));
for(const label of ['История','Неделя','Серии','Проверить','Каталог','На потом','Наш вкус','Найти']) assert(html.includes(label),label);
vm.runInContext('state.navOpen=true',sandbox);
html=vm.runInContext('shell("test")',sandbox);
assert(html.includes('aria-expanded="true"') && html.includes('top-actions is-open'));
sandbox.location.hostname='192.168.1.20';
assert(!vm.runInContext('shell("test")',sandbox).includes('data-view="catalog"'));
'''
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_mobile_styles_keep_text_and_touch_targets_visible():
    css = (ROOT / 'frontend/styles.css').read_text(encoding='utf-8')
    mobile = css[css.index('/* Mobile readability:'):]
    for contract in ['min-height:44px', 'min-width:44px', 'safe-area-inset-bottom',
                     '.top-actions .nav-label { display:inline;',
                     '.reaction span { position:static;', '.swipe-stage { min-height:0;',
                     'orientation:landscape', '100dvh', 'input:focus-visible']:
        assert contract in mobile


def test_mobile_realtime_keeps_editing_node_and_navigation_ignores_stale_results():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const callbacks=[]; const notice={innerHTML:''};
const sandbox={document:{querySelector:()=>({querySelector:()=>notice})},localStorage:storage,sessionStorage:storage,
location:{hostname:'localhost'},setTimeout:fn=>callbacks.push(fn),clearTimeout:()=>{}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
vm.runInContext('let renders=0; render=()=>{renders++}; state.view="search"; render.lastView="search"; state.user="lera"; state.connected=false;',sandbox);
let blur; let listenerCount=0;
const input={matches:()=>true,dataset:{},isConnected:true,value:'незаконченный запрос',selectionStart:5,
addEventListener:(event,fn,options)=>{assert.equal(event,'blur');assert(options.once);blur=fn;listenerCount++}};
sandbox.document.activeElement=input;
vm.runInContext('renderRealtime(); renderRealtime()',sandbox);
assert.equal(vm.runInContext('renders',sandbox),0);
assert.equal(listenerCount,1);assert.equal(input.selectionStart,5);assert.equal(input.value,'незаконченный запрос');
assert(notice.innerHTML.includes('восстанавливаем'));
vm.runInContext('state.connected=true; renderRealtime()',sandbox); assert.equal(notice.innerHTML,'');
sandbox.document.activeElement=null; blur({relatedTarget:{closest:()=>true}});
assert.equal(callbacks.length,0); // Do not swallow a navigation click after blur.
sandbox.document.activeElement=input; vm.runInContext('renderRealtime()',sandbox);
sandbox.document.activeElement=null; blur({relatedTarget:null}); callbacks.shift()();
assert.equal(vm.runInContext('renders',sandbox),1);
sandbox.document.activeElement=input;
vm.runInContext('state.view="selected"; renderRealtime()',sandbox);
assert.equal(vm.runInContext('renders',sandbox),2); // Server-driven step is not deferred.
vm.runInContext('let finishHistory; api=()=>new Promise(resolve=>finishHistory=resolve); state.view="home"; let pending=go("history"); go("search"); finishHistory({items:[{id:1}]});',sandbox);
(async()=>{
 await vm.runInContext('pending',sandbox);
 assert.equal(vm.runInContext('state.view',sandbox),'search');
 assert.equal(vm.runInContext('state.history',sandbox),undefined);
 vm.runInContext('let pendingAgain=go("history"); state.view="selected"; finishHistory({items:[]});',sandbox);
 await vm.runInContext('pendingAgain',sandbox);
 assert.equal(vm.runInContext('state.view',sandbox),'selected');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_watchlist_input_updates_results_without_replacing_field():
    js = (ROOT / 'frontend/app.js').read_text(encoding='utf-8')
    handler = js.split("[data-watchlist-search]')?.addEventListener('input',", 1)[1].split('\n', 1)[0]
    assert 'refreshWatchlistResults()' in handler and 'render()' not in handler
    assert "state.searchDraft = event.target.value" in js
    assert "searchInput.value = state.searchDraft ?? state.searchQuery" in js


def test_completed_session_reconnect_does_not_steal_current_section():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const sandbox={document:{querySelector:()=>({})},localStorage:storage,sessionStorage:storage,
location:{hostname:'localhost'},setTimeout:()=>{},clearTimeout:()=>{}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
vm.runInContext('let feedbackCalls=0; const originalFeedback=openPendingFeedback; openPendingFeedback=()=>feedbackCalls++; state.view="watchlist"; state.session={id:1,status:"completed"}; applyRealtimeSession({id:1,status:"completed"})',sandbox);
assert.equal(vm.runInContext('feedbackCalls',sandbox),0);
assert.equal(vm.runInContext('state.view',sandbox),'watchlist');
vm.runInContext('state.session.status="selected"; state.view="selected"; applyRealtimeSession({id:1,status:"completed"})',sandbox);
assert.equal(vm.runInContext('feedbackCalls',sandbox),0); // Ratings open only after an explicit action.
vm.runInContext('openPendingFeedback=originalFeedback; state.user="lera"; state.view="selected"; let finish; api=()=>new Promise(resolve=>finish=resolve); let pending= openPendingFeedback(); state.view="search"; finish({items:[{session_id:1,history_id:2,ratings:{lera:null}}]})',sandbox);
(async()=>{await vm.runInContext('pending',sandbox);assert.equal(vm.runInContext('state.view',sandbox),'search')})().catch(e=>{console.error(e);process.exitCode=1});
'''
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_primary_action_text_and_secondary_labels_have_readable_contrast():
    css = (ROOT / 'frontend/styles.css').read_text(encoding='utf-8')
    foreground = re.findall(r'\.button\s*\{[^}]*color:(#[0-9a-fA-F]{6})', css)[-1]
    accent = re.search(r'--accent:\s*(#[0-9a-fA-F]{6})', css)[1]
    endpoint = re.search(r'\.button\s*\{[^}]*linear-gradient\(110deg,var\(--accent\),(#[0-9a-fA-F]{6})\)', css)[1]
    muted = re.search(r'--muted:\s*(#[0-9a-fA-F]{6})', css)[1]
    surface = re.search(r'--surface-2:\s*(#[0-9a-fA-F]{6})', css)[1]

    def luminance(color):
        channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))

    def contrast(first, second):
        high, low = sorted((luminance(first), luminance(second)), reverse=True)
        return (high + .05) / (low + .05)

    assert min(contrast(foreground, accent), contrast(foreground, endpoint)) >= 4.5
    assert contrast(muted, surface) >= 4.5


def test_long_description_is_expandable_and_decision_precedes_alternatives():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const storage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const sandbox={document:{querySelector:()=>({})},localStorage:storage,sessionStorage:storage,
location:{hostname:'localhost'},setTimeout:()=>{},clearTimeout:()=>{}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
sandbox.longText='Описание фильма '.repeat(100)+'<script>bad()</script>';
let html=vm.runInContext('movieDescription(longText)',sandbox);
assert(html.includes('Полное описание') && html.includes('<details'));
assert(html.split('</p>')[0].length<260);
assert(html.includes('&lt;script&gt;') && !html.includes('<script>'));
assert.equal(vm.runInContext('movieDescription("Короткое описание")',sandbox).includes('<details'),false);
vm.runInContext('const film={id:"example",title:"Тест",overview:longText,year:2020,runtime:90,genres:["драма"],rating:8,match:90,poster_url:"/poster",backdrop_url:"/backdrop"}; state.session={recommendations:[film]}',sandbox);
html=vm.runInContext('renderResults()',sandbox);
assert(html.indexOf('data-action="accept-main"')<html.indexOf('Ещё может зайти'));
vm.runInContext('state.session.selected=film',sandbox);
assert(vm.runInContext('renderSelected()',sandbox).includes('Полное описание'));
'''
    result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_reading_full_card_description_never_votes_and_survives_repaint():
    if not shutil.which('node'):
        pytest.skip('Node required')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const handlers={}; let captures=0;
const card={focus:()=>{},style:{},setPointerCapture:()=>captures++,addEventListener:(name,fn)=>handlers[name]=fn};
const storage={getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
const sandbox={document:{querySelector:selector=>selector==='#swipe-card'?card:{}},
localStorage:storage,sessionStorage:storage,location:{hostname:'localhost'},setTimeout:()=>{},clearTimeout:()=>{}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),sandbox);
vm.runInContext(`let votes=[]; react=value=>votes.push(value); bindSwipeGestures();
state.user='lera'; state.deck=[{id:'film',title:'Film',overview:'A long description '.repeat(60)+'THE END <script>bad()</script>',year:2020,runtime:90,genres:[],poster_url:'/poster'}]`,sandbox);
const readingTarget={closest:()=>({})}, cardTarget={closest:()=>null};
handlers.keydown({target:readingTarget,key:'ArrowDown',preventDefault:()=>assert.fail('reading was intercepted')});
handlers.pointerdown({target:readingTarget,clientX:0,pointerId:1});
handlers.pointermove({clientX:200}); handlers.pointerup();
assert.equal(captures,0); assert.equal(vm.runInContext('votes.length',sandbox),0);
handlers.keydown({target:cardTarget,key:'ArrowRight',preventDefault:()=>{}});
assert.equal(vm.runInContext('votes.join()',sandbox),'like');
let html=vm.runInContext('renderSwipe()',sandbox);
assert(html.includes('Раскрыть целиком') && html.includes('THE END &lt;script&gt;') && !html.includes('<script>bad'));
assert(html.indexOf('card-description')>html.indexOf('poster-copy'));
vm.runInContext("state.expandedDescriptions.add('film')",sandbox);
html=vm.runInContext('renderSwipe()',sandbox);
assert(/data-description-key="film" open/.test(html));
'''
    result = subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
