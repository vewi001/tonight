const root = document.querySelector('#app');
const toastNode = document.querySelector('#toast');

const state = {
  user: localStorage.getItem('tonight:user'),
  accessCode: sessionStorage.getItem('tonight:access-code') || '',
  session: null,
  exclusions:null, exclusionsFor:null, exclusionsAt:0, exclusionsPending:false, exclusionBusy:false, exclusionDraft:{},
  roulette: null, rouletteRequest: 0, tonight: null, tonightRequest: 0, tinder: null, tinderRequest: 0,
  personal: null, personalUser: null, personalAt: 0, personalPending: false, personalError: '', personalRevision: 0,
  setup: null,
  catalog: null, catalogTimer: null, catalogError: '', catalogRequest: 0,
  expansion: null, expansionTimer: null, expansionPending: false, expansionCount: 50,
  invite: null,
  update: null, updateTimer: null, updateDismissed: '', updateInstallingFrom: null,
  view: 'loading',
  searchDraft: null, navigationRequest: 0, pendingChoice: null,
  presence: { lera: false, nikita: false },
  connected: true,
  prefs: { moods: [], energy: null, max_runtime: 120, min_year: 2000, disliked_genres: [] },
  deck: [], total: 20, ws: null, reconnectTimer: null, reconnectAttempts: 0, wasDisconnected: false,
  expandedDescriptions: new Set(),
  historyId: null, feedbackMovie:null, feedbackCompany:null, modal: null, deferMovieId: null, privacyDeleteOpen: false, waitTimer: null, recovering: false, restarting: false, waitError: '', backups: [], backupImportFile: null, searchQuery:'', searchResults:[], weeklyPicks:[], franchises:[], diagnostics:null, usageSummary:null, watchlistHiddenCount:0, watchlistQuery:'', watchlistGenre:'',
};

const moods = [
  ['laugh','😂','Поржать'],['smart','🧠','Что-то умное'],['scary','😱','Пощекотать нервы'],
  ['emotional','🥹','Эмоциональное'],['cozy','🛋','Уютное'],['action','🔥','Экшен'],
  ['mystery','🕵️','Загадка'],['wow','🤯','Чтобы офигеть'],['romance','❤️','Романтика'],
  ['atmosphere','🌌','Атмосферное'],['surprise','🎲','Удивите меня'],
];
const genres = ['хоррор','романтика','комедия','драма','боевик','sci-fi','фэнтези','детектив','триллер','мультфильм','мюзикл','документальное'];
const reactionMap = [
  ['love','❤️','Очень понравился'],['like','👍','Понравился'],['okay','🤷','Нормальный'],['dislike','👎','Не понравился'],['unseen','❔','Не смотрел(а)'],
];
const feedbackMap = [['😍','Офигенно',5],['🙂','Хорошо',4],['😐','Нормально',3],['🙁','Не зашло',2],['💀','Ужас',1]];
const names = { lera: 'Первый зритель', nikita: 'Второй зритель' };
const emojis = { lera: '🍿', nikita: '🎬' };
const genreMoodLabels = {
  'комедия':'лёгкое и смешное', 'семейный':'уютное', 'мультфильм':'уютное',
  'драма':'эмоциональное', 'романтика':'романтическое', 'хоррор':'страшное',
  'триллер':'напряжённое', 'детектив':'загадочное', 'загадка':'загадочное',
  'боевик':'динамичное', 'приключения':'приключенческое', 'sci-fi':'фантастическое',
  'фэнтези':'сказочное', 'документальное':'познавательное', 'мюзикл':'музыкальное',
};

function esc(value = '') {
  return String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

function safeTrailerUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(value);
    const key = url.searchParams.get('v') || '';
    return url.protocol === 'https:' && url.hostname === 'www.youtube.com' && url.pathname === '/watch' && /^[A-Za-z0-9_-]{11}$/.test(key) ? url.href : null;
  } catch (_) { return null; }
}

function trailerButton(movie, classes = 'button secondary') {
  const url = safeTrailerUrl(movie?.trailer_url);
  return url ? `<a class="${classes}" href="${esc(url)}" target="_blank" rel="noopener noreferrer">▶ Смотреть трейлер</a>` : '';
}

function poster(movie, { eager = false } = {}) {
  if(movie.poster_available===false || !movie.poster_url)return '<span class="poster-placeholder" role="img" aria-label="Постер отсутствует">Постер пока не загружен</span>';
  return `<img src="${esc(movie.poster_url)}" alt="Постер: ${esc(movie.title)}" loading="${eager ? 'eager' : 'lazy'}"${eager ? ' fetchpriority="high"' : ''} draggable="false" data-poster>`;
}
function bindPosters(scope=root) {
  scope.querySelectorAll('img[data-poster]').forEach(img=>{
    const unavailable=()=>{const note=document.createElement('span');note.className='poster-placeholder';note.setAttribute('role','img');note.setAttribute('aria-label','Постер недоступен');note.textContent='Постер недоступен';img.replaceWith(note);};
    img.addEventListener('error',unavailable,{once:true});if(img.complete && !img.naturalWidth)unavailable();
  });
}

function similarityTraits(movie) {
  const moods = [...new Set((movie?.genres || []).map(genre => genreMoodLabels[genre]).filter(Boolean))];
  return {
    genres: (movie?.genres || []).slice(0, 3),
    moods: moods.slice(0, 2),
    franchise: Boolean(movie?.franchise_key),
  };
}

function catalogUpdatedText() {
  const raw = state.setup?.catalog_sync?.last_sync_at;
  if (!raw) return 'Каталог работает локально';
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return 'Каталог работает локально';
  return `Каталог обновлён ${parsed.toLocaleDateString('ru-RU', {day:'numeric', month:'long'})}`;
}

function isRemoteClient() {
  return !['localhost', '127.0.0.1', '::1'].includes(location.hostname);
}

function inviteCard() {
  if (isRemoteClient() || !state.invite?.url) return '';
  return `<aside class="invite-card" aria-labelledby="invite-title">
    <img src="/api/invite/qr.svg" alt="QR-код для подключения к Tonight">
    <div><p class="eyebrow">Пригласить второго зрителя</p><h3 id="invite-title">Открой камерой телефона</h3><p>Телефон должен быть подключён к той же Wi-Fi-сети.</p><p class="hint"><strong>Код вечера: ${esc(state.invite.access_code || '—')}</strong><br>Скажите его только тому, кого зовёте.</p><div class="invite-address"><code>${esc(state.invite.display_url)}</code><button class="button secondary" data-action="copy-invite">Скопировать адрес</button></div></div>
  </aside>`;
}

async function api(path, options = {}) {
  const eveningHeaders = isRemoteClient() && state.accessCode ? {'X-Tonight-Code': state.accessCode} : {};
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { 'Content-Type': 'application/json', 'X-Tonight-Request': '1', ...eveningHeaders, ...(options.headers || {}) },
    });
  } catch(error) {
    if(error.name==='AbortError')throw error;
    throw new Error('Нет связи с Tonight. Оставьте приложение на компьютере открытым и повторите действие.');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = Array.isArray(body.detail) ? body.detail.map(item => item.msg).filter(Boolean).join('. ') : body.detail;
    throw new Error(detail || 'Что-то пошло не так');
  }
  if (options.method && options.method !== 'GET' && !path.startsWith('/api/search/smart/')) { state.personalAt = 0; state.personalRevision++; }
  return response.json();
}

function toast(message) {
  toastNode.textContent = message;
  toastNode.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => toastNode.classList.remove('show'), 2600);
}

function shell(content, { narrow = false, nav = true } = {}) {
  const identity = state.user ? `<button class="icon-button identity-pill" data-action="switch-user" aria-label="Сменить зрителя: ${names[state.user]}">${emojis[state.user]} <span>${names[state.user]}</span><span class="identity-change">· Сменить</span></button>` : '';
  const credits = state.setup?.tmdb_movies ? `<footer class="data-credits" aria-label="Источники данных"><a href="https://www.themoviedb.org/" target="_blank" rel="noopener noreferrer"><img src="/assets/tmdb.svg" alt="TMDB"></a><span>This product uses the TMDB API but is not endorsed or certified by TMDB.</span></footer>` : '';
  return `<div class="shell">
    ${nav ? `<header class="topbar"><button class="brand" data-view="home">Tonight <span>🍿</span></button>${identity}<button class="icon-button nav-toggle" data-action="toggle-nav" aria-expanded="${!!state.navOpen}" aria-controls="main-navigation">Разделы ${state.navOpen ? '−' : '+'}</button><nav id="main-navigation" class="top-actions ${state.navOpen ? 'is-open' : ''}" aria-label="Основная навигация">
      <button class="icon-button" data-view="choices">✧ <span class="nav-label">Выбрать фильм</span></button><button class="icon-button" data-view="search">⌕ <span class="nav-label">Найти фильм</span></button>
      <button class="icon-button" data-view="watchlist">♡ <span class="nav-label">На потом</span></button>
      <button class="icon-button" data-view="history">◷ <span class="nav-label">История</span></button>
      <details class="nav-more"><summary>Ещё</summary><div><button class="icon-button" data-view="weekly">✦ <span class="nav-label">Неделя</span></button><button class="icon-button" data-view="franchises">≡ <span class="nav-label">Серии</span></button><button class="icon-button" data-view="taste">♡ <span class="nav-label">Наш вкус</span></button><button class="icon-button" data-view="library">▤ <span class="nav-label">Каталог и обновления</span></button><button class="icon-button" data-view="diagnostics">✓ <span class="nav-label">Проверить приложение</span></button></div></details>
    </nav></header>` : ''}
    <div data-update-banner>${updateDialog() || ['diagnostics','catalog'].includes(state.view) ? '' : updateControls()}</div>
    <main id="main" class="page ${narrow ? 'narrow' : ''}">${['tonight','roulette','filters','results','waiting','weekly'].includes(state.view)?temporaryExclusions():''}${content}${['diagnostics','catalog'].includes(state.view) ? `<div data-update-panel>${updateDialog() ? '' : updateControls(true)}</div>` : ''}</main>
    ${credits}
    <div data-connection-status role="status">${connectionNotice()}</div>
    <div data-update-dialog>${updateDialog()}</div>
  </div>`;
}

function connectionNotice() {
  return !state.connected && state.user ? '<div class="reconnect">Связь пропала — восстанавливаем…</div>' : '';
}

function renderRealtime() {
  const active = document.activeElement;
  // Keep the actual input node alive: replacing it can dismiss a phone keyboard.
  // A server-driven step change still takes precedence over this local draft.
  if (render.lastView === state.view && active?.matches('input:not([type="file"]), textarea, select')) {
    const notice = root.querySelector('[data-connection-status]');
    if (notice) notice.innerHTML = connectionNotice();
    if (!active.dataset.repaintPending) {
      active.dataset.repaintPending = '1';
      active.addEventListener('blur', event => {
        delete active.dataset.repaintPending;
        // Do not replace the button between pointerdown (blur) and click.
        if (event.relatedTarget?.closest('button, a, label')) return;
        setTimeout(() => { if (active.isConnected) renderRealtime(); }, 0);
      }, {once:true});
    }
    return;
  }
  render();
}

function render() {
  clearTimeout(state.waitTimer);
  const viewChanged = render.lastView !== state.view;
  const openDisclosures = !viewChanged ? new Set([...root.querySelectorAll('details[open]:not([data-render-state])')].map(el=>el.dataset.disclosureKey || el.dataset.descriptionKey || el.querySelector('summary')?.textContent)) : new Set();
  if (viewChanged) state.navOpen = false;
  render.lastView = state.view;
  if (state.view === 'loading') {
    root.innerHTML = shell('<div class="hero-home" role="status" aria-label="Открываем Tonight"><div class="skeleton"></div><p>Открываем Tonight…</p></div>', { nav:false });
    if (viewChanged) requestAnimationFrame(() => window.scrollTo(0, 0));
    return;
  }
  const views = {
    choices: renderChoices,
    setup: renderSetup, home: renderHome, tonight: renderTonight, roulette: renderRoulette, tinder: renderTinder, vibe: renderVibe, filters: renderFilters,
    swipe: renderSwipe, waiting: renderWaiting, results: renderResults, quick: renderQuick,
    selected: renderSelected, watching:renderWatching, feedback: renderFeedback, eveningFeedback: renderEveningFeedback, history: renderHistory, weekly: renderWeekly, franchises: renderFranchises, diagnostics: renderDiagnostics,
    taste: renderTaste, watchlist: renderWatchlist, search: renderSearch, error: renderError, catalog: renderCatalog,
  };
  root.innerHTML = (views[state.view] || renderHome)();
  root.querySelectorAll('details').forEach(el=>{if(openDisclosures.has(el.dataset.disclosureKey || el.dataset.descriptionKey || el.querySelector('summary')?.textContent))el.open=true;});
  bindCommon();
  bindExclusions();
  if (state.view === 'swipe') bindSwipeGestures();
  if (state.view === 'waiting') scheduleWaitingCheck();
  if (state.modal) renderModal();
  if (state.deferMovieId) renderDeferDialog();
  if (state.privacyDeleteOpen) renderPrivacyDeleteDialog();
  if (state.view === 'home' && state.user && !state.personalPending && Date.now() - state.personalAt > 30000) refreshPersonal();
  if(state.user && ['home','tonight','tinder','roulette','taste','filters','results','waiting','weekly'].includes(state.view) && !state.exclusionsPending && !state.exclusionError && (!exclusionData() || Date.now()-state.exclusionsAt>30000))refreshExclusions();
  if (viewChanged) requestAnimationFrame(() => window.scrollTo(0, 0));
}

function renderSetup() {
  const o = state.setup?.ollama || {};
  const available = state.setup?.catalog_available ?? 0;
  return shell(`<section class="panel" style="margin-top:8vh">
    <p class="eyebrow">Первый запуск</p><h2>Добро пожаловать в Tonight 🍿</h2>
    <p class="lede">Оцените впечатления от знакомых фильмов. Tonight учтёт ваши ответы при подборе для двоих.</p>
    <div class="setup-list">
      <div class="setup-row"><span>Доступно для выбора</span><strong class="${available?'ok':'warn'}">${available} из ${state.setup?.catalog || 0} фильмов</strong></div>
      <div class="setup-row"><span>Постеры загружены</span><strong class="${state.setup?.posters ? 'ok':'warn'}">${state.setup?.posters ? `✓ ${state.setup.posters}`:'○ Постеры пока не загружены'}</strong></div>
      <div class="setup-row"><span>Можно выбирать фильм</span><strong class="${available?'ok':'warn'}">${available?'✓ Готово':'Нужен каталог'}</strong></div>
    </div>
    <p class="lede">${available?'Всё готово к киновечеру 🍿':'Нет подтверждённых фильмов. Откройте «Каталог и обновления» и загрузите фильмы. Для загрузки нужен интернет; при ошибке можно повторить попытку. Уже сохранённый каталог работает без сети.'}</p>
    <details class="setup-help"><summary>Если что-то не работает</summary><div class="setup-list technical-list">
      <div class="setup-row"><span>Database</span><strong class="ok">✓ Готова</strong></div>
      <div class="setup-row"><span>Ollama</span><strong class="${o.available ? 'ok':'warn'}">${o.available ? '✓ Подключена':'○ Необязательна'}</strong></div>
      <div class="setup-row"><span>AI model</span><strong class="${o.model_installed ? 'ok':'warn'}">${o.model_installed ? `✓ ${esc(o.model)}`:'○ Работаем без неё'}</strong></div>
      <div class="setup-row"><span>Local network</span><strong class="ok">✓ Tonight доступен</strong></div>
    </div>${!o.model_installed ? `<p>Tonight работает и без Ollama. Для умных подсказок на этом компьютере:</p><div class="choice"><code>${esc(state.setup?.model_command || '')}</code></div>` : ''}${!state.setup?.posters ? `<p>Чтобы один раз загрузить настоящие постеры через TMDB:</p><div class="choice"><code>${esc(state.setup?.poster_command)}</code></div>` : ''}</details>
    <div class="footer-actions">${available?'<button class="button large" data-action="finish-setup">Продолжить</button>':'<button class="button" data-view="library">Каталог и обновления</button><button class="button secondary" data-action="retry-setup">Повторить проверку</button>'}</div>
  </section>`, { narrow:true, nav:false });
}

function participantLine(id) {
  const person = state.session?.participants?.[id] || {};
  const live = state.presence[id];
  let text = live ? 'в сети' : person.ready ? 'готов 🍿' : person.joined ? (person.progress ? `выбирает: ${person.progress} / ${state.total}` : 'присоединился') : 'ещё не здесь';
  return `<span><i class="dot ${live ? 'online':''}"></i>${names[id]} — ${text}</span>`;
}

function catalogExpansionCard() {
  if (isRemoteClient() && !state.accessCode) return '';
  const job = state.expansion;
  const busy = job?.phase === 'running';
  const count = state.expansionCount;
  const result = job && ['done','cancelled','error'].includes(job.phase);
  return `<section class="catalog-growth panel" data-expansion-panel aria-labelledby="catalog-growth-title">
    <div><p class="eyebrow">Откройте что-то новое</p><h2 id="catalog-growth-title">Больше фильмов и постеров</h2>
    <p>Пополните общий каталог. Фильмы и постеры сохранятся на компьютере с Tonight и появятся на всех подключённых устройствах.</p></div>
    <div class="catalog-growth-actions"><div class="catalog-growth-count" role="group" aria-label="Сколько новых фильмов добавить">${[20,50,100].map(n=>`<button class="button ${count===n?'':'secondary'}" data-expand-count="${n}" aria-pressed="${count===n}" ${busy?'disabled':''}>${n} фильмов</button>`).join('')}</div>
    <button class="button large" data-expand-start ${busy || !job?.available?'disabled':''}>${busy?'Загружаем фильмы…':`＋ Добавить ${count} фильмов и постеры`}</button>
    ${busy?'<button class="button ghost" data-expand-cancel>Остановить загрузку</button>':''}</div>
    <div class="catalog-growth-status" role="status" aria-live="polite">${busy || result ? `<p>${esc(job.message)}</p><p>Добавлено фильмов: <strong>${job.added}</strong>${busy?` из ${job.target}`:''} · Постеров: <strong>${job.posters}</strong></p>${busy?`<progress value="${job.added}" max="${job.target}" aria-label="Добавление новых фильмов"></progress>`:''}${job.image_errors?`<p class="hint">Не удалось получить постеры: ${job.image_errors}. Повторная загрузка попробует добавить недостающие.</p>`:''}` : `<p class="hint">${job ? (job.available?'Уже добавленные фильмы пропускаем. Ваши оценки и история сохранятся.':'Для загрузки установите актуальную сборку Tonight.'):'Проверяем возможность загрузки…'}</p>`}</div>
    <p class="hint">${isRemoteClient()?'Можно закрыть телефон — компьютер продолжит загрузку.':'Во время загрузки можно продолжать выбирать фильм.'}</p>
  </section>`;
}

function paintExpansion() {
  const panel = root.querySelector('[data-expansion-panel]');
  if (!panel) return;
  const template = document.createElement('template');
  template.innerHTML = catalogExpansionCard();
  panel.replaceWith(template.content);
  bindExpansion();
}

async function refreshExpansion() {
  if (state.expansionPending || (isRemoteClient() && !state.accessCode)) return;
  clearTimeout(state.expansionTimer);
  state.expansionPending = true;
  try {
    const wasRunning = state.expansion?.phase === 'running';
    state.expansion = await api('/api/catalog/expand');
    if (wasRunning && state.expansion.phase !== 'running') {
      state.personalAt = 0; state.personalRevision++;
      if (state.view === 'home' && state.user) refreshPersonal();
    }
    paintExpansion();
  } catch (_) {
    if (!state.expansion) state.expansion = {available:false, phase:'idle'};
    paintExpansion();
  } finally {
    state.expansionPending = false;
    state.expansionTimer = setTimeout(refreshExpansion, state.expansion?.phase === 'running' ? 1500 : 10000);
  }
}

function bindExpansion() {
  root.querySelectorAll('[data-expand-count]').forEach(button=>button.addEventListener('click',()=>{
    state.expansionCount = Number(button.dataset.expandCount); paintExpansion();
  }));
  root.querySelector('[data-expand-start]')?.addEventListener('click', async event=>{
    event.currentTarget.disabled = true;
    try {
      state.expansion = await api('/api/catalog/expand', {method:'POST', headers:{'X-Tonight-Update':'1'}, body:JSON.stringify({count:state.expansionCount})});
      paintExpansion(); refreshExpansion();
    } catch (error) { toast(error.message); refreshExpansion(); }
  });
  root.querySelector('[data-expand-cancel]')?.addEventListener('click', async event=>{
    event.currentTarget.disabled = true;
    try {
      state.expansion = await api('/api/catalog/expand/cancel', {method:'POST', headers:{'X-Tonight-Update':'1'}});
      paintExpansion();
    } catch (error) { toast(error.message); }
  });
}

function homeCinema() {
  const data=state.personalUser===state.user?state.personal:null;
  const films=(data?.items||[]).filter(m=>m.poster_available!==false&&m.poster_url).slice(0,3);
  return `<div class="home-cinema"><p class="cinema-label">В вашем каталоге <span aria-hidden="true">✦</span></p><div class="cinema-posters">${films.length?films.map(m=>`<button class="cinema-poster" data-home-detail="${esc(m.id)}" aria-label="Подробнее: ${esc(m.title)}">${poster(m)}<span>${esc(m.title)}</span></button>`).join(''):'<div class="cinema-placeholder" aria-hidden="true"><span>TONIGHT</span><small>Меньше выбирать. Больше смотреть.</small></div>'}</div></div>`;
}

function homeHero() {
  return `<section class="home-choice" aria-labelledby="home-choice-title"><div class="home-choice-copy"><p class="eyebrow">Ваш вечер начинается здесь</p><h1 id="home-choice-title">Что посмотрим <span>сегодня?</span></h1><p class="lede">Отметьте, какие из просмотренных фильмов вам понравились. Tonight учтёт оценки каждого зрителя при подборе для двоих.</p><div class="footer-actions"><button class="button large" data-choice-mode="taste">По знакомым фильмам <span aria-hidden="true">↗</span></button><button class="button ghost" data-view="choices">Все способы выбора <span aria-hidden="true">→</span></button></div></div>${homeCinema()}</section>`;
}

function legacyInviteNotice() {
  return state.legacyInvite ? '<aside class="choice-resume" role="status"><div><strong>Выбор по старой ссылке больше недоступен</strong><p>Начните подбор по знакомым фильмам. Чтобы подключить телефон, используйте адрес и код с экрана Tonight.</p></div></aside>' : '';
}

function renderHome() {
  if (!state.user) {
    const accessCode = isRemoteClient() ? `<div class="panel" style="margin-bottom:1rem"><label for="access-code"><strong>Код с экрана Tonight</strong></label><input id="access-code" data-access-code inputmode="numeric" autocomplete="one-time-code" maxlength="6" value="${esc(state.accessCode)}" placeholder="6 цифр"><p class="hint">Введите код с экрана компьютера, затем выберите себя.</p></div>` : '';
    const profilePicker = `<section class="hero-home"><div class="hero-lockup"><p class="eyebrow">Продолжим подбор</p><h1>Кто будет выбирать?</h1><p class="lede">Выберите профиль — подбор продолжится автоматически. Ответы каждого зрителя сохраняются отдельно.</p></div>${accessCode}<div class="people-grid"><button class="person-card" data-user="lera" style="--glow:#ff667c"><span class="person-emoji">🍿</span><span class="person-name">Первый зритель</span></button><button class="person-card" data-user="nikita" style="--glow:#ff9a59"><span class="person-emoji">🎬</span><span class="person-name">Второй зритель</span></button></div><button class="button ghost" data-view="home">← На главную</button></section>`;
    return shell(`${legacyInviteNotice()}${state.pendingChoice ? profilePicker : homeHero()}<details class="disclosure"><summary>Подключить телефон</summary>${inviteCard()}</details>`, {nav:false});
  }
  const s = state.session;
  let title = 'Начнём киновечер?';
  let cta = 'Какой сегодня вайб?';
  if (s?.status === 'completed') { title = 'Ещё один фильм?'; cta = 'Начать новый вечер 🍿'; }
  else if (s?.status === 'recommended') { title = 'Кажется, мэтч уже найден'; cta = 'Показать результат'; }
  else if (s?.status === 'watching') { title = 'Приятного просмотра!'; cta = 'Вернуться к просмотру'; }
  else if (s?.status === 'selected') { title = 'Фильм на сегодня выбран'; cta = 'Показать выбор'; }
  else if (s?.participants?.[state.user]?.ready) { title = `Готово, ${names[state.user]}!`; cta = 'Вернуться к ожиданию'; }
  else if (s?.participants?.[state.user]?.energy) { title = 'Продолжим с того же места?'; cta = 'Продолжить выбор'; }
  const active=s && !['choosing','completed'].includes(s.status) || s?.participants?.[state.user]?.energy;
  const job=state.expansion;
  return shell(`${legacyInviteNotice()}${homeHero()}
    <div class="home-tools"><div class="home-resumes">
    ${active ? `<aside class="choice-resume"><div><strong>${esc(title)}</strong><p>Ваш вечер сохранён — можно продолжить.</p></div><button class="button secondary" data-action="continue-session">${esc(cta)}</button></aside>` : ''}
    </div>${temporaryExclusions()}</div>
    ${job && ['running','error'].includes(job.phase)?`<aside class="status-card" role="status"><p>${esc(job.message || 'Загрузка каталога')}</p><button class="button secondary" data-view="library">Открыть каталог</button></aside>`:''}
    ${personalSection()}<details class="disclosure"><summary>Подключить телефон и пригласить зрителя</summary>${inviteCard()}<div class="presence">${participantLine('lera')}${participantLine('nikita')}</div></details>`);

}

function choicesBack() {
  return '<button class="button ghost choices-back" data-view="choices">← Способы выбора</button>';
}

function renderChoices() {
  const card = (mode, icon, title, text, note) => `<button class="choice-method" data-choice-mode="${mode}"><span class="choice-method-icon" aria-hidden="true">${icon}</span><span class="choice-method-copy"><strong>${title}</strong><span>${text}</span><small>${note}</small></span><span class="choice-method-arrow" aria-hidden="true">↗</span></button>`;
  return shell(`<section class="choice-hub"><button class="button ghost choices-back" data-view="home">← На главную</button><div class="screen-head"><p class="eyebrow">Способы выбора</p><h1>Как найдём фильм?</h1><p class="lede">Выберите, что удобнее сейчас.</p></div><div class="choice-methods">
    ${card('taste','✧','По знакомым фильмам','Оцените уже просмотренное вдвоём. Учтём вкус каждого.','Подбор для двоих')}
    ${card('tonight','☾','По настроению','Настройте настроение, время и компанию. Получите короткую подборку.','Подбор на вечер')}
    ${card('smart','⌕','По описанию','Расскажите своими словами, что хочется посмотреть.','Умный поиск')}
    ${card('roulette','⚄','Случайный фильм','Задайте условия и доверьте выбор случаю.','Кинорулетка')}
    ${card('tinder','▱','Листать карточки','Отмечайте интересные фильмы по одному — подбор подстроится.','Кино-Tinder')}
  </div></section>`, {nav:!!state.user});
}

async function openChoiceMode(mode) {
  if(state.setup?.catalog_available===0){state.view='setup';render();return;}
  ++state.navigationRequest;
  smartSearch.cancel();
  if (!state.user) { state.pendingChoice=mode; state.view='home'; render(); return; }
  state.pendingChoice=null;
  if (mode==='tonight') openTonight();
  else if (mode==='smart') smartSearch.open();
  else if (mode==='roulette') openRoulette();
  else if (mode==='tinder') openTinder();
  else if (mode==='taste') await continueSession();
}

function discoveryCard(movie, reason, action = 'select-personal') {
  return `<article class="history-card discovery-card">${poster(movie)}<h3>${esc(movie.title)}</h3><p class="hint">${movie.year || 'Год не указан'} · ${movie.runtime ? `${movie.runtime} мин · ` : ''}${esc(movie.genres.join(' · '))}</p><p class="hint">${esc(reason)}</p><div class="footer-actions">${trailerButton(movie)}<button class="button" data-action="${action}" data-movie-id="${esc(movie.id)}">Выбрать на сегодня</button></div></article>`;
}

function personalSection() {
  const data = state.personalUser === state.user ? state.personal : null;
  return `<section class="home-personal" aria-labelledby="personal-title"><header class="personal-heading"><h2 id="personal-title">Подобрано для тебя</h2><p>${data?.cold_start ? 'Начните с этих фильмов — дальше подбор учтёт ваш вкус.' : 'С учётом ваших оценок и предпочтений.'}</p></header>${state.personalError ? `<p role="status">${esc(state.personalError)}</p><button class="button secondary" data-action="retry-personal">Повторить</button>` : !data ? '<p role="status">Подбираем фильмы…</p>' : data.items.length ? `<div class="history-grid personal-grid">${data.items.map(movie => discoveryCard(movie, movie.recommendation_reason)).join('')}</div>${data.limited ? '<p class="hint">Подходящих фильмов пока немного. Оцените ещё фильмы или проверьте выбранные ограничения.</p>' : ''}` : `<div class="empty">Пока нет подходящих фильмов. Проверьте ограничения или обновите каталог.${exclusionEmptyHelp()}</div>`}</section>`;
}

async function refreshPersonal() {
  const user = state.user, revision = state.personalRevision;
  if (!user || state.personalPending) return;
  state.personalPending = true;
  try {
    const data = await api(`/api/recommendations/personal/${encodeURIComponent(user)}`);
    if (state.user !== user || revision !== state.personalRevision) return;
    state.personal = data; state.personalUser = user; state.personalError = '';
  } catch (_) {
    if (state.user === user) state.personalError = 'Подборка временно недоступна. Попробуйте ещё раз.';
  } finally {
    state.personalPending = false;
    state.personalAt = revision === state.personalRevision && state.user === user ? Date.now() : 0;
    if (state.view === 'home') render();
  }
}

const quickEvenings = [
  { id:'tired', icon:'😴', title:'Устали', text:'Спокойный и понятный фильм без лишней нагрузки', moods:['cozy','laugh'], energy:'low', max_runtime:120 },
  { id:'late', icon:'🌙', title:'Поздно, нужен короткий фильм', text:'До 90 минут, чтобы не закончить глубокой ночью', moods:['cozy','laugh'], energy:'low', max_runtime:90 },
  { id:'light', icon:'☀️', title:'Хотим что-то лёгкое', text:'Больше юмора и уюта, меньше тяжёлых тем', moods:['laugh','cozy'], energy:'medium', max_runtime:120 },
  { id:'attentive', icon:'🧠', title:'Готовы внимательно смотреть', text:'Можно сложнее, напряжённее и до 160 минут', moods:['smart','mystery','wow'], energy:'high', max_runtime:160 },
  { id:'risk', icon:'🎲', title:'Можно рискнуть и удивиться', text:'Без ограничения по времени — пусть Tonight удивит', moods:['surprise'], energy:'medium', max_runtime:null },
];

function renderQuick() {
  return shell(`<section><div class="screen-head"><p class="eyebrow">Быстрый вечер ⚡</p><h2>Что за вечер сегодня?</h2><p class="lede">Выберите готовые условия для двоих. Затем каждый оценит знакомые фильмы, чтобы получить общий подбор.</p></div><div class="choice-stack">${quickEvenings.map(item => `<button class="choice quick-context" data-quick="${item.id}"><span>${item.icon} <strong>${item.title}</strong><small>${item.text}</small></span></button>`).join('')}</div><h3 class="question">Стоп-жанры на сегодня</h3><p class="lede">Отметьте только то, чего точно не хотите. Готовый сценарий сохранит эти запреты.</p><div class="chip-grid">${genres.map(g => `<button class="chip ${state.prefs.disliked_genres.includes(g)?'selected':''}" data-dislike="${g}" aria-pressed="${state.prefs.disliked_genres.includes(g)}">${g}</button>`).join('')}</div><div class="footer-actions"><button class="button ghost" data-view="home">Назад</button></div></section>`, {narrow:true});
}

function renderVibe() {
  return shell(`<section><div class="screen-head"><p class="step">Выбор вдвоём · 1 из 2</p><h2>Какой сегодня вайб?</h2><p class="lede">Укажите своё настроение. Затем оцените знакомые фильмы; второй зритель ответит отдельно.</p></div>
    <div class="chip-grid">${moods.map(([id,emoji,label]) => `<button class="chip ${state.prefs.moods.includes(id)?'selected':''}" data-mood="${id}" aria-pressed="${state.prefs.moods.includes(id)}">${emoji} ${label}</button>`).join('')}</div>
    <h3 class="question">Сколько сегодня сил?</h3><div class="choice-stack">
      ${[['low','😴','Мозг выключен'],['medium','🙂','Что-нибудь нормальное'],['high','🧠','Готов внимательно смотреть']].map(([id,e,label]) => `<button class="choice ${state.prefs.energy===id?'selected':''}" data-energy="${id}"><span>${e} ${label}</span></button>`).join('')}
    </div><div class="footer-actions"><button class="button ghost" data-view="quick">Готовые условия вечера</button><button class="button large" data-action="to-filters" ${!state.prefs.moods.length || !state.prefs.energy?'disabled':''}>Дальше</button></div>
  </section>`, {narrow:true});
}

function renderFilters() {
  const choice = (field, value, emoji, label) => `<button class="choice ${String(state.prefs[field])===String(value)?'selected':''}" data-field="${field}" data-value="${value ?? ''}"><span>${emoji} ${label}</span></button>`;
  return shell(`<section><div class="screen-head"><p class="step">Выбор вдвоём · 2 из 2</p><h2>Чего сегодня точно хочется избежать?</h2><p class="lede">Стоп-жанры важнее любых высоких рейтингов.</p></div>
    <h3 class="question">Длительность</h3><div class="choice-stack">${choice('max_runtime',90,'⏱','До 90 минут')}${choice('max_runtime',120,'🍿','До 2 часов')}${choice('max_runtime',150,'🎬','До 2.5 часов')}${choice('max_runtime',null,'♾','Неважно')}</div>
    <h3 class="question">Эпоха</h3><div class="choice-stack">${choice('min_year',2015,'✨','Относительно новое')}${choice('min_year',2000,'📀','2000+')}${choice('min_year',1980,'📼','80–90-е тоже ок')}${choice('min_year',null,'🎞','Вообще неважно')}</div>
    <h3 class="question">Сегодня точно НЕ хотим</h3><div class="chip-grid">${genres.map(g => `<button class="chip ${state.prefs.disliked_genres.includes(g)?'selected':''}" data-dislike="${g}" aria-pressed="${state.prefs.disliked_genres.includes(g)}">${g}</button>`).join('')}</div>
    <div class="footer-actions"><button class="button ghost" data-view="vibe">Назад</button><button class="button large" data-action="save-prefs">Оценить знакомые фильмы</button></div>
  </section>`, {narrow:true});
}

function renderSwipe() {
  // A realtime progress event may repaint the card while a local request is in
  // flight. The new card is a fresh interaction surface and must never inherit
  // the previous card's click lock.
  reacting = false;
  const movie = state.deck[0];
  const progress = state.total - state.deck.length;
  if (!movie) return renderNoAvailableMovies();
  return shell(`<section class="shared-review"><div class="progress-line"><div class="track"><i style="width:${(progress/state.total)*100}%"></i></div><strong>${progress + 1} / ${state.total}</strong></div>
    <div class="shared-heading"><h1>Смотрели этот фильм?</h1><p id="swipe-guidance">Если смотрели — оцените впечатление. Если нет — выберите «Не смотрел(а)».</p></div>
    <div class="swipe-stage"><article class="swipe-card" id="swipe-card" tabindex="0" aria-label="${esc(movie.title)}" aria-describedby="swipe-guidance">
      <div class="shared-film"><div class="shared-poster">${poster(movie)}</div><div class="shared-film-copy"><h2>${esc(movie.title)}</h2><p class="meta">${movie.year} · ${movie.runtime} мин<br>${esc(movie.genres.join(' · '))}</p><p class="shared-synopsis">${esc(tonightSynopsis(movie))}</p></div></div>
      <div class="reaction-row" aria-label="Впечатление от просмотренного фильма">${reactionMap.map(([id,e,label]) => `<button class="reaction" data-reaction="${id}" title="${label}"><span class="reaction-icon" aria-hidden="true">${e}</span><span>${label}</span></button>`).join('')}</div>
      <p class="action-help">Ответы сохраняются для вашего профиля и помогают подбору для двоих.</p>
      <details class="shared-help"><summary>Зачем оценивать знакомые фильмы?</summary><p>Так Tonight узнаёт ваш вкус. Здесь оценивают прошлый просмотр, а не желание посмотреть фильм. Оба зрителя отвечают отдельно.</p></details>
      ${movie.overview ? descriptionDisclosure(movie.overview, movie.id, 'card-description') : ''}
    </article></div></section>`);
}

function renderWaiting() {
  const other = state.user === 'lera' ? 'nikita' : 'lera';
  const op = state.session?.participants?.[other] || {progress:0,ready:false};
  const title = op.ready ? 'Сводим ваши вкусы…' : `Ждём ${names[other].replace('а','у')}`;
  const bothReady = state.session?.participants?.lera?.ready && state.session?.participants?.nikita?.ready;
  const recovery = bothReady ? `<div class="footer-actions"><button class="button secondary" data-action="retry-recommendations" ${state.recovering?'disabled':''}>${state.recovering ? 'Проверяем…' : 'Проверить результат'}</button><button class="button ghost" data-action="restart-session" ${state.restarting?'disabled':''}>${state.restarting ? 'Начинаем…' : 'Начать новый выбор'}</button></div>${state.waitError ? `<p class="hint">${esc(state.waitError)}</p>` : ''}` : '';
  return shell(`<section class="waiting"><div><div class="projector"><div class="beam"></div></div><p class="eyebrow">Готово! 🍿</p><h2>${title}</h2><p class="lede" style="margin-inline:auto">${op.ready ? 'Ищем не просто среднее, а вариант, от которого обоим будет хорошо.' : `${names[other]} выбирает: ${op.progress || 0} / ${state.total}`}</p>
    <div class="status-cards"><div class="status-card">${emojis[state.user]} ${names[state.user]}<br><strong class="ok">готов 🍿</strong></div><div class="status-card">${emojis[other]} ${names[other]}<br><strong>${op.ready?'готов 🍿':`${op.progress || 0} / ${state.total}`}</strong></div></div>${recovery}</div></section>`);
}

function descriptionDisclosure(description, movieId, className = 'movie-description') {
  return `<details class="${className}" aria-label="Полное описание" data-description-key="${esc(movieId || '')}" ${state.expandedDescriptions.has(String(movieId || '')) ? 'open' : ''}><summary><span class="description-expand">Раскрыть целиком</span><span class="description-collapse">Свернуть описание</span></summary><p class="description-full">${esc(description)}</p></details>`;
}

function renderNoAvailableMovies() {
  return shell(`<section class="empty"><h2>Пока нет фильмов для выбора</h2><p>Сочетание исключений и условий вечера не оставило доступных фильмов. Нужны подтверждённый прокат и русское название; неизвестные обязательные характеристики исключаем.</p><p class="hint">Проверьте обновление каталога на основном компьютере или измените ограничения вечера.</p>${exclusionEmptyHelp()}<div class="footer-actions"><button class="button secondary" data-view="filters">Изменить условия вечера</button><button class="button ghost" data-view="taste">Изменить постоянные исключения</button><button class="button ghost" data-view="home">На главный экран</button></div></section>`);
}

function movieDescription(description, movieId = '') {
  const full = String(description || 'Описание пока не добавлено');
  if (full.length <= 220) return `<p class="lede movie-summary">${esc(full)}</p>`;
  const excerpt = full.slice(0, 200).replace(/\s+\S*$/, '') + '…';
  return `<p class="lede movie-summary">${esc(excerpt)}</p>${descriptionDisclosure(full, movieId)}`;
}

function renderResults() {
  const list = state.session?.recommendations || [];
  if (!list.length) return renderNoAvailableMovies();
  const main = list[0];
  const context = state.session?.recommendation_context || {};
  const reasons = Array.isArray(main.plain_reasons) && main.plain_reasons.length === 2
    ? main.plain_reasons
    : [
        'При выборе учтены сегодняшние реакции обоих зрителей.',
        main.rating ? `Зрители оценили фильм на ${main.rating} из 10.` : 'Фильм подходит под выбранные вами рамки вечера.',
      ];
  const excluded = context.excluded_genres || [];
  const stopGenresRespected = main.stop_genres_respected !== false;
  const relaxedText = context.relaxed_constraints?.length ? `Чтобы выбор не оказался пустым, мы расширили: ${context.relaxed_constraints.join(' и ')}. Стоп-жанры остались исключены.` : '';
  return shell(`<section><div class="result-hero">${main.backdrop_available !== false && main.backdrop_url ? `<img src="${esc(main.backdrop_url)}" alt="" aria-hidden="true">` : ''}<div class="result-layout"><div class="result-poster">${poster(main, {eager:true})}</div><div class="result-content"><span class="match">${main.match}% мэтч</span><p class="eyebrow">Кажется, у нас мэтч 🍿</p><h1>${esc(main.title)}</h1><div class="meta"><span>${main.year}</span><span>•</span><span>${main.runtime} мин</span><span>•</span><span>${main.genres.join(' · ')}</span><span>★ ${main.rating}</span></div>${movieDescription(main.overview, main.id)}<div class="footer-actions" style="justify-content:flex-start">${trailerButton(main)}</div></div></div></div>
    <h2 class="section-title">Почему выбрали этот фильм</h2><ul class="reason-list">${reasons.map(reason => `<li class="reason">✓ ${esc(reason)}</li>`).join('')}</ul>
    <div class="${stopGenresRespected ? 'filter-proof' : 'constraint-warning'}"><strong>${stopGenresRespected ? 'Стоп-жанры учтены ✓' : 'Этот вариант не прошёл проверку стоп-жанров'}</strong><p>${stopGenresRespected ? (excluded.length ? `В фильме нет: ${esc(excluded.join(', '))}.` : 'Сегодня вы не выбирали стоп-жанры.') : 'Начните выбор заново — такой фильм не должен попадать в результат.'}</p></div>
    ${relaxedText ? `<div class="constraint-warning"><strong>Немного расширили поиск</strong><p>${esc(relaxedText)}</p></div>` : ''}
    <details class="method"><summary>Как Tonight выбирает фильм</summary><p>Сначала убирает стоп-жанры, затем учитывает ваши сегодняшние реакции и ищет вариант, который подойдёт вам обоим.</p></details>
    <div class="killer"><div><p class="eyebrow">Вариант на вечер</p><h2>Смотрим вместе?</h2></div><div class="footer-actions"><button class="button large" data-action="accept-main" data-movie-id="${main.id}">✅ Да, смотрим это</button><button class="button secondary" data-action="save-later" data-movie-id="${main.id}">♡ На потом</button><button class="button secondary" data-action="choose">🎲 Выбери за нас</button><button class="button ghost" data-action="restart-session">↻ Выбрать заново</button></div></div>
    <h2 class="section-title">Ещё может зайти</h2><div class="movie-rail">${list.slice(1,6).map(m => `<button class="mini-movie" data-movie="${m.id}">${poster(m)}<strong>${esc(m.title)}</strong><small>${m.match}% · ${m.year}</small><span class="mini-overview">${esc(m.overview || 'Короткое описание появится после обновления каталога')}</span></button>`).join('')}</div>
  </section>`);
}

function renderSelected() {
  const movie = state.session?.selected;
  if (!movie) return renderResults();
  const traits = similarityTraits(movie);
  return shell(`<section class="selected-layout">${poster(movie, {eager:true})}<div><p class="eyebrow">Финальное решение</p><h1>${esc(movie.title)}</h1><div class="meta"><span>${movie.year || 'Год неизвестен'}</span><span>•</span><span>${movie.runtime?`${movie.runtime} мин`:'Длительность неизвестна'}</span><span>•</span><span>${esc(movie.genres.join(' · '))}</span></div><label class="viewing-context">Смотрим<select data-viewing-company aria-label="Кто смотрит">${tonightCompanies.map(([id,label])=>`<option value="${id}" ${state.session.viewing_company===id?'selected':''}>${label}</option>`).join('')}</select></label><p class="hint">${state.session.viewing_company==='solo'?'Смотрите самостоятельно. Просмотр и оценка отмечаются отдельно.':'Компания сохранена. Просмотр и оценка отмечаются отдельно.'}</p><div class="footer-actions" style="justify-content:flex-start"><button class="button large" data-action="start-watching">${state.session.viewing_company==='solo'?'🍿 Начать одиночный вечер':'✅ Будем смотреть'}</button>${trailerButton(movie)}<button class="button secondary large" data-action="decline">✋ Не смотрим</button><button class="button ghost" data-action="choose-another">🎲 Другой вариант</button></div>${movieDescription(movie.overview, movie.id)}
    <details class="avoid-box"><summary>🚫 Не предлагать похожее</summary><p>Это сильнее обычного «не смотрим». Ослабим в будущих рекомендациях:</p><ul><li><strong>Сочетание жанров:</strong> ${esc(traits.genres.join(', ') || 'как у этого фильма')}</li><li><strong>Жанровые ориентиры:</strong> ${esc(traits.moods.join(', ') || 'похожие')}</li>${traits.franchise ? '<li><strong>Франшизу:</strong> следующие части этой серии</li>' : ''}</ul><p class="hint">Целый жанр не будет заблокирован. Действие можно отменить в «Наш вкус».</p><button class="button secondary" data-action="confirm-avoid-similar">Подтвердить и выбрать другой</button></details>
    ${state.selectionReturn?`<button class="button ghost" data-return-choice>← Вернуться к выбору</button>`:''}${state.tonight?.user===state.user && state.tonight?.data && !state.selectionReturn ? '<button class="button ghost" data-tonight-open>← К вариантам подбора</button>' : ''}</div></section>`);
}

function renderWatching() {
  const movie = state.session?.selected;
  if (!movie) return renderHome();
  return shell(`<section class="waiting"><div><p class="eyebrow">${state.session.viewing_company==='solo'?'Одиночный вечер 🍿':'Смотрим 🍿'}</p><h2>${esc(movie.title)}</h2><p class="lede">Приятного просмотра! Оценку сейчас ставить не нужно. Вернитесь сюда после фильма или откройте историю.</p><div class="footer-actions"><button class="button" data-action="finish-and-rate">Просмотр окончен — оценить</button><button class="button secondary" data-action="finish-without-rating">Просмотр окончен, оценю позже</button><button class="button ghost" data-view="history">Открыть историю</button></div></div></section>`);
}

function renderFeedback() {
  const movie = state.feedbackMovie || state.session?.selected;
  return shell(`<section class="waiting"><div><p class="eyebrow">Запомним на будущее</p><h2>${state.feedbackCompany==='solo'?'Ну как тебе фильм?':'Ну как вам?'}</h2><p class="lede" style="margin-inline:auto">${esc(movie?.title || 'Этот фильм')}</p><div class="feedback-row">${feedbackMap.map(([e,label,value]) => `<button class="feedback" data-feedback="${value}">${e} ${label}</button>`).join('')}</div><p class="hint">Оценить можно в любой момент из истории</p><button class="button ghost" data-action="leave-feedback">Оценить позже</button></div></section>`, {narrow:true});
}

function renderEveningFeedback() {
  const movie = state.feedbackMovie || state.session?.selected;
  return shell(`<section class="waiting"><div><p class="eyebrow">Ещё один вопрос</p><h2>Для совместного вечера подошло?</h2><p class="lede" style="margin-inline:auto">${esc(movie?.title || 'Этот фильм')}</p><div class="footer-actions"><button class="button" data-evening-fit="true">Да, было хорошо вместе</button><button class="button secondary" data-evening-fit="false">Не очень</button></div><button class="button ghost" data-action="skip-evening-feedback">Пропустить</button></div></section>`, {narrow:true});
}

function renderHistory() {
  const items = state.history || [];
  const faces = ['','💀','🙁','😐','🙂','😍'];
  const monthNames = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
  const groups = items.reduce((acc, item) => {
    const date = new Date(item.watched_at);
    const key = `${monthNames[date.getMonth()]} ${date.getFullYear()}`;
    (acc[key] ||= []).push(item);
    return acc;
  }, {});
  return shell(`<section><div class="screen-head"><p class="eyebrow">История просмотров 🍿</p><h2>Ваши вечера с кино</h2></div>
    ${state.session?.status === 'watching' ? `<div class="status-card"><p>Сейчас смотрим: <strong>${esc(state.session.selected?.title || 'Выбранный фильм')}</strong></p><button class="button secondary" data-view="watching">Вернуться к просмотру</button></div>` : ''}
    ${items.length ? Object.entries(groups).map(([month, movies]) => `<section><h3 class="section-title">${month}</h3><div class="history-grid">${movies.map(item => `<article class="history-card">${poster(item.movie)}<h3>${esc(item.movie.title)}</h3><div class="ratings">${item.viewing_company==='solo'?`${esc(names[item.solo_user_id])} · один ${faces[item.ratings[item.solo_user_id]] || '—'}`:`${names.lera} ${faces[item.ratings.lera] || '—'} · ${names.nikita} ${faces[item.ratings.nikita] || '—'}`}</div>${item.viewing_company!=='solo' || item.solo_user_id===state.user?`<button class="button secondary" data-action="rate-history" data-history-id="${item.history_id}">${item.ratings[state.user] == null ? 'Оценить просмотр' : 'Изменить свою оценку'}</button>`:''}</article>`).join('')}</div></section>`).join('') : '<div class="empty">Здесь появится ваш первый просмотр 🍿</div>'}
  </section>`);
}

function renderWeekly() {
  const items = state.weeklyPicks || [];
  return shell(`<section><div class="screen-head"><p class="eyebrow">Пять на неделю ✦</p><h2>Можно выбрать без долгих поисков</h2><p class="lede">Короткая локальная подборка для вас двоих. Она обновится на следующей неделе.</p><p class="hint">Tonight ничего не отправляет сам — подборка ждёт здесь, когда понадобится.</p></div>${items.length ? `<div class="history-grid">${items.map(movie => discoveryCard(movie, movie.weekly_reason, 'select-weekly')).join('')}</div>` : `<div class="empty"><h3>Нет подходящих вариантов на неделю</h3><p>Проверьте ограничения или пополните каталог. Правила сохранены.</p>${exclusionEmptyHelp()}</div>`}</section>`);
}

function renderFranchises() {
  const groups = state.franchises || [];
  const card = group => `<section class="profile-actions"><h3>${esc(group.title)}</h3><p class="hint">Просмотрено вместе: ${group.watched_count} из ${group.part_count ?? group.parts.length}</p><div class="choice-stack">${group.parts.map(part => `<div class="taste-item"><span><strong>${part.franchise_order ? `${part.franchise_order}. ` : ''}${esc(part.title)}</strong><small>${part.watched ? 'Просмотрено вместе' : part.available ? 'Ещё не смотрели вместе · Можно выбрать следующим' : 'Ещё не смотрели вместе · Сначала нужна предыдущая часть'}</small></span>${part.available && !part.watched ? `<button class="button ghost small" data-action="select-franchise" data-movie-id="${part.id}">Выбрать на сегодня</button>` : ''}</div>`).join('')}</div>${group.hidden_unverified_count ? `<p class="hint">Скрыто неподтверждённых частей: ${group.hidden_unverified_count}. Записи серии сохранены.</p>` : ''}${group.next_movie ? `<p class="hint">Следующая доступная часть: ${esc(group.next_movie.title)}. Это только подсказка — можно выбрать любой фильм.</p>` : '<p class="hint">Следующую часть пока не предлагаем: нужны подтверждённый прокат, русское название и просмотр предыдущих частей.</p>'}</section>`;
  return shell(`<section><div class="screen-head"><p class="eyebrow">Серии фильмов ≡</p><h2>Смотреть по порядку — если хочется</h2><p class="lede">Здесь показан порядок частей серий. Отметка «Просмотрено вместе» означает подтверждённый просмотр в Tonight; остальные части вы ещё не смотрели вместе.</p><p class="hint">Это не обязательный маршрут: серия не ограничивает обычный выбор.</p></div>${groups.length ? groups.map(card).join('') : '<div class="empty"><h3>Серий пока нет</h3><p>Когда в локальном каталоге появятся части одной истории, порядок будет здесь.</p></div>'}</section>`);
}

function renderDiagnostics() {
  const data = state.diagnostics;
  if (!data) return shell('<section class="waiting"><div><h2>Проверяем приложение…</h2></div></section>');
  const status = data.summary?.ok ? 'ok' : 'warn';
  const metrics = state.usageSummary?.summary;
  const timeToChoice = metrics?.typical_choice_minutes == null ? 'После следующего выбора' : `${metrics.typical_choice_minutes} мин`;
  const usage = metrics ? `<section class="profile-actions usage-summary"><p class="eyebrow">Локальная сводка</p><h2>Как проходят вечера</h2><p class="lede">Только на этом компьютере. Ничего не отправляется разработчику.</p><div class="metric-grid"><div><strong>${metrics.evenings_started}</strong><span>вечеров начато</span></div><div><strong>${metrics.evenings_with_choice} из ${metrics.evenings_started}</strong><span>закончились выбором · ${metrics.choice_rate_percent}%</span></div><div><strong>${metrics.watched_confirmed}</strong><span>просмотров подтверждено</span></div><div><strong>${timeToChoice}</strong><span>типичное время до выбора</span></div><div><strong>${metrics.restarts}</strong><span>раз начинали заново</span></div><div><strong>${metrics.phone_reconnections}</strong><span>раз восстанавливалась связь телефона</span></div><div><strong class="${metrics.stop_genre_violations === 0 ? 'ok' : 'warn'}">${metrics.stop_genre_violations}${metrics.stop_genre_violations === 0 ? ' ✓' : ''}</strong><span>рекомендаций нарушили стоп-жанры</span></div></div>${metrics.timed_evenings === 0 ? '<p class="hint">Точное время выбора начнёт считаться с этой версии — старые вечера не оцениваем приблизительно.</p>' : ''}</section>` : '';
  return shell(`<section><div class="screen-head"><p class="eyebrow">Спокойная проверка ✓</p><h2>Проверить приложение</h2><p class="lede">${esc(data.summary?.text || 'Проверка завершена')}</p></div><div class="panel"><div class="setup-row"><span>${data.summary?.ok ? 'Всё готово к киновечеру' : 'Нужно одно действие'}</span><strong class="${status}">${data.summary?.ok ? '✓ Готово' : '○ Проверьте ниже'}</strong></div>${(data.checks || []).map(check => `<div class="setup-row"><span>${esc(check.title)}</span><strong class="${check.state === 'ready' ? 'ok' : check.state === 'optional' ? 'warn' : 'warn'}">${esc(check.detail)}</strong></div>`).join('')}</div>${usage}<details class="setup-help"><summary>Технический журнал</summary><p class="hint">В нём только статусы проверки — без истории просмотров и настроек.</p><textarea readonly aria-label="Технический журнал" rows="6">${esc(data.technical_log || '')}</textarea><div class="footer-actions"><button class="button ghost" data-action="copy-diagnostics">Скопировать журнал</button></div></details></section>`, {narrow:true});
}

function renderWatchlist() {
  const items = state.watchlist || [];
  const genresInList = [...new Set(items.flatMap(movie => movie.genres || []))].sort((a,b) => a.localeCompare(b, 'ru'));
  const query = state.watchlistQuery.trim().toLocaleLowerCase('ru');
  const visibleItems = items.filter(movie => {
    const searchable = [movie.title, movie.original_title, movie.overview, ...(movie.genres || [])].join(' ').toLocaleLowerCase('ru');
    return (!query || searchable.includes(query)) && (!state.watchlistGenre || movie.genres?.includes(state.watchlistGenre));
  });
  const filters = `<div class="search-form watchlist-filters"><input data-watchlist-search value="${esc(state.watchlistQuery)}" placeholder="Найти в списке" maxlength="100" aria-label="Найти фильм в списке на потом"><select data-watchlist-genre aria-label="Фильтр по жанру"><option value="">Все жанры</option>${genresInList.map(genre => `<option value="${esc(genre)}" ${genre === state.watchlistGenre ? 'selected' : ''}>${esc(genre)}</option>`).join('')}</select></div>`;
  const cards = visibleItems.length ? `<div class="history-grid">${visibleItems.map(movie => `<article class="history-card">${poster(movie)}<h3>${esc(movie.title)}</h3><p class="hint">${esc(movie.overview || 'Описание появится после обновления каталога')}</p>${movie.fits_tonight === true ? '<p class="hint">✓ Подходит под сегодняшний план</p>' : ''}${movie.franchise_warning ? `<p class="hint">⚠ ${esc(movie.franchise_warning)}</p>` : ''}${movie.saved_by ? `<p class="hint">Добавил(а): ${esc(names[movie.saved_by])}</p>` : ''}${movie.deferred_reason ? `<p class="hint">Отложили: ${esc(movie.deferred_reason)}</p>` : ''}<div class="footer-actions">${trailerButton(movie, 'button secondary')}<button class="button" data-action="watch-saved" data-movie-id="${movie.id}">Выбрать на сегодня</button><button class="button ghost" data-action="remove-later" data-movie-id="${movie.id}">Убрать</button></div></article>`).join('')}</div>` : `<div class="empty compact"><h3>Ничего не нашли</h3><p>Попробуйте другое слово или жанр.</p><button class="button ghost" data-action="reset-watchlist-filters">Сбросить фильтры</button></div>`;
  return shell(`<section><div class="screen-head"><p class="eyebrow">Общий список ♡</p><h2>На потом</h2><p class="lede">Варианты, которые понравились, но не подошли именно сегодня.</p>${state.watchlistHiddenCount ? `<p class="hint">Скрыто сохранённых фильмов: ${state.watchlistHiddenCount}. Русское название или состоявшийся прокат пока не подтверждены. Записи в списке сохранены.</p>` : ''}${items.some(movie => movie.fits_tonight !== null) ? '<p class="hint">Сначала — то, что подходит под сегодняшний план. Остальные фильмы остаются в списке.</p>' : ''}</div>${items.length ? `${filters}${cards}` : '<div class="empty"><h3>Пока пусто</h3><p>Сохраняйте подходящие фильмы из результатов, чтобы вернуться к ним в другой вечер.</p></div>'}</section>`);
}

function renderSearch() {
  if (!smartSearch.isTitle()) return shell(`${choicesBack()}${smartSearch.tabs()}${smartSearch.content()}`);
  const items = state.searchResults || [];
  return shell(`${choicesBack()}${smartSearch.tabs()}<section><div class="screen-head"><p class="eyebrow">Поиск по названию</p><h2>Как называется фильм?</h2><p class="lede">Найдите знакомый фильм в локальном каталоге.</p></div><form class="search-form" data-action="search-catalog"><input name="query" aria-label="Название фильма" value="${esc(state.searchQuery)}" placeholder="Название фильма" maxlength="100"><button class="button" type="submit">Найти</button></form>${state.searchQuery ? (items.length ? `<div class="history-grid">${items.map(movie => `<article class="history-card">${poster(movie)}<h3>${esc(movie.title)}</h3><p class="hint">${movie.year} · ${esc(movie.genres.join(' · '))}</p><p class="hint">${esc(movie.overview || 'Описание отсутствует в каталоге.')}</p><div class="footer-actions">${trailerButton(movie, 'button secondary')}<button class="button secondary" data-action="select-search-result" data-movie-id="${movie.id}">Выбрать на сегодня</button></div></article>`).join('')}</div>` : '<div class="empty"><p>В локальном каталоге ничего не нашли. Попробуйте другое название.</p></div>') : ''}</section>`);
}

function renderTaste() {
  const data = state.taste || {profiles:{lera:[],nikita:[],pair:[]}, avoidances:{lera:[],nikita:[]}, enough_data:false, watched:0};
  const column = (title,key) => `<div class="panel"><h3>${title}</h3><div class="taste-list">${data.profiles[key]?.length ? data.profiles[key].map(g => `<div class="taste-item"><span>${g.score>=4.5?'❤️':g.score>=3.5?'👍':'•'} ${esc(g.genre)}</span><small>${g.count}×</small>${key === state.user ? `<button class="button ghost small" data-action="remove-taste-genre" data-genre="${esc(g.genre)}">Удалить этот вывод</button>` : ''}</div>`).join('') : '<p class="lede">Пока мало данных</p>'}</div></div>`;
  const avoidances = data.avoidances?.[state.user] || [];
  const backups = state.backups || [];
  const latestBackup = backups[0] ? `Последняя копия: ${new Date(backups[0].created_at).toLocaleString('ru-RU', {dateStyle:'medium', timeStyle:'short'})}.` : 'Последней копии пока нет.';
  const backupList = backups.length ? `<div class="backup-list">${backups.slice(0,5).map(item => `<article><div><strong>${new Date(item.created_at).toLocaleString('ru-RU', {dateStyle:'medium', timeStyle:'short'})}</strong><p>${Math.max(1, Math.round(item.bytes / 1024))} КБ</p></div><div class="footer-actions"><a class="button ghost small" href="/api/backups/${encodeURIComponent(item.name)}/download">Скачать</a><button class="button ghost small" data-action="restore-backup" data-backup-name="${esc(item.name)}">Восстановить</button></div></article>`).join('')}</div>` : '<div class="empty compact"><p>Копий пока нет.</p></div>';
  return shell(`<section><div class="screen-head"><p class="eyebrow">Профили зрителей</p><h2>Наш вкус</h2><p class="lede">Не сумма двух профилей, а то, что особенно хорошо работает именно вместе.</p></div>
    ${permanentExclusions()}
    ${data.enough_data ? `<div class="taste-columns">${column('🍿 Первый зритель','lera')}${column('🎬 Второй зритель','nikita')}${column('✨ Наш вайб','pair')}</div>` : `<div class="empty"><h3>Посмотрим ещё несколько фильмов</h3><p>После трёх совместных оценок здесь появятся честные закономерности 🍿</p><strong>Уже вместе: ${data.watched}</strong></div>`}
    <details class="disclosure profile-actions"><summary>Tonight IQ · управление обучением</summary><p class="lede">Если выводы Tonight стали неактуальны, начните обучение заново. История просмотров и ваши оценки останутся на месте.</p><button class="button ghost" data-action="reset-taste-profile">Начать заново</button></details>
    ${!isRemoteClient() ? `<details class="disclosure profile-actions"><summary>Резервные копии и перенос данных</summary><p class="lede">Скачайте данные, чтобы перенести их на другой компьютер или сохранить отдельно. Перед восстановлением Tonight автоматически сделает страховочную копию текущих данных.</p><p class="hint">${latestBackup}</p><div class="footer-actions"><button class="button ghost" data-action="create-backup">Создать копию</button><button class="button ghost" data-action="export-data">Скачать данные</button></div><div class="backup-import"><label>Восстановить из файла <input type="file" data-backup-import accept=".db,application/vnd.sqlite3"></label><button class="button secondary" data-action="import-backup" disabled>Восстановить из файла</button></div>${backupList}</details>` : ''}
    ${!isRemoteClient() ? '<details class="disclosure profile-actions privacy-actions"><summary>Личные данные</summary><p class="lede">Можно полностью удалить историю, оценки, реакции, список «На потом», выученный вкус и локальные резервные копии. Каталог, постеры и настройка TMDB останутся.</p><details class="setup-help"><summary>Как Tonight обращается с данными</summary><p>История, реакции и оценки хранятся только на этом компьютере. Tonight не отправляет их разработчику и не использует телеметрию.</p><p>Интернет нужен только для публичного каталога TMDB. Личные предпочтения к этим запросам не добавляются.</p></details><button class="button ghost danger" data-action="open-privacy-delete">Удалить личные данные</button></details>' : ''}
    <section class="avoidances"><h2 class="section-title">Не предлагать похожее</h2><p class="lede">Личные сильные отказы текущего зрителя. Они снижают похожие варианты, но не блокируют жанр целиком.</p>${avoidances.length ? `<div class="avoidance-list">${avoidances.map(rule => `<article><div><strong>${esc(rule.title)}</strong><p>${esc(rule.genres.slice(0,3).join(' · '))}${rule.franchise_key ? ' · включая франшизу' : ''}</p></div><button class="button ghost" data-action="remove-avoidance" data-rule-id="${rule.id}">Отменить</button></article>`).join('')}</div>` : '<div class="empty compact"><p>Сильных отказов пока нет.</p></div>'}</section>
  </section>`);
}

function renderError() {
  return shell(`<section class="waiting"><div><p class="eyebrow">Техническая пауза</p><h2>Tonight не смог загрузиться</h2><p class="lede">${esc(state.error || 'Проверьте, что сервер всё ещё запущен.')}</p><button class="button" data-action="retry">Попробовать снова</button></div></section>`, {nav:false});
}

function catalogPanel() {
  if (isRemoteClient()) return '';
  const summary = state.catalog?.summary;
  const update = state.catalog?.update || {};
  const busy = ['checking','downloading','installing'].includes(update.phase);
  const appBusy = ['downloading','ready','installing'].includes(state.update?.phase);
  const recovery = update.phase === 'recovery_error';
  const date = summary?.last_successful_update ? new Date(summary.last_successful_update) : null;
  const updated = date && !Number.isNaN(date.getTime()) ? date.toLocaleString('ru-RU', {dateStyle:'medium',timeStyle:'short'}) : 'Обновлений пакетом ещё не было';
  const rows = summary ? `<div class="setup-list">${[
    ['Фильмов в каталоге',summary.movie_count],['С локальным постером',summary.local_poster_count],
    ['Со ссылкой на трейлер',summary.trailer_link_count],['С постером и ссылкой на трейлер',summary.poster_and_trailer_count],
    ['Версия каталога',summary.catalog_version || 'Пакет ещё не установлен'],['Последнее обновление пакетом',updated],
  ].map(([label,value]) => `<div class="setup-row"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('')}</div>` : '<p class="hint">Сводка каталога пока недоступна.</p>';
  const percent = update.total_bytes ? Math.min(100,Math.round((update.download_bytes || 0)/update.total_bytes*1000)/10) : 0;
  return `<section class="panel"><h2>Ваш локальный каталог</h2>${rows}<p class="hint">Доступность видео не проверена: ссылка на YouTube может перестать работать. Считаем постеры, сохранённые для карточек, без запасных обложек.</p></section>
    <section class="panel"><h2>Обновление каталога</h2>${update.available_version ? `<p class="hint">${update.delivery_kind==='delta'?'Только изменения: новые карточки и изображения.':'Полный пакет: подходящего набора изменений для установленной версии нет.'}</p>` : ''}<p>Новые фильмы и недостающие постеры — без TMDB-токена. История, оценки, личные правки и настройки сохранятся. Tonight не перезапустится.</p>
    <p role="status">${esc(state.catalogError || update.message || 'Проверьте, появился ли новый пакет каталога')}${update.phase === 'downloading' ? ` · ${((update.download_bytes || 0)/1000000).toFixed(1)} из ${((update.total_bytes || 0)/1000000).toFixed(1)} МБ · ${percent}%` : ''}</p>
    ${update.phase === 'downloading' ? `<progress aria-label="Загрузка каталога" max="100" value="${percent}"></progress>` : ''}
    ${update.available_version ? `<p class="hint">Каталог ${esc(update.available_version)} · ${Math.ceil((update.total_bytes || 0)/1000000)} МБ. Совместимость проверим до установки.</p>` : ''}
    <div class="footer-actions"><button class="button secondary" data-catalog-action="check" ${busy || recovery || appBusy ? 'disabled' : ''}>Проверить обновление каталога</button>
    ${update.available_version && !recovery ? `<button class="button" data-catalog-action="install" ${busy || appBusy ? 'disabled' : ''}>${update.can_resume ? 'Продолжить загрузку' : 'Обновить каталог'}</button>` : ''}
    ${update.delivery_kind==='delta' && !recovery ? `<button class="button ghost" data-catalog-action="install-full" ${busy || appBusy ? 'disabled' : ''}>Скачать полный пакет</button>` : ''}
    ${recovery ? `<button class="button" data-catalog-action="recover" ${appBusy ? 'disabled' : ''}>Повторить восстановление</button>` : ''}</div></section>`;
}

function renderCatalog() {
  return shell(`<section><div class="screen-head"><h2>Каталог и обновления</h2><p class="lede">Каталог обновляется отдельно от Tonight. Интернет не нужен, чтобы выбирать уже сохранённые фильмы.</p></div>${catalogExpansionCard()}<div data-catalog-panel>${catalogPanel()}</div><div class="footer-actions"><button class="button secondary" data-view="diagnostics">Проверить приложение</button></div></section>`, {narrow:true});
}

function bindCatalogButtons() {
  root.querySelectorAll('[data-catalog-action]').forEach(button => button.addEventListener('click', () => catalogAction(button.dataset.catalogAction)));
}

function catalogNotice() {
  const panel = root.querySelector('[data-catalog-panel]');
  if (panel) { panel.innerHTML = catalogPanel(); bindCatalogButtons(); }
}

async function refreshCatalogStatus() {
  clearTimeout(state.catalogTimer);
  if (isRemoteClient()) return;
  const request = ++state.catalogRequest;
  try {
    const result = await api('/api/catalog');
    if (request !== state.catalogRequest) return;
    state.catalog = result; state.catalogError = '';
    if (result.update.phase === 'done' && state.setup) {
      state.setup.catalog = result.summary.movie_count; state.setup.posters = result.summary.local_poster_count;
    }
  } catch (_) {
    if (request !== state.catalogRequest) return;
    state.catalogError = 'Не удалось прочитать состояние. Проверьте, что Tonight запущен; можно продолжать вечер.';
  }
  catalogNotice();
  const busy = ['checking','downloading','installing'].includes(state.catalog?.update?.phase);
  if (state.view === 'catalog' || busy) state.catalogTimer = setTimeout(refreshCatalogStatus,busy ? 1500 : 30000);
}

async function catalogAction(action) {
  const endpoint = action==='install-full' ? 'install?full=true' : action;
  if (isRemoteClient() || !['check','install','install-full','recover'].includes(action)) return;
  clearTimeout(state.catalogTimer); ++state.catalogRequest;
  state.catalogError = '';
  state.catalog ||= {summary:null,update:{}};
  state.catalog.update = {...state.catalog.update,phase:action.startsWith('install') ? 'downloading' : 'checking',message:action.startsWith('install') ? 'Скачиваем и проверяем каталог…' : 'Проверяем каталог…'};
  catalogNotice();
  try { state.catalog.update = await api(`/api/catalog/updates/${endpoint}`,{method:'POST',headers:{'X-Tonight-Update':'1'}}); }
  catch (error) { state.catalogError = error.message; state.catalog.update.phase = 'error'; }
  catalogNotice();
  if (!state.catalogError) await refreshCatalogStatus();
}

function refreshWatchlistResults() {
  const current = root.querySelector('.watchlist-filters')?.nextElementSibling;
  if (!current) return;
  const template = document.createElement('template');
  template.innerHTML = renderWatchlist();
  const replacement = template.content.querySelector('.watchlist-filters').nextElementSibling;
  current.replaceWith(replacement);
  replacement.querySelectorAll('[data-action="watch-saved"]').forEach(el => el.addEventListener('click', () => watchSavedMovie(el.dataset.movieId)));
  replacement.querySelectorAll('[data-action="remove-later"]').forEach(el => el.addEventListener('click', () => removeFromWatchlist(el.dataset.movieId)));
  replacement.querySelector('[data-action="reset-watchlist-filters"]')?.addEventListener('click', () => { state.watchlistQuery=''; state.watchlistGenre=''; render(); });
}

function bindCommon() {
  bindPosters();
  smartSearch.bind();
  root.querySelectorAll('[data-home-detail]').forEach(el=>el.addEventListener('click',()=>{state.modal=state.personal?.items.find(m=>m.id===el.dataset.homeDetail);if(state.modal)renderModal();}));
  root.querySelector('[data-viewing-company]')?.addEventListener('change',e=>selectCatalogMovie(state.session.selected.id,e.target.value));
  root.querySelector('[data-return-choice]')?.addEventListener('click',()=>{state.view=state.selectionReturn;render();});
  root.querySelectorAll('[data-choice-mode]').forEach(el=>el.addEventListener('click',()=>openChoiceMode(el.dataset.choiceMode)));
  root.querySelectorAll('details').forEach(el=>el.addEventListener('keydown',e=>{if(e.key==='Escape' && el.open){e.stopPropagation();el.open=false;el.querySelector('summary')?.focus();}}));
  root.querySelectorAll('[data-view]').forEach(el=>{if(el.dataset.view===state.view || el.dataset.view==='library' && state.view==='catalog')el.setAttribute('aria-current','page');});
  bindExpansion();
  if (!state.expansion && !state.expansionPending && (!isRemoteClient() || state.accessCode)) refreshExpansion();
  bindTonight();
  bindRoulette();
  bindTinder();
  root.querySelectorAll('[data-action="select-personal"]').forEach(el => el.addEventListener('click', () => selectSearchResult(el.dataset.movieId)));
  root.querySelector('[data-action="retry-personal"]')?.addEventListener('click', refreshPersonal);
  bindUpdateButtons();
  bindCatalogButtons();
  const navToggle = root.querySelector('[data-action="toggle-nav"]');
  const navigation = root.querySelector('#main-navigation');
  const setNavigation = open => {
    state.navOpen = open;
    navigation?.classList.toggle('is-open', open);
    navToggle?.setAttribute('aria-expanded', String(open));
    if (navToggle) navToggle.textContent = `Разделы ${open ? '−' : '+'}`;
  };
  navToggle?.addEventListener('click', () => setNavigation(!state.navOpen));
  navigation?.addEventListener('keydown', event => {
    if (event.key === 'Escape') { setNavigation(false); navToggle?.focus(); }
  });
  root.querySelectorAll('[data-view]').forEach(el => el.addEventListener('click', () => go(el.dataset.view)));
  root.querySelectorAll('[data-user]').forEach(el => el.addEventListener('click', () => selectUser(el.dataset.user)));
  root.querySelector('[data-access-code]')?.addEventListener('input', event => { state.accessCode=event.target.value.replace(/\D/g, '').slice(0,6); event.target.value=state.accessCode; });
  root.querySelector('[data-action="finish-setup"]')?.addEventListener('click', () => { localStorage.setItem('tonight:setup','1'); state.view='home'; render(); });
  root.querySelector('[data-action="retry-setup"]')?.addEventListener('click', async () => {try{state.setup=await api('/api/setup/status');render();}catch(e){toast(e.message);}});
  root.querySelector('[data-action="copy-invite"]')?.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(state.invite.url); toast('Адрес скопирован ✓'); }
    catch (_) { toast(`Адрес: ${state.invite.display_url}`); }
  });
  root.querySelector('[data-action="switch-user"]')?.addEventListener('click', switchUser);
  root.querySelector('[data-action="continue-session"]')?.addEventListener('click', continueSession);
  root.querySelectorAll('[data-quick]').forEach(el => el.addEventListener('click', () => startQuickEvening(el.dataset.quick)));
  root.querySelectorAll('[data-mood]').forEach(el => el.addEventListener('click', () => toggle(state.prefs.moods, el.dataset.mood)));
  root.querySelectorAll('[data-energy]').forEach(el => el.addEventListener('click', () => { state.prefs.energy=el.dataset.energy; render(); }));
  root.querySelector('[data-action="to-filters"]')?.addEventListener('click', () => { state.view='filters'; render(); });
  root.querySelectorAll('[data-field]').forEach(el => el.addEventListener('click', () => { state.prefs[el.dataset.field] = el.dataset.value === '' ? null : Number(el.dataset.value); render(); }));
  root.querySelectorAll('[data-dislike]').forEach(el => el.addEventListener('click', () => toggle(state.prefs.disliked_genres, el.dataset.dislike)));
  root.querySelector('[data-action="save-prefs"]')?.addEventListener('click', savePrefs);
  root.querySelector('[data-action="retry-recommendations"]')?.addEventListener('click', recoverRecommendations);
  root.querySelector('[data-action="restart-session"]')?.addEventListener('click', restartSession);
  root.querySelectorAll('[data-description-key]').forEach(el => el.addEventListener('toggle', () => {
    if (el.open) state.expandedDescriptions.add(el.dataset.descriptionKey);
    else state.expandedDescriptions.delete(el.dataset.descriptionKey);
  }));
  root.querySelectorAll('[data-reaction]').forEach(el => el.addEventListener('click', () => react(el.dataset.reaction)));
  root.querySelectorAll('[data-movie]').forEach(el => el.addEventListener('click', () => { state.modal = state.session.recommendations.find(m => m.id===el.dataset.movie); renderModal(); }));
  root.querySelector('[data-action="choose"]')?.addEventListener('click', choose);
  root.querySelector('[data-action="accept-main"]')?.addEventListener('click', () => acceptMainRecommendation(root.querySelector('[data-action="accept-main"]')?.dataset.movieId));
  root.querySelectorAll('[data-action="save-later"]').forEach(el => el.addEventListener('click', () => openDeferDialog(el.dataset.movieId)));
  root.querySelectorAll('[data-action="remove-later"]').forEach(el => el.addEventListener('click', () => removeFromWatchlist(el.dataset.movieId)));
  root.querySelectorAll('[data-action="watch-saved"]').forEach(el => el.addEventListener('click', () => watchSavedMovie(el.dataset.movieId)));
  root.querySelectorAll('[data-action="select-weekly"]').forEach(el => el.addEventListener('click', () => selectSearchResult(el.dataset.movieId)));
  root.querySelectorAll('[data-action="select-franchise"]').forEach(el => el.addEventListener('click', () => selectSearchResult(el.dataset.movieId)));
  root.querySelector('[data-action="copy-diagnostics"]')?.addEventListener('click', copyDiagnostics);
  root.querySelector('[data-watchlist-search]')?.addEventListener('input', event => { state.watchlistQuery=event.target.value; refreshWatchlistResults(); });
  root.querySelector('[data-watchlist-genre]')?.addEventListener('change', event => { state.watchlistGenre=event.target.value; refreshWatchlistResults(); });
  root.querySelector('[data-action="reset-watchlist-filters"]')?.addEventListener('click', () => { state.watchlistQuery=''; state.watchlistGenre=''; render(); });
  root.querySelector('[data-action="choose-another"]')?.addEventListener('click', chooseAnother);
  root.querySelector('[data-action="start-watching"]')?.addEventListener('click', startWatching);
  root.querySelector('[data-action="finish-and-rate"]')?.addEventListener('click', () => watched(true));
  root.querySelector('[data-action="finish-without-rating"]')?.addEventListener('click', () => watched(false));
  root.querySelectorAll('[data-action="rate-history"]').forEach(el => el.addEventListener('click', () => openHistoryRating(Number(el.dataset.historyId))));
  root.querySelector('[data-action="leave-feedback"]')?.addEventListener('click', () => go('history'));
  root.querySelector('[data-action="decline"]')?.addEventListener('click', declineMovie);
  root.querySelector('[data-action="confirm-avoid-similar"]')?.addEventListener('click', avoidSimilarMovie);
  root.querySelectorAll('[data-action="remove-avoidance"]').forEach(el => el.addEventListener('click', () => removeAvoidance(Number(el.dataset.ruleId))));
  root.querySelectorAll('[data-action="remove-taste-genre"]').forEach(el => el.addEventListener('click', () => removeTasteGenre(el.dataset.genre)));
  root.querySelector('[data-action="reset-taste-profile"]')?.addEventListener('click', resetTasteProfile);
  root.querySelector('[data-action="create-backup"]')?.addEventListener('click', createBackup);
  root.querySelector('[data-action="export-data"]')?.addEventListener('click', exportData);
  root.querySelector('[data-action="open-privacy-delete"]')?.addEventListener('click', () => { state.privacyDeleteOpen=true; renderPrivacyDeleteDialog(); });
  root.querySelector('[data-backup-import]')?.addEventListener('change', chooseBackupImport);
  root.querySelector('[data-action="import-backup"]')?.addEventListener('click', importBackup);
  root.querySelectorAll('[data-action="restore-backup"]').forEach(el => el.addEventListener('click', () => restoreBackup(el.dataset.backupName)));
  root.querySelectorAll('[data-feedback]').forEach(el => el.addEventListener('click', () => saveFeedback(Number(el.dataset.feedback))));
  root.querySelectorAll('[data-evening-fit]').forEach(el => el.addEventListener('click', () => saveEveningFeedback(el.dataset.eveningFit === 'true')));
  root.querySelector('[data-action="skip-evening-feedback"]')?.addEventListener('click', () => go('history'));
  const searchInput = root.querySelector('[data-action="search-catalog"] input[name="query"]');
  if (searchInput) {
    searchInput.setAttribute('aria-label', 'Название фильма');
    searchInput.value = state.searchDraft ?? state.searchQuery;
    searchInput.addEventListener('input', event => { state.searchDraft = event.target.value; });
  }
  root.querySelector('[data-action="search-catalog"]')?.addEventListener('submit', event => { event.preventDefault(); searchCatalog(new FormData(event.currentTarget).get('query')); });
  root.querySelectorAll('[data-action="select-search-result"]').forEach(el => el.addEventListener('click', () => selectSearchResult(el.dataset.movieId)));
  root.querySelector('[data-action="retry"]')?.addEventListener('click', init);
}

function toggle(array, value) {
  const index = array.indexOf(value); index >= 0 ? array.splice(index,1) : array.push(value); render();
}

function joinBody(user) {
  return JSON.stringify({user_id:user, access_code:isRemoteClient() ? state.accessCode || null : null});
}

async function go(view) {
  smartSearch.cancel();
  const request = ++state.navigationRequest;
  const previousView = state.view;
  state.modal = null;
  if (view === 'choices') { state.pendingChoice=null; state.view=view; render(); return; }
  if (view === 'home') { state.pendingChoice=null; state.personalAt=0; state.view='home'; render(); return; }
  if (view === 'vibe') { state.view='vibe'; render(); return; }
  if (view === 'quick') { state.view='quick'; render(); return; }
  if (view === 'watching' && state.session?.status === 'watching') { state.view='watching'; render(); return; }
  try {
    if (view === 'library' || (view === 'catalog' && !isRemoteClient())) { state.view='catalog'; render(); await refreshCatalogStatus(); return; }
    let changes;
    if (view === 'history') changes = {history:(await api('/api/history')).items};
    if (view === 'weekly') changes = {weeklyPicks:(await api('/api/weekly-picks')).items};
    if (view === 'franchises') changes = {franchises:(await api('/api/franchises')).items};
    if (view === 'diagnostics') { const usageRequest = isRemoteClient() ? null : api('/api/usage-summary').catch(() => null); const [diagnostics, usage] = await Promise.all([api('/api/diagnostics'), usageRequest]); changes={diagnostics,usageSummary:usage}; }
    if (view === 'taste') { const backupRequest = isRemoteClient() ? null : api('/api/backups'); const [taste, backups] = await Promise.all([api('/api/taste'), backupRequest]); changes={taste,backups:backups?.items || []}; }
    if (view === 'search') changes = {};
    if (view === 'watchlist') { const saved=await api('/api/watchlist'); changes={watchlist:saved.items,watchlistHiddenCount:saved.hidden_unverified_count || 0}; }
    if (changes && request === state.navigationRequest && previousView === state.view) { Object.assign(state, changes); state.view=view; render(); }
  } catch (e) { if (request === state.navigationRequest && previousView === state.view) toast(e.message); }
}

async function startQuickEvening(id) {
  const preset = quickEvenings.find(item => item.id === id);
  if (!preset) return;
  state.prefs = { moods:[...preset.moods], energy:preset.energy, max_runtime:preset.max_runtime, min_year:2000, disliked_genres:[...state.prefs.disliked_genres] };
  await savePrefs();
}

async function selectUser(user) {
  try {
    state.exclusionDraft={};state.exclusionError='';
    state.user = user; localStorage.setItem('tonight:user', user);
    await api(`/api/sessions/${state.session.id}/join`, {method:'POST', body:joinBody(user)});
    if (isRemoteClient()) sessionStorage.setItem('tonight:access-code', state.accessCode);
    state.session = await api(`/api/sessions/${state.session.id}`);
    connectWs();
    const pending=state.pendingChoice;
    state.view='home';
    if(pending)await openChoiceMode(pending);else render();
  } catch (e) { state.user=null; localStorage.removeItem('tonight:user'); toast(e.message); render(); }
}

function switchUser() {
  smartSearch.cancel();
  clearTimeout(state.reconnectTimer); state.reconnectTimer=null;
  state.ws?.close(); state.ws=null; state.user=null; state.accessCode=''; state.prefs=defaultPrefs(); state.deck=[]; localStorage.removeItem('tonight:user'); sessionStorage.removeItem('tonight:access-code'); state.view='home'; render();
}

async function continueSession() {
  if(state.setup?.catalog_available===0){state.view='setup';render();return;}
  try {
    if (state.session.status === 'completed') {
      state.session = await api(`/api/sessions/${state.session.id}/restart`, {method:'POST'});
      await api(`/api/sessions/${state.session.id}/join`, {method:'POST', body:joinBody(state.user)}); connectWs();
      state.prefs=defaultPrefs(); state.deck=[];
    }
    if (state.session.status === 'watching') state.view='watching';
    else if (state.session.status === 'selected') state.view='selected';
    else if (state.session.status === 'recommended') state.view='results';
    else if (state.session.participants[state.user]?.ready) state.view='waiting';
    else if (state.session.participants[state.user]?.energy) await loadDeck();
    else state.view='vibe';
    render();
  } catch (e) { toast(e.message); }
}

async function recoverRecommendations() {
  if (state.recovering || !state.session) return;
  state.recovering = true; state.waitError = ''; render();
  try {
    state.session = await api(`/api/sessions/${state.session.id}/recommend`, {method:'POST'});
    if (state.session.status === 'recommended') state.view = 'results';
  } catch (e) {
    state.waitError = e.message;
  } finally {
    state.recovering = false; render();
  }
}

function defaultPrefs() {
  return { moods: [], energy: null, max_runtime: 120, min_year: 2000, disliked_genres: [] };
}

async function restartSession() {
  if (state.restarting || !state.session || !state.user) return;
  state.restarting = true; render();
  try {
    state.session = await api(`/api/sessions/${state.session.id}/restart`, {method:'POST'});
    await api(`/api/sessions/${state.session.id}/join`, {method:'POST', body:joinBody(state.user)});
    state.session = await api(`/api/sessions/${state.session.id}`);
    state.prefs = defaultPrefs(); state.deck = []; state.total = 20;
    connectWs(); state.view = 'vibe';
  } catch (e) {
    state.waitError = e.message;
  } finally {
    state.restarting = false; render();
  }
}

async function followRestartedSession() {
  if (!state.user || state.restarting) return;
  state.restarting = true;
  try {
    state.session = await api('/api/sessions/active');
    await api(`/api/sessions/${state.session.id}/join`, {method:'POST', body:joinBody(state.user)});
    state.session = await api(`/api/sessions/${state.session.id}`);
    state.prefs = defaultPrefs(); state.deck = []; state.total = 20;
    connectWs(); state.view = 'vibe';
    toast('Начинаем новый выбор 🍿');
  } catch (e) {
    state.error = e.message; state.view = 'error';
  } finally {
    state.restarting = false; render();
  }
}

function scheduleWaitingCheck() {
  // Recovery is an explicit user action. Automatic retries used to spin forever
  // when the catalog genuinely had no eligible candidates.
}

async function savePrefs() {
  try {
    await api(`/api/sessions/${state.session.id}/preferences`, {method:'POST', body:JSON.stringify({user_id:state.user,...state.prefs})});
    await loadDeck(); render();
  } catch (e) { toast(e.message); }
}

async function loadDeck() {
  try {
    const data = await api(`/api/sessions/${state.session.id}/swipe/${state.user}`); state.deck=data.movies; state.total=data.total;
    if(!data.total){state.view='filters';toast('Нет доступных карточек. Проверьте ограничения или пополните каталог.');}
    else state.view=state.deck.length?'swipe':'waiting';
  } catch (e) { toast(e.message); state.view='home'; }
}

let reacting = false;
async function react(reaction) {
  if (reacting || !state.deck[0]) return; reacting=true;
  const card = document.querySelector('#swipe-card');
  if (card) { card.style.transform = reaction==='dislike'?'translateX(-120%) rotate(-12deg)':'translateX(120%) rotate(12deg)'; card.style.opacity='0'; }
  try {
    const progress = await api(`/api/sessions/${state.session.id}/swipe`, {method:'POST', body:JSON.stringify({user_id:state.user,movie_id:state.deck[0].id,reaction})});
    state.deck = progress.movies; state.total = progress.total; state.session=await api(`/api/sessions/${state.session.id}`);
    state.waitError = progress.recommendation_error || '';
    if (!state.deck.length) state.view=state.session.status==='recommended'?'results':'waiting';
    setTimeout(render, 130);
  } catch (e) { toast(e.message); render(); }
  finally { reacting=false; }
}

function bindSwipeGestures() {
  const card = document.querySelector('#swipe-card'); if (!card) return;
  card.focus({preventScroll:true});
  let startX=0, dx=0, active=false;
  card.addEventListener('pointerdown', e => {
    if (e.target.closest('button, details')) return;
    active=true; startX=e.clientX; card.setPointerCapture(e.pointerId);
  });
  card.addEventListener('pointermove', e => { if(!active)return; dx=e.clientX-startX; card.style.transform=`translateX(${dx}px) rotate(${dx/25}deg)`; });
  card.addEventListener('pointerup', () => { if(!active)return; active=false; if(Math.abs(dx)>90) react(dx>0?'like':'dislike'); else card.style.transform=''; dx=0; });
  card.addEventListener('pointercancel', () => { active=false; dx=0; card.style.transform=''; });
  card.addEventListener('keydown', e => {
    if (e.target.closest('button, details')) return;
    const map={ArrowLeft:'dislike',ArrowRight:'like',ArrowUp:'love',ArrowDown:'okay','?':'unseen'};
    if(map[e.key]){e.preventDefault();react(map[e.key]);}
  });
}

async function choose() {
  const button=document.querySelector('[data-action="choose"]'); if(button)button.disabled=true;
  document.querySelector('.result-hero')?.classList.add('roulette');
  try { const movie=await api(`/api/sessions/${state.session.id}/choose`,{method:'POST'}); await new Promise(r=>setTimeout(r,1400)); state.session.selected=movie; state.session.viewing_company='couple';state.session.solo_user_id=null;state.session.status='selected'; state.view='selected'; render(); }
  catch(e){toast(e.message); if(button)button.disabled=false;}
}

async function acceptMainRecommendation(movieId) {
  if (!movieId) return;
  try {
    const movie = await api(`/api/sessions/${state.session.id}/select/${encodeURIComponent(movieId)}`, {method:'POST'});
    state.session.selected = movie; state.session.viewing_company='couple';state.session.solo_user_id=null;state.session.status = 'selected'; state.view = 'selected'; render();
  } catch (e) { toast(e.message); }
}

async function chooseAnother() {
  if(state.session?.viewing_company==='solo' && state.tonight?.user===state.user){openTonight();await fetchTonight(true);return;}
  try { const movie=await api(`/api/sessions/${state.session.id}/choose-another`,{method:'POST'}); state.session.selected=movie; render(); toast('Другой вариант — без повторов'); }
  catch(e){toast('Хорошие варианты закончились — начните новый вечер');}
}

async function startWatching() {
  try { state.session=await api(`/api/sessions/${state.session.id}/start-watching`,{method:'POST'}); state.view=state.session.status==='watching'?'watching':'home'; render(); }
  catch(e) { toast(e.message); }
}

async function watched(rate = true) {
  try {
    const result=await api(`/api/sessions/${state.session.id}/watched`,{method:'POST'});
    state.session.status='completed'; state.historyId=result.history_id; state.feedbackMovie=result.movie; state.feedbackCompany=state.session.viewing_company;
    if (rate) { state.view='feedback'; render(); } else await go('history');
  } catch(e) { toast(e.message); }
}

async function openHistoryRating(historyId) {
  if (!state.user) return;
  const fromView = state.view;
  try {
    const history=await api('/api/history');
    if (state.view !== fromView) return;
    const item=history.items.find(entry=>entry.history_id===historyId);
    if (!item) { toast('Просмотр не найден'); return; }
    state.historyId=historyId; state.feedbackMovie=item.movie; state.feedbackCompany=item.viewing_company; state.view='feedback'; render();
  } catch(e) { toast(e.message); }
}

async function declineMovie() {
  if(state.session?.viewing_company==='solo' && state.tonight?.user===state.user){
    try{state.session=await api(`/api/sessions/${state.session.id}/decline`,{method:'POST'});openTonight();await fetchTonight(true);}catch(e){toast(e.message);}return;
  }
  try { state.session=await api(`/api/sessions/${state.session.id}/decline`,{method:'POST'}); state.view='results'; toast('Не сохраняем — выбираем другой вариант'); render(); }
  catch(e) { toast(e.message); }
}

async function avoidSimilarMovie() {
  const movie = state.session?.selected;
  if (!movie) return;
  const button = document.querySelector('[data-action="confirm-avoid-similar"]');
  if (button) button.disabled = true;
  try {
    const result = await api(`/api/sessions/${state.session.id}/avoid-similar`, {method:'POST', body:JSON.stringify({user_id:state.user,movie_id:movie.id})});
    state.session = result.session; state.view = 'results'; render(); toast('Похожие варианты будут встречаться реже');
  } catch (e) { if (button) button.disabled = false; toast(e.message); }
}

async function removeAvoidance(ruleId) {
  try {
    await api(`/api/taste/avoidances/${ruleId}/${state.user}`, {method:'DELETE'});
    state.taste.avoidances[state.user] = (state.taste.avoidances[state.user] || []).filter(rule => rule.id !== ruleId);
    render(); toast('Сильный отказ отменён');
  } catch (e) { toast(e.message); }
}

async function removeTasteGenre(genre) {
  try {
    await api(`/api/taste/genres/${encodeURIComponent(genre)}/${state.user}`, {method:'DELETE'});
    state.taste = await api('/api/taste'); render(); toast('Этот вывод больше не учитывается');
  } catch (e) { toast(e.message); }
}

async function resetTasteProfile() {
  if (!window.confirm('Начать обучение вкуса заново? История просмотров и оценки останутся.')) return;
  try {
    await api(`/api/taste/reset/${state.user}`, {method:'POST'});
    state.taste = await api('/api/taste'); render(); toast('Профиль вкуса начнёт учиться заново');
  } catch (e) { toast(e.message); }
}

async function createBackup() {
  try {
    await api('/api/backup', {method:'POST'});
    state.backups = (await api('/api/backups')).items; render(); toast('Копия сохранена');
  } catch (e) { toast(e.message); }
}

async function exportData() {
  try {
    const result = await api('/api/backup', {method:'POST'});
    state.backups = (await api('/api/backups')).items;
    render();
    const link = document.createElement('a');
    link.href = `/api/backups/${encodeURIComponent(result.name)}/download`;
    link.click();
    toast('Копия скачивается');
  } catch (e) { toast(e.message); }
}

function chooseBackupImport(event) {
  state.backupImportFile = event.currentTarget.files?.[0] || null;
  const button = root.querySelector('[data-action="import-backup"]');
  if (button) button.disabled = !state.backupImportFile;
}

async function importBackup() {
  const file = state.backupImportFile;
  if (!file) { toast('Сначала выберите файл копии'); return; }
  if (!window.confirm('Восстановить данные из этого файла? Текущие данные будут заменены, но Tonight сначала создаст страховочную копию.')) return;
  try {
    const response = await fetch('/api/backups/import?confirmed=true', {method:'POST', headers:{'Content-Type': file.type || 'application/vnd.sqlite3', 'X-Tonight-Request':'1'}, body:file});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Не получилось восстановить данные');
    toast('Данные восстановлены. Обновляем экран…');
    setTimeout(() => location.reload(), 900);
  } catch (e) { toast(e.message); }
}

async function restoreBackup(name) {
  if (!window.confirm('Восстановить эту копию? Текущие данные будут заменены, но Tonight сначала создаст страховочную копию.')) return;
  try {
    const result = await api(`/api/backups/${encodeURIComponent(name)}/restore`, {method:'POST', body:JSON.stringify({confirmed:true})});
    toast('Данные восстановлены. Обновляем экран…');
    setTimeout(() => location.reload(), 900);
  } catch (e) { toast(e.message); }
}

function forgetLocalViewer() {
  try { for(const key of ['lera','nikita']) { sessionStorage.removeItem(`tonight:mode:${key}`); sessionStorage.removeItem(`tonight:tinder:${key}`); sessionStorage.removeItem(`tonight:roulette:${key}`); sessionStorage.removeItem(`tonight:search:${key}`); } } catch (_) {}
  smartSearch.reset();
  state.roulette=null;state.rouletteRequest++;
  state.tonight=null;state.tonightRequest++;state.tinder=null;state.tinderRequest++;
  state.exclusions=null;state.exclusionsFor=null;state.exclusionsAt=0;state.exclusionDraft={};
  state.user = null;
  state.accessCode = '';
  localStorage.removeItem('tonight:user');
  sessionStorage.removeItem('tonight:access-code');
}

function renderPrivacyDeleteDialog() {
  document.querySelector('.privacy-delete-backdrop')?.remove();
  if (!state.privacyDeleteOpen) return;
  const phrase = 'УДАЛИТЬ ВСЕ ДАННЫЕ';
  const node = document.createElement('div');
  node.className = 'modal-backdrop privacy-delete-backdrop';
  node.innerHTML = `<div class="modal privacy-delete" role="dialog" aria-modal="true" aria-labelledby="privacy-delete-title">
    <p class="eyebrow">Необратимое действие</p><h2 id="privacy-delete-title">Удалить личные данные?</h2>
    <p class="lede">Tonight удалит все вечера, реакции, оценки, историю просмотров, список «На потом», выученный вкус и локальные резервные копии.</p>
    <p class="constraint-warning"><strong>Каталог, постеры и TMDB-настройка останутся.</strong><br>Скачанные ранее копии находятся вне Tonight — при необходимости удалите их самостоятельно.</p>
    <label for="privacy-confirmation">Чтобы продолжить, введите <strong>${phrase}</strong></label>
    <input id="privacy-confirmation" data-privacy-confirmation autocomplete="off" spellcheck="false" placeholder="${phrase}">
    <div class="footer-actions"><button class="button ghost" data-cancel-privacy-delete>Отмена</button><button class="button danger" data-action="confirm-privacy-delete" disabled>Удалить без возможности восстановления</button></div>
  </div>`;
  document.body.appendChild(node);
  const input = node.querySelector('[data-privacy-confirmation]');
  const confirm = node.querySelector('[data-action="confirm-privacy-delete"]');
  const close = () => { state.privacyDeleteOpen=false; node.remove(); };
  input.addEventListener('input', () => { confirm.disabled = input.value !== phrase; });
  node.querySelector('[data-cancel-privacy-delete]').addEventListener('click', close);
  node.addEventListener('click', event => { if (event.target === node) close(); });
  node.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  confirm.addEventListener('click', async () => {
    confirm.disabled = true;
    input.disabled = true;
    try {
      await api('/api/privacy/delete', {method:'POST', body:JSON.stringify({confirmation:input.value})});
      state.privacyDeleteOpen=false;
      forgetLocalViewer();
      state.ws?.close();
      node.remove();
      toast('Личные данные удалены. Tonight начинает с чистого листа.');
      setTimeout(() => location.reload(), 900);
    } catch (error) {
      confirm.disabled = input.value !== phrase;
      input.disabled = false;
      toast(error.message);
    }
  });
  input.focus();
}

async function saveFeedback(rating) {
  try { await api(`/api/history/${state.historyId}/feedback`,{method:'POST',body:JSON.stringify({user_id:state.user,rating})}); if(state.feedbackCompany==='solo'){toast('Оценка сохранена');await go('history');}else{state.view='eveningFeedback';render();} }
  catch(e) { toast(e.message); }
}

async function saveEveningFeedback(fit) {
  try { await api(`/api/history/${state.historyId}/evening-feedback`,{method:'POST',body:JSON.stringify({user_id:state.user,fit})}); toast('Оценка сохранена'); await go('history'); }
  catch(e) { toast(e.message); }
}

async function searchCatalog(query) {
  state.searchQuery = String(query || '').trim();
  state.searchDraft = String(query || '');
  if (!state.searchQuery) { state.searchResults=[]; render(); return; }
  try { state.searchResults = (await api(`/api/movies/search?q=${encodeURIComponent(state.searchQuery)}`)).items; render(); }
  catch(e) { toast(e.message); }
}

async function selectCatalogMovie(movieId, company='solo') {
  if(state.movieSelecting || !state.user || !state.session)return;
  state.movieSelecting=true;
  const origin=state.view;
  document.querySelectorAll('[data-viewing-company],[data-tm-select],[data-smart-select],[data-r-accept],[data-dialog-select],[data-action="watch-saved"],[data-action="select-search-result"],[data-action="select-personal"]').forEach(el=>el.disabled=true);
  try {
    if(state.session.status==='completed') {
      state.session=await api(`/api/sessions/${state.session.id}/restart`,{method:'POST'});
      await api(`/api/sessions/${state.session.id}/join`,{method:'POST',body:joinBody(state.user)});
      connectWs();
    }
    await api(`/api/sessions/${state.session.id}/select-catalog/${encodeURIComponent(movieId)}`,{method:'POST',body:JSON.stringify({company,user_id:state.user})});
    state.session=await api(`/api/sessions/${state.session.id}`);
    if(origin!=='selected')state.selectionReturn=origin;state.modal=null;document.querySelector('.movie-dialog')?.remove();
    state.view='selected';render();
    root.querySelector('h1')?.setAttribute('tabindex','-1');root.querySelector('h1')?.focus();
  } catch(error) {toast(error.message);render();}
  finally {state.movieSelecting=false;}
}
async function selectSearchResult(movieId) { return selectCatalogMovie(movieId); }

async function copyDiagnostics() {
  try { await navigator.clipboard.writeText(state.diagnostics?.technical_log || ''); toast('Технический журнал скопирован'); }
  catch (e) { toast('Не получилось скопировать журнал'); }
}

function openDeferDialog(movieId) {
  state.deferMovieId = movieId;
  renderDeferDialog();
}

async function saveForLater(movieId, reason) {
  try { await api(`/api/watchlist/${encodeURIComponent(movieId)}?user_id=${encodeURIComponent(state.user)}&reason=${encodeURIComponent(reason)}`, {method:'POST'}); toast('Добавили в общий список на потом ♡'); }
  catch (e) { toast(e.message); }
}

async function removeFromWatchlist(movieId) {
  try { await api(`/api/watchlist/${encodeURIComponent(movieId)}`, {method:'DELETE'}); state.watchlist = state.watchlist.filter(movie => movie.id !== movieId); render(); }
  catch (e) { toast(e.message); }
}

async function watchSavedMovie(movieId) { return selectCatalogMovie(movieId); }

function renderModal() {
  document.querySelector('.movie-dialog')?.remove();
  if(!state.modal)return;
  const m=state.modal, origin=document.activeElement;
  const dialog=document.createElement('dialog');dialog.className='movie-dialog';
  dialog.setAttribute('aria-labelledby','movie-dialog-title');
  dialog.innerHTML=`<div class="movie-dialog-head"><span class="eyebrow">О фильме</span><button class="button ghost" data-close aria-label="Закрыть подробности">Закрыть ×</button></div><div class="modal-layout"><div class="detail-poster">${poster(m)}</div><div><h2 id="movie-dialog-title">${esc(m.title)}</h2><p class="meta">${m.year||'Год неизвестен'} · ${m.runtime?`${m.runtime} мин`:'Длительность неизвестна'}</p><p class="hint">${esc((m.genres||[]).join(' · '))}</p><p class="full-synopsis">${esc(m.overview||'Описание отсутствует в каталоге.')}</p><div class="footer-actions">${trailerButton(m)}<button class="button" data-dialog-select>Выбрать на сегодня</button><button class="button secondary" data-dialog-save ${m.saved?'disabled':''}>${m.saved?'✓ В списке «На потом»':'♡ Сохранить на потом'}</button></div><p class="hint">Выбор откроет ваш вечер. Просмотр отмечается отдельно.</p></div></div>`;
  document.body.appendChild(dialog);
  const close=()=>{state.modal=null;dialog.close();dialog.remove();if(origin?.isConnected)origin.focus({preventScroll:true});};
  dialog.querySelector('[data-close]').addEventListener('click',close);
  dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  dialog.addEventListener('click',e=>{if(e.target===dialog)close();});
  dialog.querySelector('[data-dialog-select]').addEventListener('click',()=>selectCatalogMovie(m.id,state.view==='tonight'?state.tonight.filters.company:state.view==='results'?'couple':'solo'));
  dialog.querySelector('[data-dialog-save]').addEventListener('click',async e=>{
    const button=e.currentTarget;button.disabled=true;
    try{await api(`/api/tonight/${state.user}/movies/${encodeURIComponent(m.id)}`,{method:'POST',body:JSON.stringify({action:'watchlist'})});m.saved=true;smartSearch.persist();button.textContent='✓ В списке «На потом»';toast('Добавлено в общий список «На потом»');}
    catch(error){button.disabled=false;toast(error.message);}
  });
  bindPosters(dialog);
  dialog.showModal();dialog.querySelector('[data-close]').focus();
}

function renderDeferDialog() {
  const old=document.querySelector('.defer-backdrop'); old?.remove();
  const movie=(state.session?.recommendations || []).find(item => item.id===state.deferMovieId);
  if(!state.deferMovieId)return;
  const node=document.createElement('div'); node.className='modal-backdrop defer-backdrop'; node.innerHTML=`<div class="modal" role="dialog" aria-modal="true" aria-labelledby="defer-title"><h2 id="defer-title">Почему отложить${movie ? ` «${esc(movie.title)}»` : ''}?</h2><p class="lede">Выберите короткую пометку — она останется рядом с фильмом в общем списке.</p><div class="choice-stack"><button class="choice" data-defer-reason="На вечер, когда будет больше времени">На вечер, когда будет больше времени</button><button class="choice" data-defer-reason="На другое настроение">На другое настроение</button><button class="choice" data-defer-reason="Хочется посмотреть вместе позже">Хочется посмотреть вместе позже</button></div><button class="button ghost" data-cancel-defer>Не откладывать</button></div>`;
  document.body.appendChild(node); node.querySelector('[data-defer-reason]').focus();
  const close=()=>{state.deferMovieId=null;node.remove();};
  node.addEventListener('click', async e=>{if(e.target===node||e.target.closest('[data-cancel-defer]')){close();return;} const reason=e.target.closest('[data-defer-reason]')?.dataset.deferReason; if(reason){const movieId=state.deferMovieId; close(); await saveForLater(movieId, reason);}});
}

function applyRealtimeSession(nextSession) {
  state.personalAt = 0; state.personalRevision++;
  if(nextSession && (state.session?.id!==nextSession.id || state.session?.status!==nextSession.status && nextSession.status==='completed')){state.exclusionsAt=0;invalidateExclusionResults();}
  if (!nextSession) return;
  if (nextSession.status === 'abandoned') { followRestartedSession(); return; }
  const previousStatus = state.session?.status;
  state.session = nextSession;
  if (nextSession.status === 'recommended' && state.view === 'waiting') state.view = 'results';
  if (nextSession.status === 'selected' && ['results','waiting'].includes(state.view)) state.view = 'selected';
  if (nextSession.status === 'watching' && ['selected','results','waiting','swipe'].includes(state.view)) state.view='watching';
  if (nextSession.status === 'completed' && ['selected','watching','results','waiting','swipe'].includes(state.view)) state.view='home';
}

async function restoreAfterReconnect(ws, recovered) {
  try {
    const active = await api('/api/sessions/active');
    if (state.ws !== ws || !state.user) return;
    await api(`/api/sessions/${active.id}/join`, {method:'POST', body:joinBody(state.user)});
    const current = await api(`/api/sessions/${active.id}`);
    if (state.ws !== ws) return;
    applyRealtimeSession(current);
    const socketSessionId = Number(new URL(ws.url).pathname.split('/').at(-2));
    if (active.id !== socketSessionId) {
      connectWs();
      return;
    }
    state.connected = true; state.reconnectAttempts = 0; state.wasDisconnected = false;
    renderRealtime();
    if (recovered) {
      toast('Связь восстановлена ✓');
      if (isRemoteClient()) api(`/api/sessions/${active.id}/connection-restored`, {method:'POST'}).catch(() => {});
    }
  } catch (_) {
    if (state.ws === ws) ws.close();
  }
}

function connectWs() {
  if (!state.user || !state.session) return;
  clearTimeout(state.reconnectTimer); state.reconnectTimer=null;
  state.ws?.close();
  const protocol=location.protocol==='https:'?'wss':'ws'; const accessQuery=isRemoteClient() && state.accessCode ? `?code=${encodeURIComponent(state.accessCode)}` : ''; const ws=new WebSocket(`${protocol}://${location.host}/ws/session/${state.session.id}/${state.user}${accessQuery}`); state.ws=ws;
  ws.onopen=()=>{const recovered=state.wasDisconnected; ws.pinger=setInterval(()=>{if(ws.readyState===1)ws.send('ping')},20000); restoreAfterReconnect(ws,recovered);};
  ws.onmessage=e=>{ const data=JSON.parse(e.data); if(data.type==='exclusions_changed'){if(data.session)applyRealtimeSession(data.session);exclusionsChanged().catch(e=>toast(e.message));return;} if(data.type==='personal_changed'){state.personalAt=0;state.personalRevision++;if(state.view==='home')refreshPersonal();return;} if(data.type==='privacy_reset'){forgetLocalViewer();state.ws=null;toast('Личные данные удалены на основном компьютере');setTimeout(()=>location.reload(),700);return;} if(!data.presence && !data.session) return; if(data.presence)state.presence=data.presence; if(data.session)applyRealtimeSession(data.session); renderRealtime(); };
  ws.onerror=()=>{};
  ws.onclose=event=>{clearInterval(ws.pinger); if(state.ws!==ws)return; if(event.code===1008 && isRemoteClient()){state.user=null;state.accessCode='';localStorage.removeItem('tonight:user');sessionStorage.removeItem('tonight:access-code');state.view='home';toast('Нужен код с экрана Tonight');render();return;} state.connected=false;state.wasDisconnected=true;renderRealtime();const delay=Math.min(12000,1200*(2**Math.min(state.reconnectAttempts,3)));state.reconnectAttempts+=1;state.reconnectTimer=setTimeout(()=>{if(state.user&&state.ws===ws)connectWs();},delay);};
}

async function openPendingFeedback() {
  if (!state.user || !state.session) return;
  const sessionId = state.session.id;
  const view = state.view;
  const user = state.user;
  try {
    const history = await api('/api/history');
    if (state.session?.id !== sessionId || state.user !== user || state.view !== view) return;
    const pending = history.items.find(item => item.session_id === sessionId && item.ratings[user] == null && (item.viewing_company!=='solo' || item.solo_user_id===user));
    if (pending) { state.historyId = pending.history_id; state.feedbackMovie=pending.movie; state.feedbackCompany=pending.viewing_company; state.view = 'feedback'; render(); }
  } catch (_) {}
}

async function init({destination='home'}={}) {
  if(!init.exclusionTimer)init.exclusionTimer=setInterval(()=>{if(state.user)refreshExclusions();},30000);
  const oldLink = new URLSearchParams(location.search);
  if (oldLink.has('room') || /^\/(?:movie-match|match)(?:\/|$)/.test(location.pathname || '')) {
    state.legacyInvite = true;
    destination = 'home';
    const clean = new URL(location.href);
    clean.pathname = '/'; clean.searchParams.delete('room'); clean.searchParams.delete('join'); clean.hash = '';
    history.replaceState(null, '', clean);
    localStorage.setItem('tonight:setup','1');
  }
  state.view='loading'; render();
  try {
    [state.setup,state.session,state.invite]=await Promise.all([api('/api/setup/status'),api('/api/sessions/active'),api('/api/invite')]);
    if (isRemoteClient() || new URLSearchParams(location.search).get('join') === '1') localStorage.setItem('tonight:setup','1');
    state.view=destination!=='home'||localStorage.getItem('tonight:setup')?destination:'setup';
    if(state.setup.catalog_available===0)state.view='setup';
    if(state.user && isRemoteClient() && !state.accessCode){
      state.user=null; localStorage.removeItem('tonight:user');
    }
    if(state.user){
      try {
        await api(`/api/sessions/${state.session.id}/join`,{method:'POST',body:joinBody(state.user)});
      } catch (error) {
        if (!isRemoteClient()) throw error;
        forgetLocalViewer(); state.view='home'; render(); return;
      }
      connectWs();
    }
    render();
    if (!isRemoteClient()) refreshUpdateStatus();
  } catch(e) { state.error=e.message; state.view='error'; render(); }
}

function updateControls(manual = false) {
  if (isRemoteClient()) return '';
  const update = state.update;
  const busy = ['checking','downloading','ready','installing'].includes(update?.phase);
  const offered = Boolean(update?.available_version);
  if (!manual && (!offered || state.updateDismissed === update.available_version) && !['downloading','ready','installing'].includes(update?.phase)) return '';
  const downloading = update?.phase === 'downloading';
  const percent = downloading && update.total_bytes ? Math.min(100, Math.floor(update.download_bytes / update.total_bytes * 100)) : 0;
  const title = offered ? `Доступно обновление ${esc(update.available_version)}` : 'Обновления Tonight';
  return `<aside class="panel update-notice" aria-label="Обновление Tonight"><h3>${title}</h3>
    <p role="status">${esc(update?.message || 'Проверьте, появилась ли новая версия')}${downloading ? ` · ${percent}% · ${(update.download_bytes / 1048576).toFixed(1)} / ${(update.total_bytes / 1048576).toFixed(1)} МБ` : ''}</p>
    ${downloading ? `<progress aria-label="Загрузка обновления" max="100" value="${percent}"></progress>` : ''}
    ${offered ? `<p class="hint">${Math.ceil(update.total_bytes / 1024 / 1024)} МБ. После загрузки Tonight перезапустится. История и настройки сохранятся.</p>` : ''}
    ${offered && !update.install_supported ? '<p class="hint">Обновление одной кнопкой доступно в переносимой версии для Windows.</p>' : ''}
    <div class="footer-actions">${offered ? `<button class="button" data-update-action="install" ${busy || !update.install_supported ? 'disabled' : ''}>${update.can_resume ? 'Продолжить загрузку' : manual ? 'Обновить приложение' : 'Скачать и обновить'}</button>${!busy ? '<button class="button ghost" data-update-action="dismiss">Не сейчас</button>' : ''}` : ''}
    ${manual ? `<button class="button secondary" data-update-action="check" ${busy ? 'disabled' : ''}>${update?.phase === 'checking' ? 'Проверяем…' : 'Проверить обновления'}</button>` : ''}</div></aside>`;
}

function bindUpdateButtons() {
  root.querySelectorAll('[data-update-action]').forEach(button => {
    if (button.dataset.updateBound) return;
    button.dataset.updateBound = '1';
    if (button.dataset.updateAction === 'check') button.addEventListener('click', checkUpdates);
    if (button.dataset.updateAction === 'install') button.addEventListener('click', installUpdate);
    if (button.dataset.updateAction === 'dismiss') button.addEventListener('click', () => {
      state.updateDismissed = state.update?.available_version || '';
      updateNotice();
    });
  });
  const dialog = root.querySelector('[data-update-dialog] dialog');
  if (dialog && !dialog.open) {
    dialog.addEventListener('cancel', event => {
      event.preventDefault();
      if (['downloading','ready','installing'].includes(state.update?.phase)) return;
      state.updateDismissed = state.update?.available_version || '';
      updateNotice();
    });
    dialog.showModal();
  }
}

function updateDialog() {
  if (isRemoteClient() || !state.update?.available_version ||
      (state.updateDismissed === state.update.available_version &&
       !['downloading','ready','installing'].includes(state.update.phase))) return '';
  return `<dialog class="startup-update-dialog" aria-label="Доступно обновление Tonight">${updateControls()}</dialog>`;
}

function updateNotice() {
  const dialogHtml = updateDialog();
  const banner = root.querySelector('[data-update-banner]');
  if (banner) banner.innerHTML = dialogHtml || ['diagnostics','catalog'].includes(state.view) ? '' : updateControls();
  const panel = root.querySelector('[data-update-panel]');
  if (panel) panel.innerHTML = dialogHtml ? '' : updateControls(true);
  const dialogHost = root.querySelector('[data-update-dialog]');
  if (dialogHost && dialogHost.dataset.updateMarkup !== dialogHtml) {
    dialogHost.innerHTML = dialogHtml;
    dialogHost.dataset.updateMarkup = dialogHtml;
  }
  bindUpdateButtons();
}

async function refreshUpdateStatus() {
  clearTimeout(state.updateTimer);
  try {
    const update = await api('/api/updates');
    if (state.updateInstallingFrom && update.current_version !== state.updateInstallingFrom) { location.reload(); return; }
    state.update = update;
    if (update.phase === 'installing') state.updateInstallingFrom = update.current_version;
    updateNotice();
  } catch (_) { /* The server briefly closes while the updater restarts Tonight. */ }
  const busy = ['idle','checking','downloading','ready','installing'].includes(state.update?.phase) || state.updateInstallingFrom;
  state.updateTimer = setTimeout(refreshUpdateStatus, busy ? 1500 : 30000);
}

async function checkUpdates() {
  state.update = {...state.update, phase:'checking', message:'Проверяем обновления…'};
  updateNotice();
  try {
    state.update = await api('/api/updates/check', {method:'POST', headers:{'X-Tonight-Update':'1'}});
    state.updateDismissed = ''; sessionStorage.removeItem('tonight:update-dismissed');
  } catch (error) { state.update = {...state.update, phase:'error', message:error.message}; }
  updateNotice();
}

async function installUpdate() {
  try {
    state.update = await api('/api/updates/install', {method:'POST', headers:{'X-Tonight-Update':'1'}});
    state.updateInstallingFrom = state.update.current_version;
    updateNotice(); refreshUpdateStatus();
  } catch (error) { toast(error.message); }
}


const tonightMoods = [['laugh','☺','Хочу посмеяться'],['scary','◈','Что-то напряжённое'],['cozy','☕','Уютный вечер'],['wow','✧','Хочу удивиться'],['smart','◎','Хочу подумать'],['atmosphere','☾','Что-то атмосферное'],['surprise','✦','Удиви меня']];
const tonightCompanies = [['solo','Один'],['couple','Вдвоём'],['friends','С друзьями'],['family','С семьёй']];
function tonightEntry() {
  return `<section class="tinder-entry"><div><h3>Подбор по условиям</h3><p>Задайте настроение, время и компанию — получите до пяти фильмов. Можно выбрать для себя или двоих.</p></div><button class="button secondary" data-tonight-open>Задать условия</button></section>`;
}
function saveTonight() {
  try { sessionStorage.setItem(`tonight:mode:${state.user}`, JSON.stringify(state.tonight)); } catch (_) {}
}
function openTonight() {
  if (!state.user) return;
  if (state.tonight?.user !== state.user) {
    let saved; try { saved = JSON.parse(sessionStorage.getItem(`tonight:mode:${state.user}`)); } catch (_) {}
    state.tonight = saved?.user === state.user ? saved : {user:state.user, step:0, filters:{mood:null,max_runtime:null,company:null,min_rating:0,min_year:null,max_year:null,excluded_genres:[],exclude_watched:true}, seen:[], data:null, actions:{}};
    state.tonight.busy=false; state.tonight.detail=null;
  }
  state.view='tonight'; render();
}
function tonightChoices(field, options) {
  const t=state.tonight;
  return `<div class="tonight-choices">${options.map(([value,icon,label]) => `<button class="choice ${t.filters[field]===value?'selected':''}" data-tm-field="${field}" data-tm-value="${value ?? ''}" aria-pressed="${t.filters[field]===value}"><span class="tonight-choice-icon" aria-hidden="true">${label?icon:'◌'}</span><strong>${esc(label || icon)}</strong></button>`).join('')}</div>`;
}
function tonightRating(m) {
  return m.rating != null ? `★ ${Number(m.rating).toFixed(1)} / 10 · ${esc(m.rating_source || 'источник не указан')}` : 'Рейтинг не указан';
}
function tonightSynopsis(m) {
  const text=(m.overview || '').trim();
  if(!text)return 'Описание отсутствует в каталоге.';
  // Use only the opening premise from the catalog, without generating plot details.
  const opening=text.match(/^.*?[.!?](?:\s|$)/u)?.[0]?.trim() || text;
  return opening.length>300?opening.slice(0,297).replace(/\s+\S*$/, '')+'…':opening;
}
function tonightCard(m, detail=false) {
  const t=state.tonight, actions=new Set([...(t.actions[m.id] || m.viewer_actions || []),...(m.saved?['watchlist']:[])]);
  return `<article class="tonight-film ${detail?'is-detail':''}"><button class="tonight-poster" data-tm-detail="${esc(m.id)}" aria-label="Подробнее: ${esc(m.title)}">${poster(m)}</button><div class="tonight-film-body"><p class="eyebrow">${tonightRating(m)}</p><h3><button class="tonight-title" data-tm-detail="${esc(m.id)}">${esc(m.title)}</button></h3><p class="hint">${m.year || 'Год не указан'} · ${m.runtime ? `${m.runtime} мин`:'Длительность не указана'}</p><p class="hint">${esc((m.genres || []).join(' · '))}</p><p class="${detail?'':'tonight-overview'}">${esc(detail?(m.overview || 'Описание отсутствует в каталоге.'):tonightSynopsis(m))}</p><p class="tonight-reason">✦ ${esc(m.recommendation_reason)}</p><div class="tonight-film-actions">${detail?trailerButton(m):''}${state.session?.status!=='watching'?`<button class="button" data-tm-select="${esc(m.id)}">Выбрать на сегодня</button>`:''}<details class="film-menu" data-disclosure-key="film-${esc(m.id)}"><summary>Сохранить или отметить просмотр</summary><p class="action-help">«На потом» — общий список. «Уже смотрел» — личная отметка без оценки. «Не интересно» — сигнал для подбора.</p><div class="choice-stack">${[['watchlist','♡ Сохранить на потом'],['watched','✓ Уже смотрел'],['dislike','− Не интересно']].map(([id,label])=>`<button class="button ${actions.has(id)?'':'secondary'}" data-tm-action="${id}" data-tm-id="${esc(m.id)}" ${actions.has(id) || t.saving?'disabled':''} aria-pressed="${actions.has(id)}">${label}${actions.has(id)?' · сохранено':''}</button>`).join('')}</div></details></div></div></article>`;
}
function tonightPeriods() {
  const year=new Date().getFullYear();
  return [['Любой год',null,null],['Последние 5 лет',year-4,year],['2020-е',2020,2029],['2010-е',2010,2019],['2000-е',2000,2009],['90-е',1990,1999],['До 1990',null,1989]];
}
function tonightYearControls(t) {
  const f=t.filters, year=new Date().getFullYear(), presets=tonightPeriods();
  const selected=presets.find(([,min,max])=>f.min_year===min && f.max_year===max);
  const field=t.yearEditor, decade=t.yearDecade ?? Math.floor((f[field] || year)/10)*10;
  return `<fieldset><legend>Год выпуска</legend><div class="chip-grid">${presets.map(([label,min,max],i)=>`<button class="chip ${selected===presets[i]?'selected':''}" data-tm-period="${i}" aria-pressed="${selected===presets[i]}">${label}</button>`).join('')}</div><p class="hint">${f.min_year || f.max_year?`Выбрано: ${f.min_year || 'любой год'} — ${f.max_year || 'любой год'}`:'Без ограничения по году'}</p><div class="tonight-years">${[['min_year','От'],['max_year','До']].map(([key,label])=>`<button class="button secondary" data-tm-year-field="${key}" aria-expanded="${field===key}">${label}: ${f[key] || 'любой год'} ▾</button>`).join('')}</div>${field?`<div class="tonight-year-picker"><div class="footer-actions"><button class="button ghost" data-tm-decade="-10" ${decade<=1880?'disabled':''} aria-label="Предыдущее десятилетие">←</button><strong>${decade}–${Math.min(2100,decade+9)}</strong><button class="button ghost" data-tm-decade="10" ${decade>=2100?'disabled':''} aria-label="Следующее десятилетие">→</button></div><div class="chip-grid">${Array.from({length:10},(_,i)=>decade+i).filter(y=>y>=1888 && y<=2100).map(y=>`<button class="chip ${f[field]===y?'selected':''}" data-tm-year="${y}" aria-pressed="${f[field]===y}">${y}</button>`).join('')}<button class="chip" data-tm-year="">Любой год</button></div></div>`:''}</fieldset>`;
}
function renderTonight() {
  const t=state.tonight;
  if (!t || t.user!==state.user) return renderHome();
  const f=t.filters, titles=['Какое сегодня настроение?','Сколько есть времени?','С кем смотрим?','Добавим пару деталей?'];
  const steps=['Настроение','Время','Компания','Детали'];
  const nav=`<nav class="tonight-steps" aria-label="Шаги подбора">${steps.map((label,i)=>`<button data-tm-step="${i}" class="${t.step===i?'active':''}" ${t.busy?'disabled':''} ${t.step===i?'aria-current="step"':''}>${i+1}<span>${label}</span></button>`).join('')}</nav>`;
  let body;
  if(t.detail) {
    const m=t.data?.items.find(m=>m.id===t.detail);
    body=`<button class="button ghost" data-tm-return>← К результатам</button>${m?tonightCard(m,true):''}`;
  } else if(t.step<4) {
    const content=[()=>tonightChoices('mood',tonightMoods),()=>tonightChoices('max_runtime',[[90,'До 90 минут'],[120,'До 120 минут'],[150,'До 150 минут'],[null,'Неважно']]),()=>tonightChoices('company',tonightCompanies),()=>`<div class="tonight-options"><label>Минимальный рейтинг <select data-tm-input="min_rating">${[0,6,7,8,9].map(n=>`<option value="${n}" ${f.min_rating===n?'selected':''}>${n?`${n} / 10`:'Неважно'}</option>`).join('')}</select></label>${tonightYearControls(t)}<fieldset><legend>Исключить жанры</legend><div class="chip-grid">${[...new Set([...genres,'семейный','приключения','криминал','история','музыка','военный','вестерн'])].map(g=>`<button class="chip ${f.excluded_genres.includes(g)?'selected':''}" data-tm-genre="${g}" aria-pressed="${f.excluded_genres.includes(g)}">${g}</button>`).join('')}</div></fieldset><label class="tonight-check"><input type="checkbox" data-tm-watched ${f.exclude_watched?'checked':''}> Исключить просмотренные фильмы</label><p class="hint">Настроение — приблизительный ориентир по жанрам и темам каталога. Эмоциональный тон и возрастной допуск не гарантируем.</p></div>`][t.step]();
    body=`${nav}<div class="tonight-stage" key="${t.step}"><h2 tabindex="-1" data-tm-heading>${titles[t.step]}</h2><p class="lede">${t.step===3?'Все параметры на этом шаге необязательны.':t.step===2?'Вдвоём учитываем вкус обоих зрителей. Для друзей — ваш вкус; для семьи — семейные жанры. Это не возрастной допуск.':''}</p>${content}<div class="footer-actions"><button class="button ghost" data-tm-back>${t.step?'← Назад':'На главную'}</button><button class="button" data-tm-next ${t.busy?'disabled':''}>${t.data?'Применить изменения':t.step===3?'Подобрать фильмы':'Далее →'}</button>${t.data?'<button class="button ghost" data-tm-cancel>Отменить изменения</button>':''}</div></div>`;
  } else {
    body=`<div class="screen-head result-heading"><h2 tabindex="-1" data-tm-results>Ваши варианты на вечер</h2><p class="hint">${esc(tonightMoods.find(m=>m[0]===f.mood)?.[2] || '')} · ${f.max_runtime?`до ${f.max_runtime} мин`:'любая длительность'} · ${esc(tonightCompanies.find(c=>c[0]===f.company)?.[1] || '')}</p><button class="button ghost" data-tm-step="0">Изменить условия</button></div>${t.busy?'<div class="empty" role="status">Tonight IQ подбирает фильмы…</div>':`${t.data?.limited?`<aside class="tonight-empty" role="status"><h3>${t.data.items.length?`Нашлось ${t.data.items.length} из 5 вариантов`:'Подходящие варианты закончились'}</h3><p>${t.data.exhausted?'Уже показанные фильмы исключены из повторного подбора. ':''}${t.data.catalog_available===0?'В каталоге пока нет фильмов с подтверждёнными данными о прокате. Обновите каталог в разделе «Каталог».':'Сочетание условий, истории просмотров и исключений оставляет мало фильмов. Измените условия или снимите исключение просмотренных.'} Ограничения сохранены.</p>${!t.data.items.length?exclusionEmptyHelp():''}<div class="footer-actions">${(t.data.relaxations || []).map(r=>`<button class="button secondary" data-tm-relax="${r.field}">Ослабить: ${esc(r.label)} · до ${r.available} вариантов</button>`).join('')}<button class="button ghost" data-tm-step="3">Изменить фильтры</button>${t.seen.length?'<button class="button ghost" data-tm-repeat>Вернуться к уже показанным</button>':''}</div></aside>`:''}<div class="tonight-films">${(t.data?.items || []).map(m=>tonightCard(m)).join('')}</div><div class="footer-actions"><button class="button" data-tm-more ${!t.data?.items.length?'disabled':''}>Другие варианты ↻</button><button class="button ghost" data-view="home">На главную</button></div>`}`;
  }
  return shell(`<section class="tonight-mode" aria-busy="${!!t.busy}">${choicesBack()}${t.step<4?'<p class="eyebrow">Подбор на вечер</p>':''}${t.error?`<p role="alert" class="constraint-warning">${esc(t.error)}</p>`:''}${body}</section>`);
}
async function fetchTonight(more=false) {
  const t=state.tonight;
  if(t.busy || t.saving)return;
  if(!t.filters.mood){t.step=0;render();return;}
  if(!t.filters.company){t.step=2;render();return;}
  if(t.filters.min_year && t.filters.max_year && t.filters.min_year>t.filters.max_year){t.error='Начальный год должен быть не позже конечного';t.step=3;render();return;}
  const seen=more?[...new Set([...t.seen,...(t.data?.items || []).map(m=>m.id)])]:[];
  const request=++state.tonightRequest; t.busy=true;t.error='';t.step=4;render();
  try {
    const data=await api(`/api/tonight/${t.user}/recommendations`,{method:'POST',body:JSON.stringify({...t.filters,seen_ids:seen})});
    if(request!==state.tonightRequest || state.user!==t.user || state.tonight!==t)return;
    t.data=data;t.seen=seen;t.applied=structuredClone(t.filters);t.actions={};
  } catch(e) {t.error=e.message;if(!t.data)t.step=3;}
  finally {t.busy=false;saveTonight();if(state.view==='tonight' && state.tonight===t){render();window.scrollTo(0,0);root.querySelector('[data-tm-results]')?.focus({preventScroll:true});}}
}
async function selectTonightMovie(movieId) { return selectCatalogMovie(movieId,state.tonight.filters.company); }
function bindTonight() {
  root.querySelector('[data-tonight-open]')?.addEventListener('click',openTonight);
  const t=state.tonight;if(state.view!=='tonight' || !t)return;
  root.querySelectorAll('[data-tm-step]').forEach(el=>el.addEventListener('click',()=>{t.step=Number(el.dataset.tmStep);t.detail=null;t.error='';render();}));
  root.querySelectorAll('[data-tm-field]').forEach(el=>el.addEventListener('click',()=>{t.filters[el.dataset.tmField]=el.dataset.tmField==='max_runtime'?(Number(el.dataset.tmValue)||null):el.dataset.tmValue;saveTonight();render();}));
  root.querySelectorAll('[data-tm-period]').forEach(el=>el.addEventListener('click',()=>{
    const [,min,max]=tonightPeriods()[Number(el.dataset.tmPeriod)];
    t.filters.min_year=min;t.filters.max_year=max;t.yearEditor=null;saveTonight();render();
  }));
  root.querySelectorAll('[data-tm-year-field]').forEach(el=>el.addEventListener('click',()=>{t.yearEditor=t.yearEditor===el.dataset.tmYearField?null:el.dataset.tmYearField;t.yearDecade=Math.floor((t.filters[t.yearEditor] || new Date().getFullYear())/10)*10;render();}));
  root.querySelectorAll('[data-tm-decade]').forEach(el=>el.addEventListener('click',()=>{t.yearDecade=Math.max(1880,Math.min(2100,t.yearDecade+Number(el.dataset.tmDecade)));render();}));
  root.querySelectorAll('[data-tm-year]').forEach(el=>el.addEventListener('click',()=>{
    const year=Number(el.dataset.tmYear)||null;t.filters[t.yearEditor]=year;
    if(t.filters.min_year && t.filters.max_year && t.filters.min_year>t.filters.max_year)t.filters[t.yearEditor==='min_year'?'max_year':'min_year']=year;
    t.yearEditor=null;saveTonight();render();
  }));
  root.querySelectorAll('[data-tm-input]').forEach(el=>el.addEventListener('input',()=>{t.filters[el.dataset.tmInput]=(el.dataset.tmInput==='min_rating'?Number(el.value):Number(el.value)||null);saveTonight();}));
  root.querySelectorAll('[data-tm-genre]').forEach(el=>el.addEventListener('click',()=>{const g=el.dataset.tmGenre;t.filters.excluded_genres=t.filters.excluded_genres.includes(g)?t.filters.excluded_genres.filter(x=>x!==g):[...t.filters.excluded_genres,g];saveTonight();render();}));
  root.querySelector('[data-tm-watched]')?.addEventListener('change',e=>{t.filters.exclude_watched=e.target.checked;saveTonight();});
  root.querySelector('[data-tm-next]')?.addEventListener('click',()=>{if(t.data || t.step===3){fetchTonight();return;}if(t.step===0&&!t.filters.mood || t.step===2&&!t.filters.company){toast('Выберите один вариант');return;}t.step++;saveTonight();render();root.querySelector('[data-tm-heading]')?.focus();});
  root.querySelector('[data-tm-back]')?.addEventListener('click',()=>{if(t.step)t.step--;else state.view='home';saveTonight();render();});
  root.querySelector('[data-tm-cancel]')?.addEventListener('click',()=>{t.filters=structuredClone(t.applied);t.step=4;render();});
  root.querySelector('[data-tm-more]')?.addEventListener('click',()=>fetchTonight(true));
  root.querySelector('[data-tm-repeat]')?.addEventListener('click',()=>fetchTonight(false));
  root.querySelectorAll('[data-tm-relax]').forEach(el=>el.addEventListener('click',()=>{const k=el.dataset.tmRelax;if(k==='year'){t.filters.min_year=null;t.filters.max_year=null;}else if(k==='mood')t.filters.mood='surprise';else if(k==='company')t.filters.company='solo';else t.filters[k]=k==='excluded_genres'?[]:k==='min_rating'?0:null;fetchTonight();}));
  root.querySelectorAll('[data-tm-detail]').forEach(el=>el.addEventListener('click',()=>{t.scroll=window.scrollY;t.detail=el.dataset.tmDetail;render();window.scrollTo(0,0);root.querySelector('[data-tm-return]')?.focus();}));
  root.querySelector('[data-tm-return]')?.addEventListener('click',()=>{const id=t.detail;t.detail=null;render();window.scrollTo(0,t.scroll || 0);root.querySelector(`[data-tm-detail="${CSS.escape(id)}"]`)?.focus({preventScroll:true});});
  root.querySelectorAll('[data-tm-select]').forEach(el=>el.addEventListener('click',event=>{t.detail=null;saveTonight();selectTonightMovie(event.currentTarget.dataset.tmSelect);}));
  root.querySelectorAll('[data-tm-action]').forEach(el=>el.addEventListener('click',async()=>{
    if(t.saving)return;t.saving=true;el.disabled=true;
    try {await api(`/api/tonight/${t.user}/movies/${encodeURIComponent(el.dataset.tmId)}`,{method:'POST',body:JSON.stringify({action:el.dataset.tmAction})});const m=t.data.items.find(m=>m.id===el.dataset.tmId);t.actions[m.id]=[...new Set([...(t.actions[m.id] || m.viewer_actions || []),el.dataset.tmAction])];toast(el.dataset.tmAction==='watchlist'?'Добавлено в общий список «На потом»':el.dataset.tmAction==='watched'?'Просмотр отмечен без оценки':'Ответ сохранён: учтём в вашем подборе');}
    catch(e){toast(e.message);}finally{t.saving=false;saveTonight();if(state.view==='tonight'&&state.tonight===t)render();}
  }));
}



// Discovery shares Tonight IQ and its persisted movie statuses.
function saveTinder() {
  const t=state.tinder;
  if(t)try {sessionStorage.setItem(`tonight:tinder:${t.user}`,JSON.stringify(t));}catch(_){}
}
function openTinder() {
  if(!state.user)return;
  if(state.tinder?.user!==state.user){
    let saved;try{saved=JSON.parse(sessionStorage.getItem(`tonight:tinder:${state.user}`));}catch(_){}
    state.tinder=saved?.user===state.user?saved:{user:state.user,queue:[],seen:[],history:[],save:false};
    // Revalidate a restored deck against current server restrictions. Queued
    // cards were not acted on and must remain eligible for that fresh request.
    const queued=new Set(state.tinder.queue.map(movie=>movie.id));
    state.tinder.seen=state.tinder.seen.filter(id=>!queued.has(id));
    state.tinder.queue=[];state.tinder.loaded=false;state.tinder.error='';
    try { const preference=localStorage.getItem(`tonight:tinder-save:${state.user}`); if(preference!==null)state.tinder.save=preference==='1'; } catch(_){}
    state.tinder.busy=false;state.tinder.detail=false;
  }
  state.view='tinder';render();
  if(!state.tinder.queue.length && !state.tinder.loaded)fetchTinder();
}
async function fetchTinder(fresh=false) {
  const t=state.tinder;if(!t || t.busy)return;
  if(fresh){t.queue=[];t.seen=[];t.history=[];t.pending=null;t.detail=false;}
  const request=++state.tinderRequest;t.busy=true;t.error='';render();
  try{
    const data=await api(`/api/tinder/${t.user}/recommendations`,{method:'POST',body:JSON.stringify({seen_ids:t.seen})});
    if(request!==state.tinderRequest || state.tinder!==t || state.user!==t.user)return;
    t.queue=data.items;t.loaded=true;t.cold=data.cold_start;t.catalogAvailable=data.catalog_available;
    t.seen=[...new Set([...t.seen,...data.items.map(m=>m.id)])];
  }catch(e){if(request===state.tinderRequest&&state.tinder===t&&state.user===t.user)t.error=e.message;}
  finally{if(request===state.tinderRequest&&state.tinder===t&&state.user===t.user){t.busy=false;saveTinder();if(state.view==='tinder')render();}}
}
function renderTinder(){
  const t=state.tinder,m=t?.queue[0];if(!t)return shell('');
  const disabled=t.busy?'disabled':'';
  const details=m?`<p class="eyebrow">${tonightRating(m)}</p><h2>${esc(m.title)}</h2><p class="hint">${m.year||'Год не указан'} · ${m.runtime?`${m.runtime} мин`:'Длительность не указана'}</p><p class="hint">${esc((m.genres||[]).join(' · '))}</p>`:'';
  const undo=`<button class="button secondary tinder-undo" data-kt-undo aria-label="Отменить последнее действие" title="Отменить последнее действие" ${!t.history.length||t.busy||t.detail?'disabled':''}><span aria-hidden="true">↶</span><span class="undo-label">Отмена</span></button>`;
  return shell(`<section class="tinder-mode" aria-busy="${!!t.busy}">${choicesBack()}<div class="tinder-heading"><h1>Кино-Tinder</h1><details class="mode-menu"><summary>Настройки</summary><div><label class="tinder-save"><input type="checkbox" data-kt-save ${t.save?'checked':''} ${disabled}> Добавлять интересные фильмы в общий список «На потом»</label><button class="button ghost" data-kt-new ${disabled}>Новая сессия</button><p class="hint">«Уже смотрел» отмечает просмотр без оценки. Интерес и список «На потом» сохраняются отдельно.</p><p class="hint keyboard-hint">← / → / ↑ — действия · Enter — подробности · Z — отмена</p>${temporaryExclusions()}</div></details></div>
    ${t.error?`<p role="alert" class="constraint-warning">${esc(t.error)}</p><button class="button secondary" data-kt-retry>${t.pending?'Повторить сохранение':'Повторить загрузку'}</button>`:''}
    <p class="tinder-status">${t.save?'Интерес → также в «На потом»':'Интерес помогает следующему подбору'}</p>
    ${t.detail&&m?`<div class="tinder-detail"><button class="button ghost" data-kt-close>← К карточке</button>${details}<p>${esc(m.overview||'Описание отсутствует в каталоге.')}</p><p class="tonight-reason">${esc(m.recommendation_reason || '')}</p></div>`:m?`
    <article class="tinder-card" data-kt-card tabindex="0" aria-label="${esc(m.title)}">
      <div class="tinder-image">${poster(m)}<span class="tinder-direction" aria-hidden="true"></span></div>
      <div class="tinder-copy">${details}<p>${esc(tonightSynopsis(m))}</p><button class="button ghost" data-kt-details>Подробнее о фильме</button></div>
    </article><div class="tinder-action-panel"><div class="tinder-controls" aria-label="Действия с фильмом">${[['dislike','←','Не интересно'],['watched','↑','Уже смотрел'],['interest','→','Интересно']].map(([action,icon,label])=>`<button class="button ${action==='interest'?'':'secondary'}" data-kt-action="${action}" ${disabled}><span aria-hidden="true">${icon}</span> ${label}</button>`).join('')}${undo}</div></div>`:`<div class="empty" role="status"><h2>${t.error?'Не удалось загрузить карточки':t.busy?'Подбираем фильмы…':!t.loaded?'Карточки ещё не загружены':'Фильмы закончились'}</h2><p>${t.error?'Повторите загрузку кнопкой выше.':t.busy?'Учитываем ваш вкус.':!t.loaded?'Загружаем доступные варианты.':t.catalogAvailable===0?'В каталоге нет подтверждённых фильмов. Откройте каталог для обновления.':'Доступные варианты просмотрены. Новая сессия учитывает сохранённые действия.'}</p>${!t.busy&&t.loaded&&!t.error?exclusionEmptyHelp():''}${!t.busy&&t.loaded&&!t.error?'<button class="button" data-kt-new>Новая сессия</button><button class="button ghost" data-view="library">Каталог</button>':''}${undo}</div>`}
    <p class="sr-only" aria-live="polite">${m?`Следующий фильм: ${esc(m.title)}`:'Нет карточки'}</p></section>`,{narrow:true});
}

function tinderRequestId(){
  // LAN phones use HTTP: randomUUID requires a secure context, getRandomValues does not.
  if(typeof crypto.randomUUID==='function')return crypto.randomUUID();
  const bytes=crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('');
}
async function tinderAct(action){
  const t=state.tinder,m=t?.queue[0];if(!m||t.busy||t.detail||state.user!==t.user)return;
  // Reuse the request ID after a lost response: the server applies it once.
  if(t.pending && t.pending.action!==action){toast('Повторите предыдущее действие, чтобы проверить сохранение');return;}
  t.busy=true;t.error='';
  root.querySelectorAll('[data-kt-action], [data-kt-undo], [data-kt-new], [data-kt-save]').forEach(el=>el.disabled=true);
  try{
    t.pending ||= {action,request_id:tinderRequestId(),save_watchlist:action==='interest'&&!!t.save};
    saveTinder();
    const result=await api(`/api/tinder/${t.user}/movies/${encodeURIComponent(m.id)}`,{method:'POST',body:JSON.stringify(t.pending)});
    const card=root.querySelector('[data-kt-card]');
    if(card&&!matchMedia('(prefers-reduced-motion: reduce)').matches){card.classList.add(`exit-${action}`);await new Promise(resolve=>setTimeout(resolve,180));}
    toast(action==='interest'?(t.pending.save_watchlist?'Интерес сохранён · фильм в «На потом»':'Интерес сохранён для подбора'):action==='watched'?'Просмотр отмечен без оценки':'Ответ сохранён: учтём в вашем подборе');
    t.history.push({id:result.id,movie:m});t.queue.shift();t.pending=null;saveTinder();
    if(!t.queue.length){t.busy=false;await fetchTinder();}
  }catch(e){t.error=e.message;}
  finally{t.busy=false;saveTinder();if(state.view==='tinder'&&state.tinder===t){render();root.querySelector('[data-kt-card]')?.focus({preventScroll:true});}}
}
async function tinderUndo(){
  const t=state.tinder,entry=t?.history.at(-1);if(!entry||t.busy||t.detail)return;
  t.busy=true;t.error='';render();
  try{await api(`/api/tinder/${t.user}/undo/${entry.id}`,{method:'POST'});t.history.pop();toast('Последнее действие отменено');t.queue=t.queue.filter(m=>m.id!==entry.movie.id);t.queue.unshift(entry.movie);t.pending=null;}
  catch(e){t.error=e.message;}
  finally{t.busy=false;saveTinder();if(state.view==='tinder'&&state.tinder===t){render();root.querySelector('[data-kt-card]')?.focus({preventScroll:true});}}
}
function bindTinder(){
  root.onkeydown=tinderKeydown;
  root.querySelector('[data-tinder-open]')?.addEventListener('click',openTinder);
  if(state.view!=='tinder')return;
  const t=state.tinder;
  root.querySelectorAll('[data-kt-new]').forEach(el=>el.addEventListener('click',()=>fetchTinder(true)));
  root.querySelector('[data-kt-retry]')?.addEventListener('click',()=>t.pending?tinderAct(t.pending.action):fetchTinder());
  root.querySelector('[data-kt-undo]')?.addEventListener('click',tinderUndo);
  root.querySelector('[data-kt-save]')?.addEventListener('change',e=>{t.save=e.target.checked;try{localStorage.setItem(`tonight:tinder-save:${t.user}`,t.save?'1':'0');}catch(_){}saveTinder();render();});
  root.querySelectorAll('[data-kt-action]').forEach(el=>el.addEventListener('click',()=>tinderAct(el.dataset.ktAction)));
  const open=()=>{if(!t.busy){t.detail=true;render();root.querySelector('[data-kt-close]')?.focus();}};
  root.querySelector('[data-kt-details]')?.addEventListener('click',open);
  root.querySelector('[data-kt-close]')?.addEventListener('click',()=>{t.detail=false;render();root.querySelector('[data-kt-card]')?.focus({preventScroll:true});});
  const card=root.querySelector('[data-kt-card]');if(!card)return;
  let drag=null,suppress=false;

  card.addEventListener('pointerdown',e=>{if(t.busy||!e.isPrimary||e.button!==0||e.target.closest('button,a,input,summary') || (e.pointerType==='touch'&&!e.target.closest('.tinder-image')))return;drag={x:e.clientX,y:e.clientY,id:e.pointerId};card.setPointerCapture(e.pointerId);});
  card.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;const x=e.clientX-drag.x,y=e.clientY-drag.y;if(Math.hypot(x,y)<10)return;suppress=true;if(y>Math.abs(x)){card.style.transform='';delete card.dataset.direction;card.querySelector('.tinder-direction').textContent='';return;}const action=y<0&&-y>Math.abs(x)?'watched':x>0?'interest':'dislike';card.style.transform=`translate(${x}px,${y}px) rotate(${x/25}deg)`;card.dataset.direction=action;card.querySelector('.tinder-direction').textContent={interest:'Интересно →',dislike:'← Не интересно',watched:'↑ Уже смотрел'}[action];});
  const reset=()=>{drag=null;card.style.transform='';delete card.dataset.direction;card.querySelector('.tinder-direction').textContent='';};
  card.addEventListener('pointerup',e=>{if(!drag||drag.id!==e.pointerId)return;const x=e.clientX-drag.x,y=e.clientY-drag.y;reset();if(Math.abs(x)>85||y< -85){suppress=true;tinderAct(y< -85&&-y>Math.abs(x)?'watched':x>0?'interest':'dislike');}setTimeout(()=>{suppress=false;},0);});
  card.addEventListener('pointercancel',e=>{if(drag?.id===e.pointerId){reset();suppress=false;}});
  card.addEventListener('lostpointercapture',()=>{if(drag)reset();});
}
function tinderKeydown(e){
  if(state.view!=='tinder'||state.tinder?.busy||e.repeat||e.altKey||e.ctrlKey||e.metaKey||document.querySelector('.modal-backdrop')||e.target.closest('input,select,textarea,details,[contenteditable="true"]'))return;
  if(state.tinder.detail){if(e.key==='Escape'){e.preventDefault();root.querySelector('[data-kt-close]')?.click();}return;}
  const action={ArrowLeft:'dislike',ArrowRight:'interest',ArrowUp:'watched'}[e.key];
  if(action){e.preventDefault();tinderAct(action);}else if(e.key.toLowerCase()==='z'){e.preventDefault();tinderUndo();}
  else if(e.key==='Enter'&&e.target.matches('[data-kt-card]')){e.preventDefault();root.querySelector('[data-kt-details]')?.click();}
}


// One real IQ result is chosen before its poster is animated.
function rouletteEntry(){
  return `<section class="tinder-entry"><div><h3>Кинорулетка</h3><p>Задайте условия — получите один фильм. Можно попросить другой.</p></div><button class="button secondary" data-roulette-open>Открыть рулетку</button></section>`;
}
function saveRoulette(){
  const r=state.roulette;if(!r)return;
  try{sessionStorage.setItem(`tonight:roulette:${r.user}`,JSON.stringify({user:r.user,filters:r.filters,seen:r.seen,accepted:r.accepted,acceptedTitle:r.acceptedTitle,movie:r.movie}));}catch(_){}
}
function openRoulette(){
  if(!state.user)return;
  if(state.roulette?.user!==state.user){
    let saved;try{saved=JSON.parse(sessionStorage.getItem(`tonight:roulette:${state.user}`));}catch(_){}
    state.roulette=saved?.user===state.user?saved:{user:state.user,filters:{mode:'smart',max_runtime:null,min_rating:0,min_year:null,max_year:null,included_genres:[],excluded_genres:[],exclude_watched:true},seen:[],accepted:null};
    state.roulette.busy=false; delete state.roulette.short;
  }
  state.view='roulette';render();
}
const ROULETTE_REVEAL_MS = 2200;
function rouletteDraw(movie) {
  // Decorative frames reveal the one result already chosen by the server.
  // No other film is selected, rated, or added to history during the draw.
  return `<article class="roulette-draw" style="--draw-duration:${ROULETTE_REVEAL_MS}ms" aria-busy="true"><div class="draw-window" aria-hidden="true"><div class="draw-track">${Array.from({length:7},(_,i)=>`<div class="draw-frame draw-placeholder" style="--frame-hue:${i%3}"><span class="draw-film-mark"></span></div>`).join('')}<div class="draw-frame draw-winner">${poster(movie)}</div></div><div class="draw-marker"></div></div><div class="draw-caption" role="status"><p class="eyebrow">Кинорулетка</p><h2>Открываем ваш фильм…</h2><p>С учётом выбранных условий</p></div></article>`;
}
function renderRoulette(){
  const r=state.roulette;if(!r||r.user!==state.user)return renderHome();
  const f=r.filters,m=r.movie,locked=r.busy||r.spinning;
  const genreChoices=(key,label)=>`<fieldset><legend>${label}</legend><div class="chip-grid">${[...new Set([...genres,'семейный','приключения','криминал','история','музыка','военный','вестерн'])].map(g=>`<button class="chip ${f[key].includes(g)?'selected':''}" data-r-genre="${key}" data-r-value="${esc(g)}" aria-pressed="${f[key].includes(g)}">${esc(g)}</button>`).join('')}</div></fieldset>`;
  return shell(`<section class="roulette-mode">${choicesBack()}<div class="tinder-heading"><div><h1>Кинорулетка</h1></div></div>
  <details class="roulette-configuration" data-r-settings data-render-state ${r.settingsOpen??!m?'open':''}><summary>Настройки выбора</summary><fieldset class="roulette-settings" ${locked?'disabled':''}><legend>Как выбираем?</legend><div class="tonight-choices">${[['smart','Умный выбор','Больше веса вашему вкусу'],['surprise','Полная неожиданность','Больше шансов новым жанрам'],['watchlist','Из моего списка','Только из «На потом»']].map(([id,title,desc])=>`<button class="choice ${f.mode===id?'selected':''}" data-r-mode="${id}" aria-pressed="${f.mode===id}"><strong>${title}</strong><small>${desc}</small></button>`).join('')}</div>
  <details class="roulette-filters" ${r.filtersOpen?'open':''}><summary>Быстрые ограничения</summary><p class="hint">Применяем вместе с сохранёнными ограничениями профиля. Автоматически ничего не ослабляем.</p><div class="roulette-inputs">${[['max_runtime','Максимум минут',1,1440],['min_rating','Минимальный рейтинг',0,10],['min_year','Год от',1888,2100],['max_year','Год до',1888,2100]].map(([key,label,min,max])=>`<label>${label}<input type="number" data-r-input="${key}" min="${min}" max="${max}" step="${key==='min_rating'?'.1':'1'}" value="${f[key]??''}" placeholder="Неважно"></label>`).join('')}</div>${genreChoices('included_genres','Жанры: хотя бы один из выбранных')}${genreChoices('excluded_genres','Исключить жанры')}<label class="tonight-check"><input type="checkbox" data-r-watched ${f.exclude_watched?'checked':''}> Исключить уже просмотренные</label></details>
  </fieldset><p class="hint">Скрытые и нежелательные фильмы исключены во всех режимах.</p></details>

  ${!m?`<button class="button large roulette-launch" data-r-launch ${locked?'disabled':''}>${r.busy?'Подбираем фильм…':'Реши за меня'}</button>`:''}
  ${r.error?`<p class="error" role="alert">${esc(r.error)}</p>`:''}
  ${r.empty?`<div class="empty" role="status"><h2>${r.watchlistCount===0?'В списке пока пусто':'Подходящие фильмы закончились'}</h2><p>${r.watchlistCount===0?'Добавьте фильмы в «На потом» или выберите другой режим.':'Измените быстрые ограничения или сохранённые ограничения профиля. Уже предложенные в этой сессии фильмы исключены; ограничения сохранены.'}</p>${exclusionEmptyHelp()}</div>`:''}
  ${r.spinning&&m?rouletteDraw(m):m?`<article class="roulette-result" aria-busy="${!!r.spinning}"><div class="roulette-poster">${poster(m)}</div><div class="roulette-copy"><p class="eyebrow">${tonightRating(m)}</p><h2 tabindex="-1" data-r-title>${esc(m.title)}</h2><p class="hint">${m.year||'Год не указан'} · ${m.runtime?`${m.runtime} мин`:'Длительность не указана'}</p><p class="hint">${esc((m.genres||[]).join(' · '))}</p><p class="roulette-synopsis">${esc(tonightSynopsis(m))}</p><p class="tonight-reason">✦ ${esc(m.recommendation_reason)}</p><div class="tonight-film-actions">${trailerButton(m)}<button class="button" data-r-accept ${r.busy?'disabled':''}>Выбрать на сегодня</button><button class="button secondary" data-r-launch>Другой фильм</button><button class="button secondary" data-r-action="watchlist" ${m.saved||r.busy?'disabled':''}>${m.saved?'✓ В списке':'Сохранить на потом'}</button><button class="button ghost" data-r-action="dislike" ${r.busy?'disabled':''}>Не интересно</button></div>${m.overview?descriptionDisclosure(m.overview,m.id,'roulette-description'):''}<p class="hint">Выбор откроет ваш вечер. Сохранение добавляет в общий список «На потом». Просмотр отмечается отдельно.</p></div></article>`:''}</section>`);
}
function finishRoulette(r){
  clearTimeout(r.timer);r.spinning=false;saveRoulette();
  if(state.roulette===r&&state.user===r.user&&state.view==='roulette'){render();root.querySelector('[data-r-title]')?.focus({preventScroll:true});}
}
async function spinRoulette(){
  const r=state.roulette;if(!r||r.busy||r.spinning)return;
  const inputs=[...root.querySelectorAll('[data-r-input]')];
  if(inputs.some(el=>!el.reportValidity()))return;
  if(r.filters.min_year&&r.filters.max_year&&r.filters.min_year>r.filters.max_year){r.error='Начальный год должен быть не позже конечного';render();return;}
  r.busy=true;r.error='';r.empty=false;const request=++state.rouletteRequest;render();
  try{
    const data=await api(`/api/roulette/${r.user}/pick`,{method:'POST',body:JSON.stringify({...r.filters,seen_ids:r.seen})});
    if(state.roulette!==r||state.user!==r.user||request!==state.rouletteRequest)return;
    r.settingsOpen=false;r.movie=data.items[0]||null;r.empty=!r.movie;r.watchlistCount=data.watchlist_count;
    if(r.movie){r.seen.push(r.movie.id);r.spinning=true;saveRoulette();
      const duration=matchMedia('(prefers-reduced-motion: reduce)').matches?0:ROULETTE_REVEAL_MS;
      r.timer=setTimeout(()=>finishRoulette(r),duration);
    }
  }catch(e){r.error=e.message;}
  finally{r.busy=false;if(state.roulette===r&&state.user===r.user&&state.view==='roulette'){render();if(r.spinning)root.querySelector('.roulette-draw')?.scrollIntoView({block:'start',behavior:'auto'});}}
}
async function rouletteAction(action){
  const r=state.roulette,m=r?.movie;if(!m||r.busy||r.spinning||state.user!==r.user)return;
  r.busy=true;r.error='';render();
  try{
    await api(`/api/tonight/${r.user}/movies/${encodeURIComponent(m.id)}`,{method:'POST',body:JSON.stringify({action})});
    if(action==='watchlist'){m.saved=true;toast('Добавлено в общий список «На потом»');}
    else{r.movie=null;if(r.accepted===m.id){r.accepted=null;r.acceptedTitle=null;}}
    saveRoulette();
    if(state.user===r.user){state.personal=null;state.tonight=null;state.tinder=null;try{sessionStorage.removeItem(`tonight:mode:${r.user}`);sessionStorage.removeItem(`tonight:tinder:${r.user}`);}catch(_){}}
  }catch(e){r.error=e.message;}
  finally{r.busy=false;if(state.roulette===r&&state.user===r.user&&state.view==='roulette')render();}
}
function bindRoulette(){
  root.querySelector('[data-roulette-open]')?.addEventListener('click',openRoulette);
  if(state.view!=='roulette')return;
  const r=state.roulette;
  root.querySelector('[data-r-settings]')?.addEventListener('toggle',e=>{r.settingsOpen=e.target.open;});
  root.querySelector('.roulette-filters')?.addEventListener('toggle',e=>{r.filtersOpen=e.target.open;});
  root.querySelectorAll('[data-r-mode]').forEach(el=>el.addEventListener('click',()=>{r.filters.mode=el.dataset.rMode;saveRoulette();render();}));
  root.querySelectorAll('[data-r-input]').forEach(el=>el.addEventListener('input',()=>{r.filters[el.dataset.rInput]=el.value===''?null:Number(el.value);if(el.dataset.rInput==='min_rating')r.filters.min_rating ||=0;saveRoulette();}));
  root.querySelectorAll('[data-r-genre]').forEach(el=>el.addEventListener('click',()=>{const list=r.filters[el.dataset.rGenre],g=el.dataset.rValue;r.filters[el.dataset.rGenre]=list.includes(g)?list.filter(x=>x!==g):[...list,g];saveRoulette();render();}));
  root.querySelector('[data-r-watched]')?.addEventListener('change',e=>{r.filters.exclude_watched=e.target.checked;saveRoulette();});
  root.querySelectorAll('[data-r-launch]').forEach(el=>el.addEventListener('click',spinRoulette));
  root.querySelector('[data-r-accept]')?.addEventListener('click',()=>selectCatalogMovie(r.movie.id));
  root.querySelectorAll('[data-r-action]').forEach(el=>el.addEventListener('click',()=>rouletteAction(el.dataset.rAction)));
}

// Hard rules share the server's evening across modes and connected devices.
const exclusionLabels = {movie:'Фильм',genre:'Жанр',keyword:'Тема',director:'Режиссёр',max_runtime:'Длительность',watched:'Просмотренное'};
function exIcon(name) {
  const paths={moon:'M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z',ban:'M8 8l8 8M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',plus:'M12 5v14M5 12h14',check:'m5 12 4 4L19 6',close:'m6 6 12 12M6 18 18 6',search:'m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z',clock:'M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',eye:'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm10-3a3 3 0 1 0 0 6 3 3 0 0 0 0-6',chevron:'m8 10 4 4 4-4',film:'M4 3h16v18H4zM4 8h16M4 16h16M8 3v18M16 3v18',spark:'m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z'};
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name] || paths.ban}"/></svg>`;
}
function exclusionData() {
  return state.exclusions?.user===state.user && state.exclusionsFor===state.session?.id ? state.exclusions : null;
}
function ruleLabel(rule) {
  if(rule.kind==='max_runtime')return `До ${rule.value} минут`;
  if(rule.kind==='watched')return 'Без просмотренного';
  return rule.title || rule.value;
}
function exTodayLabel(rule) {
  if(rule.kind==='genre')return rule.value==='хоррор'?'Без ужасов':rule.value==='драма'?'Без драм':`Без «${rule.value}»`;
  if(rule.kind==='keyword')return `Без темы «${rule.value}»`;
  if(rule.kind==='movie')return `Без «${rule.title || rule.value}»`;
  if(rule.kind==='director')return `Без фильмов: ${rule.value}`;
  return ruleLabel(rule);
}
function exDraft(scope) {
  state.exclusionDraft ||= {};
  return state.exclusionDraft[scope] ||= {kind:'genre',value:'',open:false};
}
function exSuggestions(scope) {
  const data=exclusionData(),draft=exDraft(scope),kind=draft.kind,rules=data?.[scope] || [];
  const chosen=value=>rules.some(r=>r.kind===kind&&r.value===value);
  const button=(value,label,subtitle='')=>`<button type="button" class="ex-pick ${chosen(value)?'is-chosen':''}" data-ex-pick="${esc(value)}" data-ex-kind-value="${kind}" aria-pressed="${chosen(value)}" ${state.exclusionBusy?'disabled':''}><span>${esc(label)}${subtitle?`<small>${esc(subtitle)}</small>`:''}</span>${exIcon(chosen(value)?'check':'plus')}</button>`;
  if(kind==='movie')return draft.results?draft.results.length?draft.results.map(m=>button(m.id,m.title,String(m.year))).join(''):'<p class="ex-note">Ничего не нашли. Попробуйте другое название.</p>':'<p class="ex-note">Найдите фильм по названию — он останется доступен в каталоге.</p>';
  if(kind==='max_runtime')return `<div class="ex-time-presets">${['90','120','150','180'].map(v=>button(v,`До ${v} мин`)).join('')}</div><form data-ex-time="${scope}" class="ex-custom-time"><label>Свой лимит, мин<input type="number" min="1" max="1440" required placeholder="Например, 100"></label><button class="button secondary" ${state.exclusionBusy?'disabled':''}>Применить</button></form>`;
  if(kind==='watched')return button('true','Без просмотренного','По вашей истории и отметкам «Уже смотрел»');
  const query=draft.value.trim().toLocaleLowerCase('ru');
  const choices=(data?.options[kind] || []).filter(v=>v.toLocaleLowerCase('ru').includes(query));
  return choices.length?choices.slice(0,kind==='genre'?40:16).map(v=>button(v,v)).join(''):'<p class="ex-note">Такой характеристики в каталоге пока нет.</p>';
}
function exclusionEditor(scope) {
  const data=exclusionData();if(!data)return '<p class="ex-note" role="status">Загружаем исключения…</p>';
  const allRules=data[scope] || [],draft=exDraft(scope),kind=draft.kind;
  const quickRule=r=>(r.kind==='genre'&&['хоррор','драма'].includes(r.value))||(r.kind==='max_runtime'&&r.value==='120')||r.kind==='watched';
  const rules=scope==='temporary'?allRules.filter(r=>!quickRule(r)):allRules;
  const tabs=[['genre','Жанры'],['movie','Фильмы'],['keyword','Темы'],['other','Ещё']];
  const other=['director','max_runtime','watched'].includes(kind);
  return `<div class="ex-rule-list">${rules.length?rules.map((r,i)=>`<div class="ex-rule ${r.kind==='movie'?'ex-rule-film':''}"><span class="ex-rule-symbol">${exIcon(r.kind==='movie'?'film':r.kind==='max_runtime'?'clock':r.kind==='watched'?'eye':'ban')}</span><span class="ex-rule-copy"><strong>${esc(ruleLabel(r))}</strong><small>${exclusionLabels[r.kind]}</small></span><button class="ex-remove" data-ex-remove="${allRules.indexOf(r)}" data-ex-scope="${scope}" aria-label="Убрать: ${esc(ruleLabel(r))}" ${state.exclusionBusy?'disabled':''}>${exIcon('close')}</button></div>`).join(''):scope==='permanent'?`<div class="ex-empty"><span>${exIcon('spark')}</span><div><strong>Пока открыты всему</strong><p>Добавьте то, что не хотите видеть в рекомендациях.</p></div></div>`:''}</div>
  ${draft.open?`<div class="ex-composer" data-ex-composer="${scope}"><div class="ex-composer-head"><strong>${scope==='permanent'?'Что больше не предлагать?':'Что исключим на этот вечер?'}</strong><button class="ex-remove" data-ex-composer-close="${scope}" aria-label="Закрыть добавление">${exIcon('close')}</button></div><div class="ex-tabs" role="group" aria-label="Вид исключения">${tabs.map(([k,label])=>`<button class="ex-tab ${k===kind||k==='other'&&other?'active':''}" data-ex-category="${k}" data-ex-scope="${scope}" aria-pressed="${k===kind||k==='other'&&other}">${label}</button>`).join('')}</div>
  ${other?`<div class="ex-subtabs">${[['director','Режиссёр'],['max_runtime','Длительность'],['watched','Просмотренное']].map(([k,label])=>`<button class="ex-tab ${kind===k?'active':''}" data-ex-category="${k}" data-ex-scope="${scope}">${label}</button>`).join('')}</div>`:''}
  ${!['max_runtime','watched'].includes(kind)?`<form data-ex-search="${scope}" class="ex-search">${exIcon('search')}<input data-ex-query="${scope}" value="${esc(draft.value)}" aria-label="${kind==='movie'?'Название фильма':kind==='genre'?'Найти жанр':kind==='keyword'?'Найти тему':'Найти режиссёра'}" placeholder="${kind==='movie'?'Название фильма…':kind==='genre'?'Найти жанр…':kind==='keyword'?'Например, космос…':'Имя режиссёра…'}" autocomplete="off" maxlength="200">${kind==='movie'?'<button type="submit" class="button small secondary">Найти</button>':''}</form>`:''}
  <div class="ex-suggestions ${kind==='genre'?'ex-genre-picks':''}" data-ex-suggestions="${scope}">${exSuggestions(scope)}</div>${kind==='keyword'?'<p class="ex-note">Темы берём из каталога; они могут быть указаны на английском.</p>':''}</div>`:`<button class="ex-add" data-ex-composer-open="${scope}">${exIcon('plus')} ${scope==='permanent'?'Добавить исключение':'Другие ограничения'}</button>`}
  ${allRules.length?`<div class="ex-list-footer"><span>${scope==='permanent'?'Действуют во всех следующих подборах':'Только до конца этого вечера'}</span><button class="ex-text-button" data-ex-clear="${scope}" ${state.exclusionBusy?'disabled':''}>${scope==='temporary'?'Снять все':'Очистить список'}</button></div>`:''}`;
}
function temporaryExclusions() {
  if(!state.user)return '';
  const data=exclusionData(),rules=data?.temporary || [];
  const quick=[['genre','хоррор','Без ужасов','Спокойнее сегодня','moon'],['genre','драма','Без драм','Хочется полегче','spark'],['max_runtime','120','До двух часов','Без долгого кино','clock'],['watched','true','Только новое','Без просмотренного','eye']];
  return `<details class="ex-today" data-disclosure-key="today-exclusions"><summary><span class="ex-today-icon">${exIcon('moon')}</span><span class="ex-today-heading"><strong>Не хочу сегодня</strong><small>${rules.length?rules.slice(0,2).map(exTodayLabel).map(esc).join(' · ')+(rules.length>2?' и ещё…':''):'Настройте подбор под этот вечер'}</small></span><span class="ex-count ${rules.length?'has-rules':''}">${rules.length || 'Без ограничений'}</span><span class="ex-chevron">${exIcon('chevron')}</span></summary><div class="ex-today-body"><div class="ex-today-intro"><p>Сегодня — по вашему настроению</p><span>Вкус Tonight IQ не изменится</span></div>
  ${state.exclusionError?`<p class="ex-error" role="alert">${esc(state.exclusionError)}</p><button class="ex-text-button" data-ex-retry>Попробовать снова</button>`:''}
  ${data?.session_id?`<div class="ex-quick-grid">${quick.map(([kind,value,label,hint,icon])=>{const active=rules.some(r=>r.kind===kind&&r.value===value);return `<button class="ex-quick ${active?'selected':''}" data-ex-quick="${kind}" data-ex-value="${value}" aria-pressed="${active}" ${state.exclusionBusy?'disabled':''}><span class="ex-quick-icon">${exIcon(icon)}</span><span><strong>${label}</strong><small>${hint}</small></span><span class="ex-check">${exIcon('check')}</span></button>`;}).join('')}</div>${exclusionEditor('temporary')}<p class="ex-expiry">${exIcon('clock')} До конца вечера или полуночи. Вдвоём учитываются ограничения обоих.</p>`:data?`<div class="ex-empty"><span>${exIcon('moon')}</span><div><strong>Новый вечер — новое настроение</strong><p>Начните новый подбор, чтобы включить временные исключения.</p></div></div><button class="button secondary" data-ex-new>Начать новый вечер</button>`:'<p class="ex-note" role="status">Загружаем настройки вечера…</p>'}
  <div class="ex-today-footer"><span>Есть то, что не любите вообще?</span><button class="ex-text-button" data-view="taste">Не рекомендовать ${exIcon('plus')}</button></div></div></details>`;
}
function exclusionEmptyHelp() {
  const data=exclusionData();if(!data || !data.permanent.length&&!data.temporary.length)return '';
  const active=[...data.permanent.map(r=>ruleLabel(r)),...data.temporary.map(exTodayLabel)];
  return `<div class="ex-empty-help"><p>Сейчас исключено: <strong>${active.slice(0,4).map(esc).join(' · ')}${active.length>4?' и ещё…':''}</strong></p><p>Правила сохранены. Можно изменить одно из них и попробовать снова.</p><div>${data.temporary.length?'<button class="ex-text-button" data-ex-edit-today>Изменить на сегодня</button>':''}${data.permanent.length?'<button class="ex-text-button" data-view="taste">Изменить постоянные</button>':''}</div></div>`;
}
function permanentExclusions() {
  const data=exclusionData();
  return `<section class="ex-permanent" aria-labelledby="ex-permanent-title"><div class="ex-section-heading"><span class="ex-permanent-icon">${exIcon('ban')}</span><div><p class="eyebrow">Ваш Tonight IQ</p><h2 id="ex-permanent-title">Не рекомендовать <span class="ex-count">${data?.permanent.length || 0}</span></h2></div><span class="ex-scope-badge">Постоянно</span></div><p class="ex-description">То, что вы не хотите смотреть вообще. Сохраним для следующих вечеров — ваши оценки останутся прежними.</p>
  ${state.exclusionError?`<p class="ex-error" role="alert">${esc(state.exclusionError)}</p><button class="ex-text-button" data-ex-retry>Попробовать снова</button>`:''}${exclusionEditor('permanent')}
  <details class="ex-help"><summary>Как это работает</summary><p>Действует для выбранного зрителя во всех автоматических подборах и на подключённых устройствах. Вдвоём объединяем ограничения обоих. Фильм всегда можно найти и выбрать в каталоге.</p><p>Если нужная характеристика неизвестна, фильм не предлагаем. «Без драм» исключает весь жанр: надёжных данных о тяжести сюжета нет.</p></details>
  <details class="ex-legacy"><summary>Ранее отмечено «Не интересно» <span>${data?.disinterest?.length || 0}</span></summary><p class="ex-note">Это ваши прежние сигналы IQ. Отмена вернёт фильм в подбор и уберёт этот сигнал. Оценки просмотров сохранятся.</p>${(data?.disinterest || []).map(m=>`<div class="ex-legacy-film"><span>${exIcon('film')} ${esc(m.title)}</span><button class="ex-text-button" data-ex-disinterest="${esc(m.movie_id)}">Вернуть в подбор</button></div>`).join('') || '<p class="ex-note">Таких отметок пока нет.</p>'}</details></section>`;
}

async function refreshExclusions() {
  const user=state.user,sid=state.session?.id;
  if(!user || state.exclusionsPending)return;
  let changed=false;
  state.exclusionsPending=true;state.exclusionError='';
  try {
    const data=await api(`/api/exclusions/${user}${sid?`?session_id=${sid}`:''}`);
    if(state.user!==user||state.session?.id!==sid)return;
    const previous=state.exclusions;
    state.exclusions=data;state.exclusionsFor=sid;state.exclusionsAt=Date.now();
    changed=!previous || JSON.stringify(previous)!==JSON.stringify(data);
    // The first response describes rules the server already applied to the
    // concurrent deck. It is a baseline, not a change invalidating that deck.
    if(changed && previous && previous.user===user)invalidateExclusionResults();
  }catch(e){state.exclusionError=e.message;}
  finally {state.exclusionsPending=false;if(state.user===user){if(changed || state.exclusionError)render();if(changed && state.view==='tinder' && state.tinder?.user===user && !state.tinder.loaded && !state.tinder.busy && !state.tinder.error)fetchTinder();}else if(state.user)refreshExclusions();}
}
function invalidateExclusionResults() {
  state.personal=null;state.personalAt=0;state.personalRevision++;
  state.tonightRequest++;state.tinderRequest++;state.rouletteRequest++;
  if(state.tonight){state.tonight.busy=false;state.tonight.data=null;state.tonight.detail=null;state.tonight.step=Math.min(3,state.tonight.step);saveTonight();}
  if(state.tinder){const queued=new Set(state.tinder.queue.map(movie=>movie.id));state.tinder.seen=state.tinder.seen.filter(id=>!queued.has(id));state.tinder.queue=[];state.tinder.busy=false;state.tinder.loaded=false;state.tinder.detail=false;saveTinder();}
  if(state.roulette){clearTimeout(state.roulette.timer);state.roulette.movie=null;state.roulette.busy=false;state.roulette.spinning=false;state.roulette.accepted=null;state.roulette.acceptedTitle=null;state.roulette.empty=false;saveRoulette();}
}
async function exclusionsChanged() {
  invalidateExclusionResults();
  await refreshExclusions();
  if(state.view==='tonight'&&state.tonight?.filters.mood&&state.tonight?.filters.company)await fetchTonight(true);
  else if(state.view==='tinder'&&state.tinder)await fetchTinder();
  else if(state.view==='weekly'){state.weeklyPicks=(await api('/api/weekly-picks')).items;render();}
}
async function mutateExclusion(scope, rule, remove=false, clear=false) {
  if(state.exclusionBusy)return;
  if(clear&&scope==='permanent'&&!window.confirm('Очистить постоянные исключения? Оценки и отметки «Не интересно» останутся.'))return;
  const user=state.user,sid=state.session?.id;state.exclusionBusy=true;
  try {
    let data;
    if(remove||clear){
      const query=new URLSearchParams({scope,session_id:String(sid),...(clear?{clear:'true',confirmed:'true'}:rule)});
      data=await api(`/api/exclusions/${user}?${query}`,{method:'DELETE'});
    } else data=await api(`/api/exclusions/${user}`,{method:'POST',body:JSON.stringify({...rule,scope,session_id:sid})});
    if(state.user!==user)return;
    state.exclusions=data;state.exclusionsFor=sid;state.exclusionsAt=Date.now();
    await exclusionsChanged();
    if(state.view==='results')state.session=await api(`/api/sessions/${sid}`);
  }catch(e){toast(e.message);}
  finally{state.exclusionBusy=false;render();}
}
function bindExclusions() {
  root.querySelectorAll('[data-ex-edit-today]').forEach(el=>el.addEventListener('click',()=>{const panel=root.querySelector('.ex-today');if(panel){panel.open=true;panel.scrollIntoView({block:'start',behavior:'smooth'});panel.querySelector('summary').focus({preventScroll:true});}}));
  const redrawComposer=()=>{render();root.querySelector('[data-ex-query]')?.focus({preventScroll:true});};
  root.querySelectorAll('[data-ex-composer-open]').forEach(el=>el.addEventListener('click',()=>{exDraft(el.dataset.exComposerOpen).open=true;redrawComposer();}));
  root.querySelectorAll('[data-ex-composer-close]').forEach(el=>el.addEventListener('click',()=>{exDraft(el.dataset.exComposerClose).open=false;render();}));
  root.querySelectorAll('[data-ex-category]').forEach(el=>el.addEventListener('click',()=>{const draft=exDraft(el.dataset.exScope);draft.kind=el.dataset.exCategory==='other'?'director':el.dataset.exCategory;draft.value='';draft.results=null;redrawComposer();}));
  const findMovies=async scope=>{
    const draft=exDraft(scope),query=draft.value.trim(),user=state.user;
    if(!query){draft.results=null;return;}
    try{
      const result=await api(`/api/movies/search?q=${encodeURIComponent(query)}`);
      if(state.user!==user || draft!==exDraft(scope) || draft.value.trim()!==query || draft.kind!=='movie')return;
      draft.results=result.items.slice(0,12);
      const list=root.querySelector(`[data-ex-suggestions="${scope}"]`);if(list)list.innerHTML=exSuggestions(scope);
    }catch(e){toast(e.message);}
  };
  root.querySelectorAll('[data-ex-query]').forEach(el=>el.addEventListener('input',()=>{
    const scope=el.dataset.exQuery,draft=exDraft(scope);draft.value=el.value;
    if(draft.kind==='movie'){
      clearTimeout(bindExclusions.searchTimer);bindExclusions.searchTimer=setTimeout(()=>findMovies(scope),250);
    }else{const list=root.querySelector(`[data-ex-suggestions="${scope}"]`);if(list)list.innerHTML=exSuggestions(scope);}
  }));
  root.querySelectorAll('[data-ex-search]').forEach(form=>form.addEventListener('submit',e=>{e.preventDefault();if(exDraft(form.dataset.exSearch).kind==='movie')findMovies(form.dataset.exSearch);}));
  root.querySelectorAll('[data-ex-composer]').forEach(composer=>composer.addEventListener('click',e=>{
    const el=e.target.closest('[data-ex-pick]');if(!el)return;
    const scope=composer.dataset.exComposer,rule={kind:el.dataset.exKindValue,value:el.dataset.exPick};
    const active=exclusionData()?.[scope].some(r=>r.kind===rule.kind&&r.value===rule.value);
    mutateExclusion(scope,rule,active);
  }));
  root.querySelectorAll('[data-ex-time]').forEach(form=>form.addEventListener('submit',e=>{e.preventDefault();mutateExclusion(form.dataset.exTime,{kind:'max_runtime',value:form.querySelector('input').value});}));
  root.querySelectorAll('[data-ex-remove]').forEach(el=>el.addEventListener('click',()=>{const scope=el.dataset.exScope,r=exclusionData()?.[scope][Number(el.dataset.exRemove)];if(r)mutateExclusion(scope,{kind:r.kind,value:r.value},true);}));
  root.querySelectorAll('[data-ex-clear]').forEach(el=>el.addEventListener('click',()=>mutateExclusion(el.dataset.exClear,null,false,true)));
  root.querySelectorAll('[data-ex-quick]').forEach(el=>el.addEventListener('click',()=>{const rule={kind:el.dataset.exQuick,value:el.dataset.exValue},active=exclusionData()?.temporary.some(r=>r.kind===rule.kind&&r.value===rule.value);mutateExclusion('temporary',rule,active);}));
  root.querySelectorAll('[data-ex-retry]').forEach(el=>el.addEventListener('click',refreshExclusions));
  root.querySelector('[data-ex-new]')?.addEventListener('click',async()=>{try{state.session=await api(`/api/sessions/${state.session.id}/restart`,{method:'POST'});await api(`/api/sessions/${state.session.id}/join`,{method:'POST',body:joinBody(state.user)});connectWs();await exclusionsChanged();}catch(e){toast(e.message);}});
  root.querySelectorAll('[data-ex-disinterest]').forEach(el=>el.addEventListener('click',async()=>{try{await api(`/api/exclusions/${state.user}/disinterest/${encodeURIComponent(el.dataset.exDisinterest)}`,{method:'DELETE'});await exclusionsChanged();}catch(e){toast(e.message);}}));
}

// Isolated search state; all taste signals and saved actions use existing APIs.
const genreOptions = ['хоррор','романтика','комедия','драма','боевик','sci-fi','фэнтези','детектив','триллер','мультфильм','мюзикл','документальное','приключения','криминал','семейный','история','музыка','военный','вестерн'];
const themeOptions = {space:'Космос',time:'Путешествия во времени',robots:'Роботы',friendship:'Дружба',love:'Любовь',twists:'Неожиданные повороты',light:'Лёгкое настроение (по тегам)',tense:'Напряжение (по тегам)',funny:'Юмор (по тегам)'};
const numericFields = {min_runtime:['Длительность от, мин',1,1440,1],max_runtime:['Длительность до, мин',1,1440,1],min_year:['Год от',1888,2100,1],max_year:['Год до',1888,2100,1],min_rating:['Рейтинг от, из 10',0,10,.1]};
const examples = ['Детектив без ужасов до двух часов','Комедию после 2015 года с хорошим рейтингом','Похожее на Интерстеллар, но попроще','Фантастику про космос, которую я ещё не смотрел'];

function createSmartSearch({state,root,api,render,esc,poster,tonightRating,tonightSynopsis,toast}) {
  let owner = null, s, sequence = 0, controller = null;
  function persist() {
    if(!s||!owner)return;
    try {sessionStorage.setItem(`tonight:search:${owner}`,JSON.stringify({query:s.query,refinement:s.refinement,data:s.data,mode:s.mode}));}catch(_){}
  }
  function cancel() { sequence++; controller?.abort(); controller=null; if(s)s.pending=false; }
  function current() {
    if (owner !== state.user || !s) {
      cancel(); owner=state.user;
      s={query:'',refinement:'',data:null,editorDraft:null,pending:false,error:'',mode:'smart',saving:new Set()};
      try {const saved=JSON.parse(sessionStorage.getItem(`tonight:search:${owner}`));if(saved&&typeof saved.query==='string')Object.assign(s,saved,{pending:false,saving:new Set()});}catch(_){}
    }
    return s;
  }
  function entry() {
    const local=current();
    return `<section class="smart-entry" aria-labelledby="smart-entry-title"><div><p class="eyebrow">Умный поиск</p><h2 id="smart-entry-title">Опиши, что хочешь посмотреть</h2><p class="hint">Жанр, длительность или фильм для похожего — своими словами.</p></div>${queryForm(local,'home')}</section>`;
  }
  function queryForm(local,place='search') {
    return `<form data-smart-query class="smart-query"><label class="sr-only" for="smart-query-${place}">Опиши, что хочешь посмотреть</label><textarea id="smart-query-${place}" name="query" rows="2" maxlength="500" placeholder="Например: детектив без ужасов до двух часов" aria-describedby="smart-query-help-${place}">${esc(local.query)}</textarea><div class="smart-query-actions"><small class="hint" id="smart-query-help-${place}">До 500 символов</small><button type="button" class="button ghost" data-smart-clear>Очистить</button><button class="button" type="submit">${local.pending?'Ищем…':'Подобрать фильмы'}</button></div></form>`;
  }
  function chips(c) {
    const chip=(group,field,value,label,caption,display,icon='film')=>`<div class="smart-token ${field==='similar_title'||field==='themes'?'is-wide':''}"><button class="smart-token-edit" type="button" data-smart-edit-field="${field}" ${value==null?'':`data-smart-edit-value="${esc(value)}"`} aria-label="Изменить условие: ${esc(label)}">${exIcon(icon)}<span><small>${esc(caption)}</small><strong>${esc(display)}</strong></span></button><button class="smart-token-remove" type="button" data-smart-remove="${group}.${field}" ${value==null?'':`data-value="${esc(value)}"`} aria-label="Удалить условие: ${esc(label)}" title="Удалить условие">${exIcon('close')}</button></div>`;
    const genreName=v=>({'sci-fi':'Фантастика','хоррор':'Ужасы','документальное':'Документальный'}[v] || v[0].toUpperCase()+v.slice(1));
    const hard=[...c.hard.genres.map(v=>chip('hard','genres',v,`Жанр: ${v}`,'Жанр',genreName(v))),...c.hard.excluded_genres.map(v=>chip('hard','excluded_genres',v,`Без: ${v}`,'Исключить',genreName(v),'ban'))];
    const numericLabels={min_runtime:['Длительность',`От ${c.hard.min_runtime} мин`,'clock'],max_runtime:['Длительность',`До ${c.hard.max_runtime} мин`,'clock'],min_year:['Год выпуска',`От ${c.hard.min_year}`,'film'],max_year:['Год выпуска',`До ${c.hard.max_year}`,'film'],min_rating:['Рейтинг',`От ${c.hard.min_rating} / 10`,'spark']};
    for(const [k,[label]] of Object.entries(numericFields))if(c.hard[k]!=null)hard.push(chip('hard',k,null,`${label}: ${c.hard[k]}`,...numericLabels[k]));
    if(c.hard.exclude_watched)hard.push(chip('hard','exclude_watched',null,'Ещё не смотрел(а)','Просмотренное','Не смотрел(а)','eye'));
    const soft=c.soft.themes.map(v=>chip('soft','themes',v,`Тема: ${themeOptions[v]}`,'Пожелание',themeOptions[v],'spark'));
    if(c.soft.similar_title)soft.push(chip('soft','similar_title',null,`Похоже на: ${s.data?.source?.title || c.soft.similar_title}`,'Похоже на',s.data?.source?.title || c.soft.similar_title));
    return `<section class="smart-criteria" aria-labelledby="smart-criteria-title"><header class="smart-criteria-head"><div class="smart-criteria-heading"><span class="smart-criteria-symbol">${exIcon('check')}</span><div><h3 id="smart-criteria-title">Условия поиска <span class="smart-criteria-count">${hard.length+soft.length}</span></h3><p>Нажмите на условие, чтобы изменить</p></div></div><button type="button" class="smart-configure" data-smart-edit-toggle aria-expanded="${!!s.editorOpen}" aria-controls="smart-criteria-editor">${exIcon(s.editorOpen?'close':'plus')}<span>${s.editorOpen?'Закрыть':'Изменить'}</span></button></header>${hard.length?`<div class="smart-criteria-group"><p class="smart-group-label"><span></span>Обязательно${soft.length?'':' · все условия'}</p><div class="smart-tokens">${hard.join('')}</div></div>`:''}${soft.length?`<div class="smart-criteria-group is-soft"><p class="smart-group-label"><span></span>Желательно</p><div class="smart-tokens">${soft.join('')}</div></div>`:''}${!hard.length&&!soft.length?'<p class="smart-criteria-empty">Добавьте жанр, время или другое пожелание.</p>':''}${editor(c)}</section>`;
  }
  function editor(c) {
    c=s.editorDraft?.criteria || c;
    const replacing=s.editingToken?.field;
    const options=field=>genreOptions.map(g=>`<option value="${esc(g)}" ${s.editorDraft?.selects[field]===g?'selected':''}>${esc({'sci-fi':'Фантастика','хоррор':'Ужасы'}[g]||g[0].toUpperCase()+g.slice(1))}</option>`).join('');
    const number=(field,caption,unit)=>{const [label,min,max,step]=numericFields[field];return `<label class="smart-number"><span>${caption}</span><span class="smart-number-input"><input aria-label="${label}" name="${field}" type="number" min="${min}" max="${max}" step="${step}" inputmode="${step===1?'numeric':'decimal'}" value="${c.hard[field]??''}" placeholder="Любое"><span aria-hidden="true">${unit}</span></span></label>`;};
    return `<div id="smart-criteria-editor" class="smart-editor-panel" ${s.editorOpen?'':'hidden'}><form data-smart-edit><div class="smart-range-grid"><fieldset><legend>${exIcon('clock')}Длительность</legend><div class="smart-range">${number('min_runtime','От','мин')}${number('max_runtime','До','мин')}</div></fieldset><fieldset><legend>${exIcon('film')}Год выпуска</legend><div class="smart-range">${number('min_year','От','')}${number('max_year','До','')}</div></fieldset><fieldset><legend>${exIcon('spark')}Рейтинг</legend>${number('min_rating','Не ниже','/ 10')}</fieldset></div><div class="smart-editor-selects"><label>${replacing==='genres'?'Жанр':'Добавить жанр'}<select name="genre"><option value="">Выберите жанр</option>${options('genre')}</select></label><label>${replacing==='excluded_genres'?'Исключённый жанр':'Исключить жанр'}<select name="excluded_genre"><option value="">Выберите жанр</option>${options('excluded_genre')}</select></label><label>${replacing==='themes'?'Пожелание':'Добавить пожелание'}<select name="theme"><option value="">Выберите тему</option>${Object.entries(themeOptions).map(([v,label])=>`<option value="${v}" ${s.editorDraft?.selects.theme===v?'selected':''}>${label}</option>`).join('')}</select></label></div><label class="smart-source-input">Найти похожее на<input name="similar_title" aria-label="Похожее на фильм" maxlength="200" value="${esc(c.soft.similar_title||'')}" placeholder="Название фильма"></label><label class="smart-check"><input type="checkbox" name="exclude_watched" ${c.hard.exclude_watched?'checked':''}><span>Только то, что я ещё не смотрел(а)<small>По истории и вашим отметкам просмотра</small></span></label><footer class="smart-editor-footer"><button class="smart-configure" type="button" data-smart-edit-close>Отмена</button><button class="button" type="submit">Применить условия</button></footer></form></div>`;
  }
  function content() {
    const local=current(), data=local.data;
    if(local.mode==='title')return '';
    return `<section class="smart-search" aria-labelledby="smart-title"><div class="screen-head"><p class="eyebrow">Умный поиск</p><h2 id="smart-title">Опиши, что хочешь посмотреть</h2><p class="lede">Tonight учитывает понятные условия и ваш вкус. Нераспознанные пожелания покажем отдельно.</p></div>${queryForm(local)}<details class="smart-examples-disclosure" data-render-state ${data?'':'open'}><summary>Примеры запросов${exIcon('chevron')}</summary><div class="smart-examples" aria-label="Примеры запросов">${examples.map((q,i)=>`<button class="button ghost small" type="button" data-smart-example="${i}">${esc(q)}</button>`).join('')}</div></details><div data-smart-status role="status" aria-live="polite">${local.pending?'Разбираем запрос и ищем в локальном каталоге…':''}</div>${local.error?`<p class="smart-error" role="alert">${esc(local.error)}</p>`:''}${data?`<div class="smart-response" aria-busy="${local.pending}">${chips(data.criteria)}${data.notes.length?`<aside class="smart-notes"><h3>Что учли не полностью</h3><ul>${data.notes.map(note=>`<li>${esc(note)}</li>`).join('')}</ul></aside>`:''}${data.conflicts.length?`<div class="smart-error" role="alert">${data.conflicts.map(esc).join(' ')}</div>`:''}${data.needs_source?`<section class="smart-source"><h3>Какой фильм вы имеете в виду?</h3><div class="smart-chips">${data.sources.map(m=>`<button class="button secondary" data-smart-source="${esc(m.id)}">${esc(m.title)} · ${m.year}${m.original_title?` · ${esc(m.original_title)}`:''}</button>`).join('')}</div></section>`:''}${!data.needs_source&&!data.conflicts.length?results(data):''}<form data-smart-refine class="smart-refine"><label for="smart-refinement">Уточнить текущие условия</label><div class="search-form"><input id="smart-refinement" name="refinement" value="${esc(local.refinement)}" maxlength="500" placeholder="Например: только после 2020 года"><button class="button secondary" type="submit">Уточнить</button></div><p class="hint">Новые значения заменяют соответствующие условия. Остальные сохраняются.</p></form></div>`:''}</section>`;
  }
  function results(data) {
    const policy=data.policies;
    return `<section class="smart-results" aria-labelledby="smart-results-title"><h3 id="smart-results-title">${data.items.length?`Показаны ${data.items.length} из ${data.total}`:'Подходящих фильмов нет'}</h3>${policy?`<p class="hint">${data.cold_start?'Подобрано по вашему запросу.':'С учётом вашего вкуса Tonight IQ.'}${policy.permanent||policy.temporary||policy.evening?' Сохранённые ограничения также учтены.':''}</p>`:''}${data.items.length?`<div class="smart-film-grid">${data.items.map(m=>`<article class="smart-film"><div class="smart-film-heading"><button class="smart-poster" data-smart-detail="${esc(m.id)}" aria-label="Подробнее: ${esc(m.title)}">${poster(m)}</button><div><p class="eyebrow">${tonightRating(m)}</p><h3><button class="tonight-title" data-smart-detail="${esc(m.id)}">${esc(m.title)}</button></h3><p class="hint">${m.year||'Год не указан'} · ${m.runtime?`${m.runtime} мин`:'Длительность не указана'}</p><p class="hint">${esc((m.genres||[]).join(' · '))}</p></div></div><div class="smart-film-body"><p>${esc(tonightSynopsis(m))}</p><details class="smart-reasons"><summary>Почему подходит</summary><ul>${m.search_reasons.map(reason=>`<li>${esc(reason)}</li>`).join('')}</ul><p class="hint">${esc(m.recommendation_reason)}</p></details><div class="smart-film-actions"><button class="button" data-smart-select="${esc(m.id)}">Выбрать на сегодня</button><button class="button ghost" data-smart-detail="${esc(m.id)}">Подробнее</button>${trailerButton(m)}<button class="button secondary" data-smart-save="${esc(m.id)}" ${m.saved||s.saving.has(m.id)?'disabled':''}>${m.saved?'✓ В списке «На потом»':s.saving.has(m.id)?'Сохраняем…':'♡ Сохранить на потом'}</button></div></div></article>`).join('')}</div>${data.items.length<data.total?`<button class="button secondary search-more" data-smart-more ${s.pending?'disabled':''}>${s.pending?'Загружаем…':'Показать ещё 12'}</button>`:''}`:`<div class="empty"><p>Можно удалить отдельное условие кнопкой × или изменить значения выше. Ограничения автоматически не ослабляются.</p>${data.diagnostics.length?`<ul>${data.diagnostics.map(d=>`<li>${esc(d.label)}: исключает ${d.excluded} из ${data.catalog_count} фильмов каталога.</li>`).join('')}</ul>`:''}</div>`}</section>`;
  }
  function tabs() {
    const local=current();
    return `<div class="smart-tabs" role="group" aria-label="Способ поиска"><button class="button ${local.mode==='smart'?'':'secondary'}" data-search-mode="smart" aria-pressed="${local.mode==='smart'}">По описанию</button><button class="button ${local.mode==='title'?'':'secondary'}" data-search-mode="title" aria-pressed="${local.mode==='title'}">По названию</button></div>`;
  }
  async function run({criteria=null,refine=false,query=null,more=false}={}) {
    const local=current(), user=owner;
    cancel(); const revision=sequence;
    controller=new AbortController();
    local.pending=true; local.error='';
    if(!criteria&&!more)local.data=null;
    else if(local.data)local.data.criteria=criteria;
    local.editorDraft=null;
    local.editorOpen=false;local.editingToken=null;
    state.view='search'; render();
    try {
      const data=await api(`/api/search/smart/${encodeURIComponent(user)}`,{method:'POST',signal:controller.signal,body:JSON.stringify({query:query??local.query,criteria,refine,offset:more?(local.data?.items.length||0):0})});
      if(revision!==sequence||state.user!==user)return;
      if(refine&&local.data)data.notes=[...new Set([...local.data.notes,...data.notes])];
      if(more&&local.data)data.items=[...local.data.items,...data.items].filter((m,i,all)=>all.findIndex(x=>x.id===m.id)===i);
      local.data=data;
      if(refine)local.refinement='';
    } catch(e) {
      if(revision!==sequence||e.name==='AbortError')return;
      local.error=e.message;
    } finally {
      if(revision===sequence){local.pending=false;controller=null;persist();if(state.view==='search')render();}
    }
  }
  function cloneCriteria() { return JSON.parse(JSON.stringify(s.data.criteria)); }
  function bind() {
    const local=current();
    function openEditor(field,value) {
      const names={genres:'genre',excluded_genres:'excluded_genre',themes:'theme'};
      local.editingToken=value?{field,value}:null;
      if(value)local.editorDraft={criteria:cloneCriteria(),selects:{[names[field]]:value}};
      local.editorOpen=true;render();
      const target=field?root.querySelector(`[data-smart-edit] [name="${names[field]||field}"]`):null;
      target?.focus();
    }
    root.querySelector('[data-smart-edit-toggle]')?.addEventListener('click',()=>{if(local.editorOpen){local.editorOpen=false;local.editingToken=null;local.editorDraft=null;render();}else openEditor();});
    root.querySelector('[data-smart-edit-close]')?.addEventListener('click',()=>{local.editorOpen=false;local.editingToken=null;local.editorDraft=null;render();root.querySelector('[data-smart-edit-toggle]')?.focus();});
    root.querySelectorAll('[data-smart-edit-field]').forEach(el=>el.addEventListener('click',()=>openEditor(el.dataset.smartEditField,el.dataset.smartEditValue)));
    root.querySelector('[data-smart-edit]')?.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();local.editorOpen=false;local.editingToken=null;local.editorDraft=null;render();root.querySelector('[data-smart-edit-toggle]')?.focus();}});
    root.querySelectorAll('[data-search-mode]').forEach(el=>el.addEventListener('click',()=>{cancel();local.mode=el.dataset.searchMode;render();}));
    root.querySelector('[data-smart-query] textarea')?.addEventListener('input',e=>{
      local.query=e.target.value;
      persist();
      if(local.pending){cancel();root.querySelector('[data-smart-status]').textContent='Запрос изменён. Нажмите «Подобрать фильмы».';root.querySelector('[data-smart-query] button[type="submit"]').textContent='Подобрать фильмы';}
    });
    root.querySelector('[data-smart-query]')?.addEventListener('submit',e=>{e.preventDefault();local.query=new FormData(e.currentTarget).get('query').trim();local.mode='smart';run();});
    root.querySelector('[data-smart-clear]')?.addEventListener('click',()=>{cancel();local.query='';local.refinement='';local.data=null;local.editorDraft=null;local.error='';persist();render();root.querySelector('[data-smart-query] textarea')?.focus();});
    root.querySelectorAll('[data-smart-example]').forEach(el=>el.addEventListener('click',()=>{local.query=examples[Number(el.dataset.smartExample)];run();}));
    root.querySelectorAll('[data-smart-remove]').forEach(el=>el.addEventListener('click',()=>{
      const c=cloneCriteria(), [group,field]=el.dataset.smartRemove.split('.');
      if(Array.isArray(c[group][field]))c[group][field]=c[group][field].filter(v=>v!==el.dataset.value);
      else c[group][field]=field==='exclude_watched'?false:null;
      if(field==='similar_title')c.soft.source_id=null;
      run({criteria:c});
    }));
    root.querySelectorAll('[data-smart-source]').forEach(el=>el.addEventListener('click',()=>{const c=cloneCriteria();c.soft.source_id=el.dataset.smartSource;run({criteria:c});}));
    const editForm=root.querySelector('[data-smart-edit]');
    function editedCriteria() {
      const form=new FormData(editForm),c=cloneCriteria();
      for(const k of Object.keys(numericFields))c.hard[k]=form.get(k)===''?null:Number(form.get(k));
      for(const [input,group,field] of [['genre','hard','genres'],['excluded_genre','hard','excluded_genres'],['theme','soft','themes']]){
        if(local.editingToken?.field===field)c[group][field]=c[group][field].filter(v=>v!==local.editingToken.value);
        const value=form.get(input);if(value&&!c[group][field].includes(value))c[group][field].push(value);
      }
      c.hard.exclude_watched=form.has('exclude_watched');
      const title=form.get('similar_title').trim()||null;
      if(title!==c.soft.similar_title)c.soft.source_id=null;
      c.soft.similar_title=title;return c;
    }
    function preserveEdit(){const form=new FormData(editForm);local.editorDraft={criteria:editedCriteria(),selects:{genre:form.get('genre'),excluded_genre:form.get('excluded_genre'),theme:form.get('theme')}};}
    editForm?.addEventListener('input',preserveEdit);
    editForm?.addEventListener('change',preserveEdit);
    editForm?.addEventListener('submit',e=>{e.preventDefault();run({criteria:editedCriteria()});});
    root.querySelector('[data-smart-refine] input')?.addEventListener('input',e=>{local.refinement=e.target.value;});
    root.querySelector('[data-smart-refine]')?.addEventListener('submit',e=>{e.preventDefault();const query=new FormData(e.currentTarget).get('refinement').trim();if(query)run({criteria:cloneCriteria(),refine:true,query});});
    root.querySelector('[data-smart-more]')?.addEventListener('click',()=>run({criteria:cloneCriteria(),more:true}));
    root.querySelectorAll('[data-smart-select]').forEach(el=>el.addEventListener('click',()=>selectCatalogMovie(el.dataset.smartSelect)));
    root.querySelectorAll('[data-smart-detail]').forEach(el=>el.addEventListener('click',()=>{state.modal=local.data.items.find(m=>m.id===el.dataset.smartDetail);renderModal();}));
    root.querySelectorAll('[data-smart-save]').forEach(el=>el.addEventListener('click',async()=>{
      const user=owner,id=el.dataset.smartSave;local.saving.add(id);render();
      try{await api(`/api/tonight/${encodeURIComponent(user)}/movies/${encodeURIComponent(id)}`,{method:'POST',body:JSON.stringify({action:'watchlist'})});const movie=local.data?.items.find(m=>m.id===id);if(movie)movie.saved=true;toast('Добавлено в общий список «На потом»');}
      catch(e){if(state.user===user)local.error=e.message;}
      finally{local.saving.delete(id);if(state.user===user){persist();if(state.view==='search')render();}}
    }));
  }
  return {entry,content,tabs,bind,cancel,persist,reset:()=>{cancel();owner=null;s=null;},open:()=>{cancel();current().mode='smart';state.view='search';render();},isTitle:()=>current().mode==='title'};
}


const smartSearch=createSmartSearch({state,root,api,render,esc,poster,tonightRating,tonightSynopsis,toast});
init();
