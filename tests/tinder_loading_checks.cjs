const fs=require('fs'),vm=require('vm'),assert=require('assert');
function context(){
  const values=new Map(),storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
  const root={querySelector:()=>null,querySelectorAll:()=>[]};
  const box={document:{querySelector:()=>root},localStorage:storage,sessionStorage:storage,
    location:{hostname:'localhost'},setTimeout:()=>{},clearTimeout:()=>{}};
  vm.createContext(box);
  vm.runInContext(fs.readFileSync('frontend/app.js','utf8').replace(/\ninit\(\);\s*$/,''),box);
  vm.runInContext(`render=()=>{};state.user='lera';state.session={id:1};state.view='tinder';
    state.tinder={user:'lera',queue:[],seen:[],history:[],save:false,busy:false};
    let decks=[],rules=[];
    api=path=>new Promise((resolve,reject)=>{(path.includes('/api/tinder/')?decks:rules).push({resolve,reject});});`,box);
  return {box,run:s=>vm.runInContext(s,box)};
}
const card="{items:[{id:'available',title:'Есть в каталоге'}],cold_start:true,catalog_available:532}";
const rules="{user:'lera',session_id:1,permanent:[],temporary:[],disinterest:[]}";
(async()=>{
  for(const order of ['rules-first','deck-first']){
    const {run}=context();
    const deck=run('fetchTinder()'),exclusions=run('refreshExclusions()');
    if(order==='rules-first'){run(`rules[0].resolve(${rules})`);await exclusions;run(`decks[0].resolve(${card})`);await deck;}
    else{run(`decks[0].resolve(${card})`);await deck;run(`rules[0].resolve(${rules})`);await exclusions;}
    assert.equal(run('state.tinder.queue.length'),1,order);
    assert.equal(run('state.tinder.loaded'),true);
    assert.equal(run('state.tinder.busy'),false);
  }
  {
    const {run}=context();
    run(`state.exclusions=${rules};state.exclusionsFor=1;`);
    const old=run('fetchTinder()'),exclusions=run('refreshExclusions()');
    run(`rules[0].resolve({...${rules},permanent:[{kind:'genre',value:'хоррор'}]})`);await exclusions;
    assert.equal(run('decks.length'),2,'Changed restrictions automatically reload the invalidated request');
    run(`decks[0].resolve({items:[{id:'stale'}]})`);await old;
    assert.equal(run('state.tinder.busy'),true,'Old response cannot clear the current loading state');
    run(`decks[1].resolve(${card})`);await new Promise(setImmediate);
    assert.equal(run('state.tinder.queue[0].id'),'available');
  }
  {
    const {run}=context(),old=run('fetchTinder()');
    run(`state.user='nikita';state.tinder={user:'nikita',queue:[],seen:[],history:[]}`);
    const current=run('fetchTinder()');
    run(`decks[0].reject(Error('old profile failed'))`);await old;
    assert.equal(run('state.tinder.busy'),true);
    assert.equal(run('state.tinder.error'),'');
    run(`decks[1].resolve(${card})`);await current;
    assert.equal(run('state.tinder.queue[0].id'),'available');
  }
  {
    const {run}=context();
    const task=run('fetchTinder()');
    assert(run('renderTinder()').includes('Подбираем фильмы'));
    run(`decks[0].reject(Error('Нет связи'))`);await task;
    assert(run('renderTinder()').includes('Не удалось загрузить карточки'));
    assert(!run('renderTinder()').includes('Фильмы закончились'));
    const retry=run('fetchTinder()');run(`decks[1].resolve({items:[],catalog_available:20})`);await retry;
    assert(run('renderTinder()').includes('Фильмы закончились'));
  }
  {
    const {run}=context();
    run(`sessionStorage.setItem('tonight:tinder:lera',JSON.stringify({user:'lera',queue:[{id:'stale'}],seen:['acted','stale'],history:[],loaded:true}));state.tinder=null;openTinder();`);
    assert.equal(run('state.tinder.queue.length'),0);
    assert.equal(run('state.tinder.seen.join()'),'acted');
    run(`decks[0].resolve(${card})`);await new Promise(setImmediate);
    assert.equal(run('state.tinder.queue[0].id'),'available');
  }
  console.log('PASS: response orders, changed restrictions, stale response, profile switch, slow loading, error/retry, exhausted and restored decks');
})().catch(error=>{console.error(error);process.exitCode=1;});
