function createMovieMatch({state, root, render, shell, esc, poster, toast, onBrowse}) {
  let current=null, error='', networkError=false, busy=false, online=true, socket=null, timer=null, heartbeat=null;
  let tab='cards', editing=false, draft=null, detail=null, ending=false, joining=false, link='';
  const storageKey='tonight:movie-match';
  let token=localStorage.getItem('tonight:match-device');
  if(!token){const bytes=new Uint8Array(32);crypto.getRandomValues(bytes);token=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');localStorage.setItem('tonight:match-device',token);}
  const stored=()=>{try{return JSON.parse(localStorage.getItem(storageKey)||'null');}catch{return null;}};
  const saved=()=>{try{return JSON.parse(localStorage.getItem('tonight:match-saved')||'[]');}catch{return [];}};
  const disabled=()=>busy||!online?'disabled':'';
  function paint(){if(state.view==='match')render();}
  async function request(path, body){
    const response=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-Match-Token':token},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(15000)});
    const data=await response.json();
    if(!response.ok){const message=Array.isArray(data.detail)?data.detail.map(i=>i.msg.replace('Value error, ','')).join('. '):data.detail;const e=new Error(message||'Не удалось обновить комнату');e.status=response.status;throw e;}
    return data;
  }
  function apply(next){
    if(current && current.id===next.id && next.version<current.version)return;
    if(networkError){error='';networkError=false;}
    const before=current?.matches.length||0;
    const initial=!current;
    if(current && current.version!==next.version && editing && !busy && JSON.stringify(current.filters)!==JSON.stringify(next.filters)){draft=null;editing=false;error='Условия изменились. Проверьте их перед подтверждением.';}
    current=next;online=true;
    localStorage.setItem(storageKey,JSON.stringify({id:next.id,room:next.room,link}));
    if(!initial&&next.matches.length>before)toast('Есть новое совпадение! 🍿');
  }
  function stop(){clearTimeout(timer);clearInterval(heartbeat);const old=socket;socket=null;old?.close();}
  function connect(){
    stop();if(!current||['closed','left','expired'].includes(current.phase))return;
    const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/session/${current.id}/${current.me===0?'lera':'nikita'}`);socket=ws;
    ws.onopen=()=>{if(socket!==ws)return;online=true;sync();heartbeat=setInterval(()=>{if(ws.readyState===1)ws.send('ping');},15000);};
    ws.onmessage=e=>{if(socket!==ws)return;const event=JSON.parse(e.data);if(event.type==='privacy_reset'){current=null;localStorage.removeItem(storageKey);error='Комната удалена на основном компьютере.';stop();paint();return;}if(event.presence)state.presence=event.presence;if(event.type!=='pong')sync();};
    ws.onclose=()=>{if(socket!==ws)return;clearInterval(heartbeat);online=false;paint();timer=setTimeout(connect,2500);};
    ws.onerror=()=>{};
  }
  async function sync(){
    if(!current)return;
    const id=current.id;
    try{const next=await request(`/api/sessions/${id}/match`);if(current?.id!==id)return;apply(next);paint();}
    catch(e){if(current?.id!==id)return;online=false;networkError=!e.status;error=e.status?e.message:'Нет связи с Tonight. Проверьте Wi-Fi и оставьте приложение на компьютере открытым.';paint();}
  }
  async function action(op, extra={}){
    if(!current||busy)return;
    busy=true;error='';networkError=false;paint();
    try{
      apply(await request(`/api/sessions/${current.id}/match`,{op,version:current.version,...extra}));
      if(op==='filters'){editing=false;draft=null;error='';toast('Новые условия видны обоим. Подтвердите их заново.');}
      if(op==='save'){
        const movie=current.matches.find(m=>m.id===extra.movie_id);
        if(movie){const list=saved();if(!list.some(m=>m.id===movie.id))list.push(movie);localStorage.setItem('tonight:match-saved',JSON.stringify(list));toast('Сохранено в ваш список в этом браузере');}
      }
      if(op==='leave'||op==='close'){ending=false;stop();}
    }catch(e){networkError=!e.status;error=e.status?e.message:'Не удалось передать ответ. Восстанавливаем связь с Tonight.';if(!e.status)online=false;await sync();}
    finally{busy=false;paint();}
  }
  async function enter(room){
    state.ws?.close();state.ws=null;clearTimeout(state.reconnectTimer);
    state.view='match';joining=true;error='';paint();
    try{
      if(room)apply(await request('/api/movie-match/join',{room}));
      else{
        const old=stored();
        if(old){link=old.link||'';apply(await request(`/api/sessions/${old.id}/match`));}
        else{
          const profile=state.user?`&profile=${encodeURIComponent(state.user)}`:'';
          apply(await request(`/api/sessions/new?movie_match=true${profile}`,{}));
        }
      }
      let base=location.origin;
      if(!link){try{const info=await fetch('/api/invite').then(r=>r.json());const candidate=new URL(info.url);candidate.port=location.port; base=candidate.origin;}catch{}link=`${base}/?join=1&room=${encodeURIComponent(current.room)}`;}
      localStorage.setItem(storageKey,JSON.stringify({id:current.id,room:current.room,link}));
      const url=new URL(location.href);url.searchParams.set('room',current.room);url.searchParams.set('join','1');history.replaceState(null,'',url);
      connect();
    }catch(e){error=e.status?e.message:'Не удалось подключиться к Tonight. Проверьте Wi-Fi и оставьте приложение на компьютере открытым.';}
    finally{joining=false;paint();}
  }
  const button=(label,op,extra='',cls='secondary')=>`<button class="button ${cls}" data-mm-action="${op}" ${extra} ${disabled()}>${label}</button>`;
  function summary(f){return [f.max_runtime?`До ${f.max_runtime} минут`:'Любая длительность',f.min_rating?`Рейтинг от ${f.min_rating}`:'Любой рейтинг',f.min_year||f.max_year?`${f.min_year||'…'}–${f.max_year||'…'}`:'Любой год',f.included_genres.length?f.included_genres.join(', '):'Все жанры',f.excluded_genres.length?`Без: ${f.excluded_genres.join(', ')}`:'',f.exclude_watched?'Без просмотренного':'Просмотренное допустимо'].filter(Boolean).map(t=>`<span>${esc(t)}</span>`).join('');}
  function filters(){
    const f=draft||current.filters;
    const number=(name,label,min,max,step='1')=>`<label>${label}<input name="${name}" type="number" min="${min}" max="${max}" step="${step}" value="${f[name]||''}" placeholder="Неважно"></label>`;
    return `<form data-mm-filters class="mm-filters"><h2>Условия для двоих</h2><p>Изменения увидят оба. Выбор продолжится после двух подтверждений; прежние голоса сохранятся.</p><div class="mm-fields">${number('max_runtime','Не дольше, минут',1,1440)}${number('min_rating','Рейтинг от',0,10,'.1')}${number('min_year','Год от',1888,2100)}${number('max_year','Год до',1888,2100)}</div><fieldset><legend>Хочется жанры</legend><p class="hint">Подойдёт хотя бы один из отмеченных.</p><div class="chip-grid">${genres.map(g=>`<label class="mm-check"><input type="checkbox" name="included_genres" value="${esc(g)}" ${f.included_genres.includes(g)?'checked':''}>${esc(g)}</label>`).join('')}</div></fieldset><fieldset><legend>Точно без</legend><div class="chip-grid">${genres.map(g=>`<label class="mm-check"><input type="checkbox" name="excluded_genres" value="${esc(g)}" ${f.excluded_genres.includes(g)?'checked':''}>${esc(g)}</label>`).join('')}</div></fieldset><label class="mm-check"><input type="checkbox" name="exclude_watched" ${f.exclude_watched?'checked':''}>Исключать просмотренное</label><p class="hint">Учитываем доступные отметки создателя и ответы «Уже смотрел(а)» в комнате. Личные данные гостя не запрашиваем. Исключения создателя на момент создания комнаты действуют весь выбор; сами личные данные не раскрываются.</p><div class="footer-actions"><button class="button" type="submit" ${disabled()}>Показать условия обоим</button><button class="button ghost" type="button" data-mm-edit-cancel>Отмена</button></div></form>`;
  }
  const genres=['комедия','драма','боевик','sci-fi','фэнтези','детектив','триллер','хоррор','романтика','мультфильм','семейный','документальное'];
  function film(movie, result=false){
    const chosen=current?.proposal===movie.id, confirmed=current?.confirmed.includes(current.me);
    const savedAlready=saved().some(m=>m.id===movie.id);
    return `<article class="mm-film ${result?'mm-result':''}" aria-label="${esc(movie.title)}"><div class="mm-poster">${poster(movie)}</div><div class="mm-film-copy">${result?'<span class="mm-mutual">♥ Оба хотите посмотреть</span>':''}<h2>${esc(movie.title)}</h2><p class="meta">${movie.year||'Год не указан'} · ${movie.runtime?`${movie.runtime} мин`:'Длительность неизвестна'} · ${movie.rating?`★ ${movie.rating} / 10`:'Без рейтинга'}</p><p class="hint">${esc(movie.genres.join(' · '))}</p><p class="mm-synopsis">${esc((movie.overview||'Описание пока не добавлено').slice(0,240))}${movie.overview?.length>240?'…':''}</p><button class="button ghost" data-mm-details="${esc(movie.id)}">Подробнее о фильме</button>${result?`<div class="footer-actions">${current.phase==='voting'?chosen?confirmed?'<p role="status">Вы подтвердили. Ждём второго участника.</p>':button('Да, выбираем этот','confirm',`data-mid="${esc(movie.id)}"`,''):button('Предложить на вечер','propose',`data-mid="${esc(movie.id)}"`,''):''}${button(savedAlready?'✓ В моём списке':'♡ Сохранить себе','save',`data-mid="${esc(movie.id)}"`)}</div>`:''}</div></article>`;
  }
  function content(){
    let body='';
    if(joining)body='<div class="mm-empty" role="status"><h1>Подключаемся к комнате…</h1><p>Восстанавливаем сохранённый выбор.</p></div>';
    else if(!current)body=`<div class="mm-empty"><p class="eyebrow">Movie Match</p><h1>Выберите фильм вдвоём</h1><p>Пригласите второго человека. Каждый отвечает за себя, а Tonight покажет общие «Хочу посмотреть».</p><button class="button" data-mm-new>Создать новую комнату</button><button class="button ghost" data-mm-home>На главную</button></div>`;
    else {
      const p=current.phase, me=current.people[current.me], other=current.people[1-current.me];
      const otherOnline=state.presence[current.me===0?'nikita':'lera'];
      const terminal=['closed','left','expired'].includes(p);
      const status=!online?'Связь потеряна · восстанавливаем':!other?'Ждём второго участника':otherOnline?'Второй участник в сети':'Второй участник не в сети · ответы сохранены';
      body=`<header class="mm-head"><div><p class="eyebrow">Tonight · Movie Match</p><h1>${p==='finished'?'Фильм на вечер выбран':terminal?'Совместный выбор завершён':'Что посмотрим вдвоём?'}</h1></div><span class="mm-status" role="status"><i class="dot ${online&&otherOnline?'online':''}"></i>${status}</span></header>`;
      if(terminal)body+=`<section class="mm-empty"><h2>${p==='expired'?'Срок комнаты истёк':p==='left'?'Участник вышел из комнаты':'Комната закрыта'}</h2><p>Голоса в этой комнате больше не принимаются.</p><button class="button" data-mm-new>Создать новую комнату</button><button class="button ghost" data-mm-saved>Мой список</button><button class="button ghost" data-mm-home>На главную</button></section>`;
      else {
        body+=`<ol class="mm-steps" aria-label="Этапы выбора"><li class="${p==='lobby'?'active':''}">1. Подключаемся</li><li class="${p==='voting'?'active':''}">2. Выбираем</li><li class="${p==='finished'?'active':''}">3. Решаем вместе</li></ol>`;
        if(p==='lobby'){
          body+=`<section class="mm-lobby"><div class="panel"><span class="mm-big-icon" aria-hidden="true">${other?'🍿':'↗'}</span><h2>${other?'Вы оба здесь':'Позовите того, с кем смотрите'}</h2><p>${other?'Проверьте общие условия и нажмите «Мне подходит». Каждый выбирает фильмы независимо.':'Отправьте ссылку второму участнику или покажите QR-код. Оба устройства должны быть в одной Wi-Fi-сети; Tonight на компьютере должен оставаться открытым.'}</p><label class="mm-link-label">Ссылка-приглашение<input readonly value="${esc(link)}" data-mm-link></label><div class="footer-actions"><button class="button" data-mm-copy>Скопировать приглашение</button><button class="button ghost" data-mm-qr>Показать QR-код</button></div><p class="hint">Комната на двоих · приглашение действует 24 часа · регистрация не нужна</p></div><div class="panel mm-readiness"><h2>Готовность участников</h2><p>🍿 Вы <strong>${me.ready?'✓ Условия подходят':'Проверяете условия'}</strong></p><p>🎬 Второй участник <strong>${!other?'Ожидаем подключения':other.ready?'✓ Условия подходят':'Проверяет условия'}</strong></p><div class="mm-conditions">${summary(current.filters)}</div><button class="button secondary" data-mm-edit ${disabled()}>Изменить общие условия</button>${other?button(me.ready?'✓ Ждём подтверждения второго':'Мне подходит — начать выбор','ready','','large'):'<p class="hint">Кнопка начала появится, когда подключится второй участник.</p>'}</div></section>`;
        }else if(p==='finished'){
          body+=`<div class="mm-celebrate" role="status">♥ Вы оба подтвердили этот фильм</div>${tab==='matches'?`<div class="mm-results">${current.matches.map(m=>film(m,true)).join('')}</div><button class="button secondary" data-mm-tab="cards">К итоговому фильму</button>`:current.final?film(current.final,true):'<p>Карточка фильма больше недоступна в каталоге.</p>'}<p class="hint">Приятного вечера! Фильм не отмечен как просмотренный.</p><div class="footer-actions">${button('Завершить сессию','close')}<button class="button secondary" data-mm-tab="matches">Все совпадения · ${current.matches.length}</button></div>`;
        }else{
          body+=`<div class="mm-toolbar"><p>Вы оценили <strong>${me.progress}</strong> фильмов · осталось ${current.remaining}<br><span class="hint">${otherOnline?'Второй участник выбирает':'Ждём возвращения второго участника'} · оценено ${other?.progress||0}</span></p><div class="mm-tabs"><button class="button ${tab==='cards'?'':'secondary'}" data-mm-tab="cards">Выбирать</button><button class="button ${tab==='matches'?'':'secondary'}" data-mm-tab="matches">Совпадения · ${current.matches.length}</button></div></div><details class="mm-active-conditions"><summary>Общие условия</summary><div class="mm-conditions">${summary(current.filters)}</div><button class="button ghost" data-mm-edit>Предложить изменить</button></details>`;
          if(current.proposal){const m=current.matches.find(m=>m.id===current.proposal);body+=`<aside class="mm-proposal" role="status"><strong>На вечер предлагается «${esc(m?.title||'Фильм')}»</strong><p>${current.confirmed.includes(current.me)?'Вы подтвердили. Второй участник ещё решает.':'Второй участник предлагает этот фильм. Подтвердите, если согласны.'}</p><div class="footer-actions">${!current.confirmed.includes(current.me)?button('Подтвердить фильм','confirm',`data-mid="${esc(current.proposal)}"`,''):''}${button('Вернуться к подбору','cancel')}</div></aside>`;}
          if(tab==='matches')body+=current.matches.length?`<div class="mm-results">${current.matches.map(m=>film(m,true)).join('')}</div><button class="button secondary" data-mm-tab="cards">Продолжить подбор</button>`:`<section class="mm-empty"><span class="mm-big-icon">♡</span><h2>Пока нет общих «Хочу посмотреть»</h2><p>Продолжайте выбор или согласуйте более широкие условия. Совпадение появится, только когда фильм понравится обоим.</p><button class="button" data-mm-tab="cards">Продолжить подбор</button><button class="button ghost" data-mm-edit>Изменить условия</button></section>`;
          else if(current.card)body+=`${film(current.card)}<div class="mm-votes" aria-label="Хотите посмотреть этот фильм?">${button('✕ Не сейчас','vote',`data-mid="${esc(current.card.id)}" data-vote="no"`,'secondary')}${button('♥ Хочу посмотреть','vote',`data-mid="${esc(current.card.id)}" data-vote="yes"`,'large')}${button('✓ Уже смотрел(а)','vote',`data-mid="${esc(current.card.id)}" data-vote="watched"`,'ghost')}</div><p class="hint mm-private">Ваши отрицательные ответы не видны второму участнику. Личные оценки Tonight IQ не меняются.</p>`;
          else body+=`<section class="mm-empty"><h2>Вы оценили все доступные фильмы</h2><p>${current.matches.length?'Общие варианты уже в списке совпадений.':'Дождитесь ответов второго участника или расширьте общие условия.'}</p><button class="button" data-mm-tab="matches">Открыть совпадения · ${current.matches.length}</button><button class="button ghost" data-mm-edit>Изменить условия</button></section>`;
        }
        if(editing)body=`<header class="mm-head"><p class="eyebrow">Movie Match · общие условия</p></header>`+filters();
        body+=`<footer class="mm-footer"><button class="button ghost" data-mm-saved>♡ Мой список</button><button class="button ghost" data-mm-end>Выйти из комнаты</button></footer>`;
      }
      if(ending)body+=`<section class="panel mm-end" role="alert"><h2>Завершить выбор для двоих?</h2><p>Второй участник увидит, что комната закрыта. Просто закрыв вкладку, вы сможете вернуться позже.</p>${button('Выйти и закрыть комнату','leave')}<button class="button ghost" data-mm-end-cancel>Остаться</button></section>`;
    }
    if(tab==='saved')body=`<header class="mm-head"><h1>Мой список</h1><button class="button secondary" data-mm-tab="cards">Назад к комнате</button></header><p class="hint">Сохранено только для вас в этом браузере. Список второго участника не меняется.</p>${saved().length?saved().map(m=>film(m)).join(''):'<div class="mm-empty"><h2>Сохранённых фильмов пока нет</h2><p>Нажмите «Сохранить себе» рядом с совпадением.</p></div>'}`;
    if(detail)body+=`<div class="mm-dialog" role="dialog" aria-modal="true" aria-labelledby="mm-detail-title" tabindex="-1"><div class="panel"><button class="button secondary" data-mm-detail-close>Вернуться к выбору</button><h2 id="mm-detail-title">${esc(detail.title)}</h2><p>${esc(detail.year)} · ${detail.runtime?`${detail.runtime} мин`:'Длительность неизвестна'} · ${esc(detail.genres.join(' · '))}</p><p>${esc(detail.overview||'Описание пока не добавлено')}</p></div></div>`;
    return shell(`<section class="mm"><button class="button ghost choices-back" data-mm-back>← Способы выбора</button>${error?`<div class="mm-error" role="alert">${esc(error)} <button class="button ghost" data-mm-retry>Повторить</button></div>`:''}${!online&&current?'<p class="mm-offline" role="status">Ответы сохранены на компьютере. Дождитесь восстановления связи; непринятый ответ можно повторить.</p>':''}${body}</section>`,{nav:false});
  }
  function bind(){
    root.querySelectorAll('[data-mm-open]').forEach(b=>b.addEventListener('click',()=>enter()));
    if(state.view!=='match')return;
    root.querySelector('[data-mm-back]')?.addEventListener('click',()=>{stop();history.replaceState(null,'',location.pathname);if(onBrowse)onBrowse();else location.reload();});
    root.querySelectorAll('[data-mm-new]').forEach(b=>b.addEventListener('click',()=>{stop();current=null;link='';localStorage.removeItem(storageKey);tab='cards';enter();}));
    root.querySelector('[data-mm-home]')?.addEventListener('click',()=>{stop();current=null;history.replaceState(null,'',location.pathname);localStorage.removeItem(storageKey);location.reload();});
    root.querySelectorAll('[data-mm-action]').forEach(b=>b.addEventListener('click',()=>action(b.dataset.mmAction,{...(b.dataset.mid?{movie_id:b.dataset.mid}:{}),...(b.dataset.vote?{vote:b.dataset.vote}:{})})));
    root.querySelector('[data-mm-copy]')?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(link);toast('Приглашение скопировано');}catch{root.querySelector('[data-mm-link]')?.select();toast('Выделили ссылку — скопируйте её');}});
    root.querySelector('[data-mm-qr]')?.addEventListener('click',()=>{const box=document.createElement('div');box.className='mm-qr panel';const img=document.createElement('img');img.alt='QR-код приглашения в эту комнату';img.src=`/api/sessions/${current.id}/match/qr?room=${encodeURIComponent(current.room)}`;box.append(img);const close=document.createElement('button');close.className='button secondary';close.textContent='Скрыть QR-код';close.onclick=()=>box.remove();box.append(close);root.querySelector('.mm-lobby .panel').append(box);});
    root.querySelectorAll('[data-mm-edit]').forEach(b=>b.addEventListener('click',()=>{editing=true;draft=structuredClone(current.filters);paint();root.querySelector('[data-mm-filters]')?.scrollIntoView({block:'start'});}));
    root.querySelector('[data-mm-edit-cancel]')?.addEventListener('click',()=>{editing=false;draft=null;paint();});
    const form=root.querySelector('[data-mm-filters]');
    const readForm=()=>{const f=new FormData(form);return {max_runtime:f.get('max_runtime')?Number(f.get('max_runtime')):null,min_rating:Number(f.get('min_rating')||0),min_year:f.get('min_year')?Number(f.get('min_year')):null,max_year:f.get('max_year')?Number(f.get('max_year')):null,included_genres:f.getAll('included_genres'),excluded_genres:f.getAll('excluded_genres'),exclude_watched:f.has('exclude_watched')};};
    form?.addEventListener('input',()=>{draft=readForm();});form?.addEventListener('submit',e=>{e.preventDefault();draft=readForm();action('filters',{filters:draft});});
    root.querySelectorAll('[data-mm-tab]').forEach(b=>b.addEventListener('click',()=>{tab=b.dataset.mmTab;detail=null;paint();}));
    root.querySelectorAll('[data-mm-saved]').forEach(b=>b.addEventListener('click',()=>{tab='saved';paint();}));
    root.querySelectorAll('[data-mm-details]').forEach(b=>b.addEventListener('click',()=>{detail=[current?.card,...current?.matches||[],...saved()].find(m=>m?.id===b.dataset.mmDetails);paint();root.querySelector('[data-mm-detail-close]')?.focus();}));
    root.querySelector('[data-mm-detail-close]')?.addEventListener('click',()=>{detail=null;paint();});
    root.querySelector('.mm-dialog')?.addEventListener('keydown',e=>{if(e.key==='Escape'){detail=null;paint();}if(e.key==='Tab'){e.preventDefault();root.querySelector('[data-mm-detail-close]').focus();}});
    root.querySelector('[data-mm-retry]')?.addEventListener('click',()=>current?sync():enter(new URLSearchParams(location.search).get('room')));
    root.querySelector('[data-mm-end]')?.addEventListener('click',()=>{ending=true;paint();root.querySelector('.mm-end')?.scrollIntoView();});
    root.querySelector('[data-mm-end-cancel]')?.addEventListener('click',()=>{ending=false;paint();});
  }
  window.addEventListener('online',()=>{if(current&&state.view==='match'){error='';sync();connect();}});
  window.addEventListener('offline',()=>{online=false;paint();});
  // The realtime signal is an invalidation, never a private room payload.
  // A fallback refresh also recovers dropped events and sleeping tabs.
  setInterval(()=>{if(current&&state.view==='match'&&!document.hidden&&!busy&&!editing)sync();},7000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&current&&state.view==='match'){sync();if(!socket||socket.readyState>1)connect();}});
  return {content,bind,hasSession:()=>Boolean(stored()),entry:()=>`<button class="button large" data-mm-open>${stored()?'Продолжить совместный выбор':'Создать комнату для двоих'}</button>${stored()?'<p class="hint">Комната и ваши ответы сохранены в этом браузере.</p>':''}`,resume:async({fromLinkOnly=false}={})=>{const room=new URLSearchParams(location.search).get('room');if(room||(!fromLinkOnly&&stored())){await enter(room||null);return true;}return false;}};
}
