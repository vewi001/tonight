const root = document.querySelector('#app');
const toastNode = document.querySelector('#toast');

const state = {
  user: localStorage.getItem('tonight:user'),
  accessCode: sessionStorage.getItem('tonight:access-code') || '',
  session: null,
  roulette: null, rouletteRequest: 0, tonight: null, tonightRequest: 0, tinder: null, tinderRequest: 0,
  personal: null, personalUser: null, personalAt: 0, personalPending: false, personalError: '', personalRevision: 0,
  setup: null,
  catalog: null, catalogTimer: null, catalogError: '', catalogRequest: 0,
  expansion: null, expansionTimer: null, expansionPending: false, expansionCount: 50,
  invite: null,
  update: null, updateTimer: null, updateDismissed: '', updateInstallingFrom: null,
  view: 'loading',
  searchDraft: null, navigationRequest: 0,
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
  ['love','❤️','Обожаю'],['like','👍','Нравится'],['okay','🤷','Норм'],['dislike','👎','Не хочу'],['unseen','❔','Не смотрел(а)'],
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

function poster(movie) {
  if(movie.poster_available===false || !movie.poster_url)return '<span class="poster-placeholder" role="img" aria-label="Постер отсутствует">Постер пока не загружен</span>';
  return `<img src="${esc(movie.poster_url)}" alt="Постер: ${esc(movie.title)}" loading="lazy" draggable="false" data-poster>`;
}
function bindPosters() {
  root.querySelectorAll('img[data-poster]').forEach(img=>{
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
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...eveningHeaders, ...(options.headers || {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = Array.isArray(body.detail) ? body.detail.map(item => item.msg).filter(Boolean).join('. ') : body.detail;
    throw new Error(detail || 'Что-то пошло не так');
  }
  if (options.method && options.method !== 'GET') { state.personalAt = 0; state.personalRevision++; }
  return response.json();
}

function toast(message) {
  toastNode.textContent = message;
  toastNode.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => toastNode.classList.remove('show'), 2600);
}

function shell(content, { narrow = false, nav = true } = {}) {
  const identity = state.user ? `<button class="icon-button identity-pill" data-action="switch-user" title="Сменить пользователя">${emojis[state.user]} <span>${names[state.user]}</span></button>` : '';
  const credits = state.setup?.tmdb_movies ? `<footer class="data-credits" aria-label="Источники данных"><a href="https://www.themoviedb.org/" target="_blank" rel="noopener noreferrer"><img src="/assets/tmdb.svg" alt="TMDB"></a><span>This product uses the TMDB API but is not endorsed or certified by TMDB.</span></footer>` : '';
  return `<div class="shell">
    ${nav ? `<header class="topbar"><button class="brand" data-view="home">Tonight <span>🍿</span></button>${identity}<button class="icon-button nav-toggle" data-action="toggle-nav" aria-expanded="${!!state.navOpen}" aria-controls="main-navigation">Разделы ${state.navOpen ? '−' : '+'}</button><nav id="main-navigation" class="top-actions ${state.navOpen ? 'is-open' : ''}" aria-label="Основная навигация">
      <button class="icon-button" data-view="history">◷ <span class="nav-label">История</span></button><button class="icon-button" data-view="weekly">✦ <span class="nav-label">Неделя</span></button><button class="icon-button" data-view="franchises">≡ <span class="nav-label">Серии</span></button><button class="icon-button" data-view="diagnostics">✓ <span class="nav-label">Проверить приложение</span></button><button class="icon-button" data-view="library">▤ <span class="nav-label">Каталог и обновления</span></button>
      <button class="icon-button" data-view="watchlist">♡ <span class="nav-label">На потом</span></button>
      <button class="icon-button" data-view="taste">♡ <span class="nav-label">Наш вкус</span></button><button class="icon-button" data-view="search">⌕ <span class="nav-label">Найти</span></button>
    </nav></header>` : ''}
    <div data-update-banner>${updateDialog() || ['diagnostics','catalog'].includes(state.view) ? '' : updateControls()}</div>
    <main id="main" class="page ${narrow ? 'narrow' : ''}">${content}${['diagnostics','catalog'].includes(state.view) ? `<div data-update-panel>${updateDialog() ? '' : updateControls(true)}</div>` : ''}</main>
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
    setup: renderSetup, home: renderHome, tonight: renderTonight, roulette: renderRoulette, tinder: renderTinder, vibe: renderVibe, filters: renderFilters,
    swipe: renderSwipe, waiting: renderWaiting, results: renderResults, quick: renderQuick,
    selected: renderSelected, watching:renderWatching, feedback: renderFeedback, eveningFeedback: renderEveningFeedback, history: renderHistory, weekly: renderWeekly, franchises: renderFranchises, diagnostics: renderDiagnostics,
    taste: renderTaste, watchlist: renderWatchlist, search: renderSearch, error: renderError, catalog: renderCatalog,
  };
  root.innerHTML = (views[state.view] || renderHome)();
  root.querySelectorAll('details').forEach(el=>{if(openDisclosures.has(el.dataset.disclosureKey || el.dataset.descriptionKey || el.querySelector('summary')?.textContent))el.open=true;});
  bindCommon();
  if (state.view === 'swipe') bindSwipeGestures();
  if (state.view === 'waiting') scheduleWaitingCheck();
  if (state.modal) renderModal();
  if (state.deferMovieId) renderDeferDialog();
  if (state.privacyDeleteOpen) renderPrivacyDeleteDialog();
  if (state.view === 'home' && state.user && !state.personalPending && Date.now() - state.personalAt > 30000) refreshPersonal();
  if (viewChanged) requestAnimationFrame(() => window.scrollTo(0, 0));
}

function renderSetup() {
  const o = state.setup?.ollama || {};
  return shell(`<section class="panel" style="margin-top:8vh">
    <p class="eyebrow">Первый запуск</p><h2>Добро пожаловать в Tonight 🍿</h2>
    <p class="lede">Проверим, что всё готово для выбора фильма.</p>
    <div class="setup-list">
      <div class="setup-row"><span>Каталог готов</span><strong class="ok">✓ ${state.setup?.catalog || 0} фильмов</strong></div>
      <div class="setup-row"><span>Постеры загружены</span><strong class="${state.setup?.posters ? 'ok':'warn'}">${state.setup?.posters ? `✓ ${state.setup.posters}`:'○ Постеры пока не загружены'}</strong></div>
      <div class="setup-row"><span>Можно выбирать фильм</span><strong class="ok">✓ Готово</strong></div>
    </div>
    <p class="lede">Всё готово к киновечеру 🍿</p>
    <details class="setup-help"><summary>Если что-то не работает</summary><div class="setup-list technical-list">
      <div class="setup-row"><span>Database</span><strong class="ok">✓ Готова</strong></div>
      <div class="setup-row"><span>Ollama</span><strong class="${o.available ? 'ok':'warn'}">${o.available ? '✓ Подключена':'○ Необязательна'}</strong></div>
      <div class="setup-row"><span>AI model</span><strong class="${o.model_installed ? 'ok':'warn'}">${o.model_installed ? `✓ ${esc(o.model)}`:'○ Работаем без неё'}</strong></div>
      <div class="setup-row"><span>Local network</span><strong class="ok">✓ Tonight доступен</strong></div>
    </div>${!o.model_installed ? `<p>Tonight работает и без Ollama. Для умных подсказок на этом компьютере:</p><div class="choice"><code>${esc(state.setup?.model_command || '')}</code></div>` : ''}${!state.setup?.posters ? `<p>Чтобы один раз загрузить настоящие постеры через TMDB:</p><div class="choice"><code>${esc(state.setup?.poster_command)}</code></div>` : ''}</details>
    <div class="footer-actions"><button class="button large" data-action="finish-setup">Продолжить</button></div>
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

function renderHome() {
  if (!state.user) {
    const accessCode = isRemoteClient() ? `<div class="panel" style="margin-bottom:1rem"><label for="access-code"><strong>Код с экрана Tonight</strong></label><input id="access-code" data-access-code inputmode="numeric" autocomplete="one-time-code" maxlength="6" value="${esc(state.accessCode)}" placeholder="6 цифр"><p class="hint">Введите код с экрана компьютера, затем выберите себя.</p></div>` : '';
    return shell(`<section class="hero-home"><div class="hero-lockup"><p class="eyebrow">Выбор фильма на вечер</p><h1>Tonight <em>🍿</em></h1><p class="lede">Что смотрим сегодня?</p></div>
      ${accessCode}
      <div class="people-grid">
        <button class="person-card" data-user="lera" style="--glow:#ff667c"><span class="person-emoji">🍿</span><span class="person-name">Первый зритель</span></button>
        <button class="person-card" data-user="nikita" style="--glow:#ff9a59"><span class="person-emoji">🎬</span><span class="person-name">Второй зритель</span></button>
      </div>
      <div class="session-strip"><span>${esc(state.session?.title || 'Сегодня')}</span><div class="presence">${participantLine('lera')}${participantLine('nikita')}</div></div>
      <details class="disclosure"><summary>Подключить телефон</summary>${inviteCard()}</details>
    </section>`, {nav:false});
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
  return shell(`${tonightEntry()}<div class="mode-grid">${rouletteEntry()}<section class="tinder-entry"><div><h2>Кино-Tinder</h2><p>Один фильм, три простых действия.</p></div><button class="button secondary" data-tinder-open>Начать подбор</button></section></div>
    <section class="shared-entry"><h2>${active?esc(title):'Выбрать вместе'}</h2><p>Учтём настроение и реакции обоих зрителей.</p><button class="button secondary" data-action="continue-session">${active?esc(cta):'Начать совместный выбор'}</button>${!active?'<button class="button ghost" data-view="quick">Быстрый вечер</button>':''}</section>
    ${job && ['running','error'].includes(job.phase)?`<aside class="status-card" role="status"><p>${esc(job.message || 'Загрузка каталога')}</p><button class="button secondary" data-view="library">Открыть каталог</button></aside>`:''}
    ${personalSection()}<details class="disclosure"><summary>Подключить телефон и пригласить зрителя</summary>${inviteCard()}<div class="presence">${participantLine('lera')}${participantLine('nikita')}</div></details>`);

}

function discoveryCard(movie, reason, action = 'select-personal') {
  return `<article class="history-card">${poster(movie)}<h3>${esc(movie.title)}</h3><p class="hint">${movie.year || 'Год не указан'} · ${movie.runtime ? `${movie.runtime} мин · ` : ''}${esc(movie.genres.join(' · '))}</p><p class="hint">${esc(reason)}</p><div class="footer-actions">${trailerButton(movie)}<button class="button" data-action="${action}" data-movie-id="${esc(movie.id)}">Выбрать на сегодня</button></div></article>`;
}

function personalSection() {
  const data = state.personalUser === state.user ? state.personal : null;
  return `<section aria-labelledby="personal-title"><h2 id="personal-title" class="section-title">Подобрано для тебя</h2><p class="lede">${data?.cold_start ? 'Начнём со знакомства: пока личных оценок мало. Отмечайте фильмы — подборка начнёт учитывать ваш вкус.' : 'По вашим оценкам, реакциям и выбранным предпочтениям.'}</p>${state.personalError ? `<p role="status">${esc(state.personalError)}</p><button class="button secondary" data-action="retry-personal">Повторить</button>` : !data ? '<p role="status">Подбираем фильмы…</p>' : data.items.length ? `<div class="history-grid">${data.items.map(movie => discoveryCard(movie, movie.recommendation_reason)).join('')}</div>${data.limited ? '<p class="hint">Подходящих фильмов пока немного. Оцените ещё фильмы или проверьте выбранные ограничения.</p>' : ''}` : '<div class="empty">Пока нет подходящих фильмов. Проверьте ограничения или обновите каталог.</div>'}</section>`;
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
  return shell(`<section><div class="screen-head"><p class="eyebrow">Быстрый вечер ⚡</p><h2>Что за вечер сегодня?</h2><p class="lede">Одно нажатие заменит настройки времени, сил и настроения.</p></div><div class="choice-stack">${quickEvenings.map(item => `<button class="choice quick-context" data-quick="${item.id}"><span>${item.icon} <strong>${item.title}</strong><small>${item.text}</small></span></button>`).join('')}</div><h3 class="question">Стоп-жанры на сегодня</h3><p class="lede">Отметьте только то, чего точно не хотите. Готовый сценарий сохранит эти запреты.</p><div class="chip-grid">${genres.map(g => `<button class="chip ${state.prefs.disliked_genres.includes(g)?'selected':''}" data-dislike="${g}" aria-pressed="${state.prefs.disliked_genres.includes(g)}">${g}</button>`).join('')}</div><div class="footer-actions"><button class="button ghost" data-view="home">Назад</button></div></section>`, {narrow:true});
}

function renderVibe() {
  return shell(`<section><div class="screen-head"><p class="step">1 из 2 · настроение</p><h2>Какой сегодня вайб?</h2><p class="lede">Можно выбрать несколько. Второй увидит только итоговый мэтч.</p></div>
    <div class="chip-grid">${moods.map(([id,emoji,label]) => `<button class="chip ${state.prefs.moods.includes(id)?'selected':''}" data-mood="${id}" aria-pressed="${state.prefs.moods.includes(id)}">${emoji} ${label}</button>`).join('')}</div>
    <h3 class="question">Сколько сегодня сил?</h3><div class="choice-stack">
      ${[['low','😴','Мозг выключен'],['medium','🙂','Что-нибудь нормальное'],['high','🧠','Готов внимательно смотреть']].map(([id,e,label]) => `<button class="choice ${state.prefs.energy===id?'selected':''}" data-energy="${id}"><span>${e} ${label}</span></button>`).join('')}
    </div><div class="footer-actions"><button class="button large" data-action="to-filters" ${!state.prefs.moods.length || !state.prefs.energy?'disabled':''}>Дальше</button></div>
  </section>`, {narrow:true});
}

function renderFilters() {
  const choice = (field, value, emoji, label) => `<button class="choice ${String(state.prefs[field])===String(value)?'selected':''}" data-field="${field}" data-value="${value ?? ''}"><span>${emoji} ${label}</span></button>`;
  return shell(`<section><div class="screen-head"><p class="step">2 из 2 · рамки вечера</p><h2>Чего сегодня точно хочется избежать?</h2><p class="lede">Стоп-жанры важнее любых высоких рейтингов.</p></div>
    <h3 class="question">Длительность</h3><div class="choice-stack">${choice('max_runtime',90,'⏱','До 90 минут')}${choice('max_runtime',120,'🍿','До 2 часов')}${choice('max_runtime',150,'🎬','До 2.5 часов')}${choice('max_runtime',null,'♾','Неважно')}</div>
    <h3 class="question">Эпоха</h3><div class="choice-stack">${choice('min_year',2015,'✨','Относительно новое')}${choice('min_year',2000,'📀','2000+')}${choice('min_year',1980,'📼','80–90-е тоже ок')}${choice('min_year',null,'🎞','Вообще неважно')}</div>
    <h3 class="question">Сегодня точно НЕ хотим</h3><div class="chip-grid">${genres.map(g => `<button class="chip ${state.prefs.disliked_genres.includes(g)?'selected':''}" data-dislike="${g}" aria-pressed="${state.prefs.disliked_genres.includes(g)}">${g}</button>`).join('')}</div>
    <div class="footer-actions"><button class="button ghost" data-view="vibe">Назад</button><button class="button large" data-action="save-prefs">К быстрым реакциям</button></div>
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
  return shell(`<section><div class="progress-line"><div class="track"><i style="width:${(progress/state.total)*100}%"></i></div><strong>${progress + 1} / ${state.total}</strong></div>
    <aside class="swipe-guidance" id="swipe-guidance"><strong>Вы уже смотрели этот фильм?</strong> Если да — оцените впечатление от просмотра. Если нет — нажмите «Не смотрел(а)». «Нравится» здесь означает оценку просмотренного фильма, а не желание его посмотреть.</aside>
    <div class="swipe-stage"><article class="swipe-card" id="swipe-card" tabindex="0" aria-label="${esc(movie.title)}" aria-describedby="swipe-guidance">
      <div class="poster-wrap">${poster(movie)}<div class="poster-shade"></div><div class="poster-copy"><h2>${esc(movie.title)}</h2><div class="meta"><span>${movie.year}</span><span>•</span><span>${movie.genres.join(' · ')}</span><span>•</span><span>${movie.runtime} мин</span></div><p class="card-overview">${esc(movie.overview || 'Описание пока не добавлено')}</p></div></div>
      ${movie.overview ? descriptionDisclosure(movie.overview, movie.id, 'card-description') : ''}
      <div class="reaction-row">${reactionMap.map(([id,e,label]) => `<button class="reaction" data-reaction="${id}" title="${label}">${e}<span>${label}</span></button>`).join('')}</div>
      <p class="hint keyboard-hint">← не хочу · ↑ обожаю · → нравится · ↓ норм · ? не смотрел(а)</p>
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
  return shell(`<section class="empty"><h2>Пока нет фильмов для выбора</h2><p>Нужно подтверждённое русское название и состоявшийся прокат. Записи каталога и ваша история сохранены.</p><p class="hint">Проверьте обновление каталога на основном компьютере или измените ограничения вечера.</p><button class="button secondary" data-view="home">На главный экран</button></section>`);
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
  return shell(`<section><div class="result-hero"><img src="${main.backdrop_url}" alt=""><div class="result-content"><span class="match">${main.match}% мэтч</span><p class="eyebrow">Кажется, у нас мэтч 🍿</p><h1>${esc(main.title)}</h1><div class="meta"><span>${main.year}</span><span>•</span><span>${main.runtime} мин</span><span>•</span><span>${main.genres.join(' · ')}</span><span>★ ${main.rating}</span></div>${movieDescription(main.overview, main.id)}<div class="footer-actions" style="justify-content:flex-start">${trailerButton(main)}</div></div></div>
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
  return shell(`<section class="selected-layout">${poster(movie)}<div><p class="eyebrow">Финальное решение</p><h1>${esc(movie.title)}</h1><div class="meta"><span>${movie.year}</span><span>•</span><span>${movie.runtime} мин</span><span>•</span><span>${movie.genres.join(' · ')}</span></div>${movieDescription(movie.overview, movie.id)}<p class="hint">${state.session.viewing_company==='solo'?'Смотрите самостоятельно — второй зритель не нужен. После фильма можно поставить свою оценку.':'Будем смотреть? Если да — после просмотра зрители поставят свои оценки, и Tonight учтёт их в следующих рекомендациях.'}</p><div class="footer-actions" style="justify-content:flex-start">${trailerButton(movie)}<button class="button large" data-action="start-watching">${state.session.viewing_company==='solo'?'🍿 Начать одиночный вечер':'✅ Будем смотреть'}</button><button class="button secondary large" data-action="decline">✋ Не смотрим</button><button class="button ghost" data-action="choose-another">🎲 Другой вариант</button></div>
    <details class="avoid-box"><summary>🚫 Не предлагать похожее</summary><p>Это сильнее обычного «не смотрим». Ослабим в будущих рекомендациях:</p><ul><li><strong>Сочетание жанров:</strong> ${esc(traits.genres.join(', ') || 'как у этого фильма')}</li><li><strong>Настроение:</strong> ${esc(traits.moods.join(', ') || 'похожее')}</li>${traits.franchise ? '<li><strong>Франшизу:</strong> следующие части этой серии</li>' : ''}</ul><p class="hint">Целый жанр не будет заблокирован. Действие можно отменить в «Наш вкус».</p><button class="button secondary" data-action="confirm-avoid-similar">Подтвердить и выбрать другой</button></details>
    ${state.tonight?.user===state.user && state.tonight?.data ? '<button class="button ghost" data-tonight-open>← К вариантам Tonight Mode</button>' : ''}</div></section>`);
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
  return shell(`<section><div class="screen-head"><p class="eyebrow">Пять на неделю ✦</p><h2>Можно выбрать без долгих поисков</h2><p class="lede">Короткая локальная подборка для вас двоих. Она обновится на следующей неделе.</p><p class="hint">Tonight ничего не отправляет сам — подборка ждёт здесь, когда понадобится.</p></div>${items.length ? `<div class="history-grid">${items.map(movie => discoveryCard(movie, movie.weekly_reason, 'select-weekly')).join('')}</div>` : '<div class="empty"><h3>Пока подбираем варианты</h3><p>Откройте экран ещё раз через минуту.</p></div>'}</section>`);
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
  const cards = visibleItems.length ? `<div class="history-grid">${visibleItems.map(movie => `<article class="history-card">${poster(movie)}<h3>${esc(movie.title)}</h3><p class="hint">${esc(movie.overview || 'Описание появится после обновления каталога')}</p>${movie.fits_tonight === true ? '<p class="hint">✓ Подходит под сегодняшний план</p>' : ''}${movie.franchise_warning ? `<p class="hint">⚠ ${esc(movie.franchise_warning)}</p>` : ''}${movie.saved_by ? `<p class="hint">Добавил(а): ${esc(names[movie.saved_by])}</p>` : ''}${movie.deferred_reason ? `<p class="hint">Отложили: ${esc(movie.deferred_reason)}</p>` : ''}<div class="footer-actions">${trailerButton(movie, 'button secondary')}<button class="button" data-action="watch-saved" data-movie-id="${movie.id}">✅ Будем смотреть</button><button class="button ghost" data-action="remove-later" data-movie-id="${movie.id}">Убрать</button></div></article>`).join('')}</div>` : `<div class="empty compact"><h3>Ничего не нашли</h3><p>Попробуйте другое слово или жанр.</p><button class="button ghost" data-action="reset-watchlist-filters">Сбросить фильтры</button></div>`;
  return shell(`<section><div class="screen-head"><p class="eyebrow">Общий список ♡</p><h2>На потом</h2><p class="lede">Варианты, которые понравились, но не подошли именно сегодня.</p>${state.watchlistHiddenCount ? `<p class="hint">Скрыто сохранённых фильмов: ${state.watchlistHiddenCount}. Русское название или состоявшийся прокат пока не подтверждены. Записи в списке сохранены.</p>` : ''}${items.some(movie => movie.fits_tonight !== null) ? '<p class="hint">Сначала — то, что подходит под сегодняшний план. Остальные фильмы остаются в списке.</p>' : ''}</div>${items.length ? `${filters}${cards}` : '<div class="empty"><h3>Пока пусто</h3><p>Сохраняйте подходящие фильмы из результатов, чтобы вернуться к ним в другой вечер.</p></div>'}</section>`);
}

function renderSearch() {
  const items = state.searchResults || [];
  return shell(`<section><div class="screen-head"><p class="eyebrow">Поиск по примеру</p><h2>На что похоже настроение?</h2><p class="lede">Напишите название, жанр или деталь — например, «Как Достать ножи» или «смешное на полтора часа».</p></div><form class="search-form" data-action="search-catalog"><input name="query" value="${esc(state.searchQuery)}" placeholder="Название или пример фильма" maxlength="100"><button class="button" type="submit">Найти</button></form>${state.searchQuery ? (items.length ? `<div class="history-grid">${items.map(movie => `<article class="history-card">${poster(movie)}<h3>${esc(movie.title)}</h3><p class="hint">${movie.year} · ${esc(movie.genres.join(' · '))}</p><p class="hint">${esc(movie.overview)}</p><div class="footer-actions">${trailerButton(movie, 'button secondary')}<button class="button secondary" data-action="select-search-result" data-movie-id="${movie.id}">Выбрать на сегодня</button></div></article>`).join('')}</div>` : '<div class="empty"><p>В локальном каталоге ничего похожего не нашли. Попробуйте название или более короткий запрос.</p></div>') : ''}</section>`);
}

function renderTaste() {
  const data = state.taste || {profiles:{lera:[],nikita:[],pair:[]}, avoidances:{lera:[],nikita:[]}, enough_data:false, watched:0};
  const column = (title,key) => `<div class="panel"><h3>${title}</h3><div class="taste-list">${data.profiles[key]?.length ? data.profiles[key].map(g => `<div class="taste-item"><span>${g.score>=4.5?'❤️':g.score>=3.5?'👍':'•'} ${esc(g.genre)}</span><small>${g.count}×</small>${key === state.user ? `<button class="button ghost small" data-action="remove-taste-genre" data-genre="${esc(g.genre)}">Удалить этот вывод</button>` : ''}</div>`).join('') : '<p class="lede">Пока мало данных</p>'}</div></div>`;
  const avoidances = data.avoidances?.[state.user] || [];
  const backups = state.backups || [];
  const latestBackup = backups[0] ? `Последняя копия: ${new Date(backups[0].created_at).toLocaleString('ru-RU', {dateStyle:'medium', timeStyle:'short'})}.` : 'Последней копии пока нет.';
  const backupList = backups.length ? `<div class="backup-list">${backups.slice(0,5).map(item => `<article><div><strong>${new Date(item.created_at).toLocaleString('ru-RU', {dateStyle:'medium', timeStyle:'short'})}</strong><p>${Math.max(1, Math.round(item.bytes / 1024))} КБ</p></div><div class="footer-actions"><a class="button ghost small" href="/api/backups/${encodeURIComponent(item.name)}/download">Скачать</a><button class="button ghost small" data-action="restore-backup" data-backup-name="${esc(item.name)}">Восстановить</button></div></article>`).join('')}</div>` : '<div class="empty compact"><p>Копий пока нет.</p></div>';
  return shell(`<section><div class="screen-head"><p class="eyebrow">Профили зрителей</p><h2>Наш вкус</h2><p class="lede">Не сумма двух профилей, а то, что особенно хорошо работает именно вместе.</p></div>
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
    searchInput.setAttribute('aria-label', 'Название или пример фильма');
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
  const request = ++state.navigationRequest;
  const previousView = state.view;
  state.modal = null;
  if (view === 'home') { state.personalAt=0; state.view='home'; render(); return; }
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
    state.user = user; localStorage.setItem('tonight:user', user);
    await api(`/api/sessions/${state.session.id}/join`, {method:'POST', body:joinBody(user)});
    if (isRemoteClient()) sessionStorage.setItem('tonight:access-code', state.accessCode);
    state.session = await api(`/api/sessions/${state.session.id}`);
    connectWs(); state.view='home'; render();
  } catch (e) { state.user=null; localStorage.removeItem('tonight:user'); toast(e.message); render(); }
}

function switchUser() {
  clearTimeout(state.reconnectTimer); state.reconnectTimer=null;
  state.ws?.close(); state.ws=null; state.user=null; state.accessCode=''; state.prefs=defaultPrefs(); state.deck=[]; localStorage.removeItem('tonight:user'); sessionStorage.removeItem('tonight:access-code'); state.view='home'; render();
}

async function continueSession() {
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
    const data = await api(`/api/sessions/${state.session.id}/swipe/${state.user}`); state.deck=data.movies; state.total=data.total; state.view=state.deck.length?'swipe':'waiting';
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
    const response = await fetch('/api/backups/import?confirmed=true', {method:'POST', headers:{'Content-Type': file.type || 'application/vnd.sqlite3'}, body:file});
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
  try { for(const key of ['lera','nikita']) { sessionStorage.removeItem(`tonight:mode:${key}`); sessionStorage.removeItem(`tonight:tinder:${key}`); sessionStorage.removeItem(`tonight:roulette:${key}`); } } catch (_) {}
  state.roulette=null;state.rouletteRequest++;
  state.tonight=null;state.tonightRequest++;state.tinder=null;state.tinderRequest++;
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

async function selectSearchResult(movieId) {
  try { const movie=await api(`/api/sessions/${state.session.id}/select-catalog/${encodeURIComponent(movieId)}`,{method:'POST'}); state.session=await api(`/api/sessions/${state.session.id}`); state.view='selected'; render(); }
  catch(e) { toast(e.message); }
}

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

async function watchSavedMovie(movieId) {
  try {
    if (state.session.status === 'completed') {
      state.session = await api(`/api/sessions/${state.session.id}/restart`, {method:'POST'});
      await api(`/api/sessions/${state.session.id}/join`, {method:'POST', body:joinBody(state.user)});
      connectWs();
    }
    const movie = await api(`/api/sessions/${state.session.id}/select-saved/${encodeURIComponent(movieId)}`, {method:'POST'});
    state.session.selected = movie; state.session.viewing_company='couple';state.session.solo_user_id=null;state.session.status = 'selected'; state.view = 'selected'; render();
  } catch (e) { toast(e.message); }
}

function renderModal() {
  const old=document.querySelector('.modal-backdrop'); old?.remove();
  if(!state.modal)return; const m=state.modal;
  const node=document.createElement('div'); node.className='modal-backdrop'; node.innerHTML=`<div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-layout">${poster(m)}<div><span class="match">${m.match}% мэтч</span><h2 id="modal-title">${esc(m.title)}</h2><div class="meta">${m.year} · ${m.runtime} мин · ${m.genres.join(' · ')}</div><p class="lede" style="margin-top:1rem">${esc(m.overview)}</p><button class="button secondary" data-close>Закрыть</button></div></div></div>`;
  document.body.appendChild(node); node.querySelector('[data-close]').focus();
  const close=()=>{state.modal=null;node.remove();}; node.addEventListener('click',e=>{if(e.target===node||e.target.closest('[data-close]'))close();});
  node.addEventListener('keydown',e=>{if(e.key==='Escape')close();});
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
  ws.onmessage=e=>{ const data=JSON.parse(e.data); if(data.type==='personal_changed'){state.personalAt=0;state.personalRevision++;if(state.view==='home')refreshPersonal();return;} if(data.type==='privacy_reset'){forgetLocalViewer();state.ws=null;toast('Личные данные удалены на основном компьютере');setTimeout(()=>location.reload(),700);return;} if(!data.presence && !data.session) return; if(data.presence)state.presence=data.presence; if(data.session)applyRealtimeSession(data.session); renderRealtime(); };
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

async function init() {
  state.view='loading'; render();
  try {
    [state.setup,state.session,state.invite]=await Promise.all([api('/api/setup/status'),api('/api/sessions/active'),api('/api/invite')]);
    if (isRemoteClient() || new URLSearchParams(location.search).get('join') === '1') localStorage.setItem('tonight:setup','1');
    state.view=localStorage.getItem('tonight:setup')?'home':'setup';
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
  return `<section class="tonight-entry"><div><p class="eyebrow">Tonight Mode</p><h2>Что смотрим сегодня?</h2><p class="lede">Укажите настроение, время и компанию — выберите из пяти вариантов.</p></div><button class="button large" data-tonight-open>Подобрать фильм <span aria-hidden="true">↗</span></button></section>`;
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
  return `<article class="tonight-film ${detail?'is-detail':''}"><button class="tonight-poster" data-tm-detail="${esc(m.id)}" aria-label="Подробнее: ${esc(m.title)}">${poster(m)}</button><div class="tonight-film-body"><p class="eyebrow">${tonightRating(m)}</p><h3><button class="tonight-title" data-tm-detail="${esc(m.id)}">${esc(m.title)}</button></h3><p class="hint">${m.year || 'Год не указан'} · ${m.runtime ? `${m.runtime} мин`:'Длительность не указана'}</p><p class="hint">${esc((m.genres || []).join(' · '))}</p><p class="${detail?'':'tonight-overview'}">${esc(detail?(m.overview || 'Описание отсутствует в каталоге.'):tonightSynopsis(m))}</p><p class="tonight-reason">✦ ${esc(m.recommendation_reason)}${t.filters.max_runtime ? ` Не дольше ${t.filters.max_runtime} минут.`:''}</p><div class="tonight-film-actions">${state.session?.status!=='watching'?`<button class="button" data-tm-select="${esc(m.id)}">${t.filters.company==='solo'?'Смотреть одному':'Выбрать на сегодня'}</button>`:''}<details class="film-menu" data-disclosure-key="film-${esc(m.id)}"><summary>Другие действия</summary><div class="choice-stack">${[['watchlist','♡ Хочу посмотреть'],['watched','✓ Уже смотрел'],['dislike','− Не интересно']].map(([id,label])=>`<button class="button ${actions.has(id)?'':'secondary'}" data-tm-action="${id}" data-tm-id="${esc(m.id)}" ${actions.has(id) || t.saving?'disabled':''} aria-pressed="${actions.has(id)}">${label}${actions.has(id)?' · сохранено':''}</button>`).join('')}</div></details></div></div></article>`;
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
    const content=[()=>tonightChoices('mood',tonightMoods),()=>tonightChoices('max_runtime',[[90,'До 90 минут'],[120,'До 120 минут'],[150,'До 150 минут'],[null,'Неважно']]),()=>tonightChoices('company',tonightCompanies),()=>`<div class="tonight-options"><label>Минимальный рейтинг <select data-tm-input="min_rating">${[0,6,7,8,9].map(n=>`<option value="${n}" ${f.min_rating===n?'selected':''}>${n?`${n} / 10`:'Неважно'}</option>`).join('')}</select></label>${tonightYearControls(t)}<fieldset><legend>Исключить жанры</legend><div class="chip-grid">${[...new Set([...genres,'семейный','приключения','криминал','история','музыка','военный','вестерн'])].map(g=>`<button class="chip ${f.excluded_genres.includes(g)?'selected':''}" data-tm-genre="${g}" aria-pressed="${f.excluded_genres.includes(g)}">${g}</button>`).join('')}</div></fieldset><label class="tonight-check"><input type="checkbox" data-tm-watched ${f.exclude_watched?'checked':''}> Исключить просмотренные фильмы</label><p class="hint">Сложность сюжета не оцениваем: в каталоге нет надёжных данных.</p></div>`][t.step]();
    body=`${nav}<div class="tonight-stage" key="${t.step}"><h2 tabindex="-1" data-tm-heading>${titles[t.step]}</h2><p class="lede">${t.step===3?'Все параметры на этом шаге необязательны.':t.step===2?'Вдвоём учитываем вкус обоих зрителей. Для друзей — ваш вкус; для семьи — семейные жанры. Это не возрастной допуск.':''}</p>${content}<div class="footer-actions"><button class="button ghost" data-tm-back>${t.step?'← Назад':'На главную'}</button><button class="button" data-tm-next ${t.busy?'disabled':''}>${t.data?'Применить изменения':t.step===3?'Подобрать фильмы':'Далее →'}</button>${t.data?'<button class="button ghost" data-tm-cancel>Отменить изменения</button>':''}</div></div>`;
  } else {
    body=`${nav}<div class="screen-head"><h2 tabindex="-1" data-tm-results>Ваши варианты на вечер.</h2><p class="lede">${t.data?.cold_start?'Пока знакомимся с вашим вкусом: учитываем настроение и данные каталога.':'По оценкам зрителей и условиям этого вечера.'}</p><p class="hint">${esc(tonightMoods.find(m=>m[0]===f.mood)?.[2] || '')} · ${f.max_runtime?`до ${f.max_runtime} мин`:'любая длительность'} · ${esc(tonightCompanies.find(c=>c[0]===f.company)?.[1] || '')}. Нажмите на нужный шаг выше, чтобы изменить условия.</p></div>${t.busy?'<div class="empty" role="status">Tonight IQ подбирает фильмы…</div>':`${t.data?.limited?`<aside class="tonight-empty" role="status"><h3>${t.data.items.length?`Нашлось ${t.data.items.length} из 5 вариантов`:'Подходящие варианты закончились'}</h3><p>${t.data.exhausted?'Уже показанные фильмы исключены из повторного подбора. ':''}${t.data.catalog_available===0?'В каталоге пока нет фильмов с подтверждёнными данными о прокате. Обновите каталог в разделе «Каталог».':'Сочетание условий, истории просмотров и исключений оставляет мало фильмов. Измените условия или снимите исключение просмотренных.'} Ограничения сохранены.</p><div class="footer-actions">${(t.data.relaxations || []).map(r=>`<button class="button secondary" data-tm-relax="${r.field}">Ослабить: ${esc(r.label)} · до ${r.available} вариантов</button>`).join('')}<button class="button ghost" data-tm-step="3">Изменить фильтры</button>${t.seen.length?'<button class="button ghost" data-tm-repeat>Вернуться к уже показанным</button>':''}</div></aside>`:''}<div class="tonight-films">${(t.data?.items || []).map(m=>tonightCard(m)).join('')}</div><div class="footer-actions"><button class="button" data-tm-more ${!t.data?.items.length?'disabled':''}>Другие варианты ↻</button><button class="button ghost" data-view="home">На главную</button></div>`}`;
  }
  return shell(`<section class="tonight-mode" aria-busy="${!!t.busy}"><p class="eyebrow">Tonight Mode</p>${t.error?`<p role="alert" class="constraint-warning">${esc(t.error)}</p>`:''}${body}</section>`);
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
async function selectTonightMovie(movieId) {
  try {
    if(state.session?.status==='completed') {
      state.session=await api(`/api/sessions/${state.session.id}/restart`,{method:'POST'});
      await api(`/api/sessions/${state.session.id}/join`,{method:'POST',body:joinBody(state.user)});
      connectWs();
    }
    await api(`/api/sessions/${state.session.id}/select-catalog/${encodeURIComponent(movieId)}`,{method:'POST',body:JSON.stringify({company:state.tonight.filters.company,user_id:state.user})});
    state.session=await api(`/api/sessions/${state.session.id}`);
    state.view='selected';render();
  } catch(error) {toast(error.message);}
}
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
    try {await api(`/api/tonight/${t.user}/movies/${encodeURIComponent(el.dataset.tmId)}`,{method:'POST',body:JSON.stringify({action:el.dataset.tmAction})});const m=t.data.items.find(m=>m.id===el.dataset.tmId);t.actions[m.id]=[...new Set([...(t.actions[m.id] || m.viewer_actions || []),el.dataset.tmAction])];toast('Сохранено');}
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
  }catch(e){t.error=e.message;}
  finally{t.busy=false;saveTinder();if(state.view==='tinder'&&state.tinder===t)render();}
}
function renderTinder(){
  const t=state.tinder,m=t?.queue[0];if(!t)return shell('');
  const disabled=t.busy?'disabled':'';
  const details=m?`<p class="eyebrow">${tonightRating(m)}</p><h2>${esc(m.title)}</h2><p class="hint">${m.year||'Год не указан'} · ${m.runtime?`${m.runtime} мин`:'Длительность не указана'}</p><p class="hint">${esc((m.genres||[]).join(' · '))}</p>`:'';
  const undo=`<button class="button secondary tinder-undo" data-kt-undo aria-label="Отменить последнее действие" title="Отменить последнее действие" ${!t.history.length||t.busy||t.detail?'disabled':''}>↶</button>`;
  return shell(`<section class="tinder-mode" aria-busy="${!!t.busy}"><div class="tinder-heading"><h1>Кино-Tinder</h1><details class="mode-menu"><summary>Настройки</summary><div><label class="tinder-save"><input type="checkbox" data-kt-save ${t.save?'checked':''} ${disabled}> «Интересно» также добавляет в «На потом»</label><button class="button ghost" data-kt-new ${disabled}>Новая сессия</button><p class="hint keyboard-hint">← / → / ↑ — действия · Enter — подробности · Z — отмена</p></div></details></div>
    ${t.error?`<p role="alert" class="constraint-warning">${esc(t.error)}</p><button class="button secondary" data-kt-retry>${t.pending?'Повторить сохранение':'Повторить загрузку'}</button>`:''}
    ${t.detail&&m?`<div class="tinder-detail"><button class="button ghost" data-kt-close>← К карточке</button>${details}<p>${esc(m.overview||'Описание отсутствует в каталоге.')}</p><p class="tonight-reason">${esc(m.recommendation_reason || '')}</p></div>`:m?`
    <article class="tinder-card" data-kt-card tabindex="0" aria-label="${esc(m.title)}">
      <div class="tinder-image">${poster(m)}<span class="tinder-direction" aria-hidden="true"></span></div>
      <div class="tinder-copy">${details}<p>${esc(tonightSynopsis(m))}</p><button class="button ghost" data-kt-details>Подробнее о фильме</button></div>
    </article><div class="tinder-action-panel"><div class="tinder-controls" aria-label="Действия с фильмом">${[['dislike','←','Не интересно'],['watched','↑','Уже смотрел'],['interest','→','Интересно']].map(([action,icon,label])=>`<button class="button ${action==='interest'?'':'secondary'}" data-kt-action="${action}" ${disabled}><span aria-hidden="true">${icon}</span> ${label}</button>`).join('')}${undo}</div></div>`:`<div class="empty" role="status"><h2>${t.busy?'Подбираем фильмы…':'Фильмы закончились'}</h2><p>${t.busy?'Учитываем ваш вкус.':t.catalogAvailable===0?'В каталоге нет подтверждённых фильмов. Откройте каталог для обновления.':'Доступные варианты просмотрены. Новая сессия учитывает сохранённые действия.'}</p>${!t.busy?'<button class="button" data-kt-new>Новая сессия</button><button class="button ghost" data-view="library">Каталог</button>':''}${undo}</div>`}
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
    t.history.push({id:result.id,movie:m});t.queue.shift();t.pending=null;saveTinder();
    if(!t.queue.length){t.busy=false;await fetchTinder();}
  }catch(e){t.error=e.message;}
  finally{t.busy=false;saveTinder();if(state.view==='tinder'&&state.tinder===t){render();root.querySelector('[data-kt-card]')?.focus({preventScroll:true});}}
}
async function tinderUndo(){
  const t=state.tinder,entry=t?.history.at(-1);if(!entry||t.busy||t.detail)return;
  t.busy=true;t.error='';render();
  try{await api(`/api/tinder/${t.user}/undo/${entry.id}`,{method:'POST'});t.history.pop();t.queue=t.queue.filter(m=>m.id!==entry.movie.id);t.queue.unshift(entry.movie);t.pending=null;}
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
  root.querySelector('[data-kt-save]')?.addEventListener('change',e=>{t.save=e.target.checked;try{localStorage.setItem(`tonight:tinder-save:${t.user}`,t.save?'1':'0');}catch(_){}saveTinder();});
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
  return `<section class="tinder-entry"><div><h2>Кинорулетка</h2><p>Один вариант с учётом вашего вкуса.</p></div><button class="button secondary" data-roulette-open>Реши за меня 🎲</button></section>`;
}
function saveRoulette(){
  const r=state.roulette;if(!r)return;
  try{sessionStorage.setItem(`tonight:roulette:${r.user}`,JSON.stringify({user:r.user,filters:r.filters,seen:r.seen,accepted:r.accepted,acceptedTitle:r.acceptedTitle,short:r.short}));}catch(_){}
}
function openRoulette(){
  if(!state.user)return;
  if(state.roulette?.user!==state.user){
    let saved;try{saved=JSON.parse(sessionStorage.getItem(`tonight:roulette:${state.user}`));}catch(_){}
    state.roulette=saved?.user===state.user?saved:{user:state.user,filters:{mode:'smart',max_runtime:null,min_rating:0,min_year:null,max_year:null,included_genres:[],excluded_genres:[],exclude_watched:true},seen:[],accepted:null,short:false};
    state.roulette.busy=false;
  }
  state.view='roulette';render();
}
function renderRoulette(){
  const r=state.roulette;if(!r||r.user!==state.user)return renderHome();
  const f=r.filters,m=r.movie,locked=r.busy||r.spinning;
  const genreChoices=(key,label)=>`<fieldset><legend>${label}</legend><div class="chip-grid">${[...new Set([...genres,'семейный','приключения','криминал','история','музыка','военный','вестерн'])].map(g=>`<button class="chip ${f[key].includes(g)?'selected':''}" data-r-genre="${key}" data-r-value="${esc(g)}" aria-pressed="${f[key].includes(g)}">${esc(g)}</button>`).join('')}</div></fieldset>`;
  return shell(`<section class="roulette-mode"><div class="tinder-heading"><div><h1>Кинорулетка</h1></div></div>
  <details class="roulette-configuration" data-r-settings data-render-state ${r.settingsOpen??!m?'open':''}><summary>Настройки выбора</summary><fieldset class="roulette-settings" ${locked?'disabled':''}><legend>Как выбираем?</legend><div class="tonight-choices">${[['smart','Умный выбор','Больше веса вашему вкусу'],['surprise','Полная неожиданность','Больше шансов новым жанрам'],['watchlist','Из моего списка','Только из «На потом»']].map(([id,title,desc])=>`<button class="choice ${f.mode===id?'selected':''}" data-r-mode="${id}" aria-pressed="${f.mode===id}"><strong>${title}</strong><small>${desc}</small></button>`).join('')}</div>
  <details class="roulette-filters" ${r.filtersOpen?'open':''}><summary>Быстрые ограничения</summary><p class="hint">Применяем вместе с сохранёнными ограничениями профиля. Автоматически ничего не ослабляем.</p><div class="roulette-inputs">${[['max_runtime','Максимум минут',1,1440],['min_rating','Минимальный рейтинг',0,10],['min_year','Год от',1888,2100],['max_year','Год до',1888,2100]].map(([key,label,min,max])=>`<label>${label}<input type="number" data-r-input="${key}" min="${min}" max="${max}" step="${key==='min_rating'?'.1':'1'}" value="${f[key]??''}" placeholder="Неважно"></label>`).join('')}</div>${genreChoices('included_genres','Жанры: хотя бы один из выбранных')}${genreChoices('excluded_genres','Исключить жанры')}<label class="tonight-check"><input type="checkbox" data-r-watched ${f.exclude_watched?'checked':''}> Исключить уже просмотренные</label></details>
  <label class="tonight-check"><input type="checkbox" data-r-short ${r.short?'checked':''}> Короткая анимация</label></fieldset><p class="hint">Скрытые и нежелательные фильмы исключены во всех режимах.</p></details>
  ${r.acceptedTitle&&r.accepted!==m?.id?`<p class="tonight-reason">Ваш выбор в этой сессии: ${esc(r.acceptedTitle)}</p>`:''}
  ${!m?`<button class="button large roulette-launch" data-r-launch ${locked?'disabled':''}>${r.busy?'Подбираем фильм…':'Реши за меня'}</button>`:''}
  ${r.error?`<p class="error" role="alert">${esc(r.error)}</p>`:''}
  ${r.empty?`<div class="empty" role="status"><h2>${r.watchlistCount===0?'В списке пока пусто':'Подходящие фильмы закончились'}</h2><p>${r.watchlistCount===0?'Добавьте фильмы в «На потом» или выберите другой режим.':'Измените быстрые ограничения или сохранённые ограничения профиля. Уже предложенные в этой сессии фильмы исключены; ограничения сохранены.'}</p></div>`:''}
  ${m?`<article class="roulette-result ${r.spinning?'is-spinning':''}" aria-busy="${!!r.spinning}"><div class="roulette-poster">${poster(m)}${r.spinning?'<div class="roulette-orbit" aria-hidden="true">✦</div>':''}</div>${r.spinning?`<div><p role="status">Один фильм для вашего вечера…</p><button class="button secondary" data-r-skip>Пропустить анимацию</button></div>`:`<div class="roulette-copy"><p class="eyebrow">${tonightRating(m)}</p><h2 tabindex="-1" data-r-title>${esc(m.title)}</h2><p class="hint">${m.year||'Год не указан'} · ${m.runtime?`${m.runtime} мин`:'Длительность не указана'}</p><p class="hint">${esc((m.genres||[]).join(' · '))}</p><p>${esc(tonightSynopsis(m))}</p><p class="tonight-reason">✦ ${esc(m.recommendation_reason)}</p><div class="tonight-film-actions"><button class="button" data-r-accept ${r.accepted===m.id||r.busy?'disabled':''}>${r.accepted===m.id?'✓ Выбрано на эту сессию':'Беру этот'}</button><button class="button secondary" data-r-launch>Другой фильм</button><button class="button secondary" data-r-action="watchlist" ${m.saved||r.busy?'disabled':''}>${m.saved?'✓ В списке':'Хочу посмотреть'}</button><button class="button ghost" data-r-action="dislike" ${r.busy?'disabled':''}>Не интересно</button></div><p class="hint">«Беру этот» сохраняет решение в этой вкладке. Просмотренным фильм станет только после вашей отметки.</p></div>`}</article>`:''}</section>`);
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
      const duration=matchMedia('(prefers-reduced-motion: reduce)').matches?0:r.short?180:1800;
      r.timer=setTimeout(()=>finishRoulette(r),duration);
    }
  }catch(e){r.error=e.message;}
  finally{r.busy=false;if(state.roulette===r&&state.user===r.user&&state.view==='roulette'){render();if(r.spinning)root.querySelector('.roulette-result')?.scrollIntoView({block:'start',behavior:'auto'});}}
}
async function rouletteAction(action){
  const r=state.roulette,m=r?.movie;if(!m||r.busy||r.spinning||state.user!==r.user)return;
  r.busy=true;r.error='';render();
  try{
    await api(`/api/tonight/${r.user}/movies/${encodeURIComponent(m.id)}`,{method:'POST',body:JSON.stringify({action})});
    if(action==='watchlist')m.saved=true;
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
  root.querySelector('[data-r-short]')?.addEventListener('change',e=>{r.short=e.target.checked;saveRoulette();});
  root.querySelectorAll('[data-r-launch]').forEach(el=>el.addEventListener('click',spinRoulette));
  root.querySelector('[data-r-skip]')?.addEventListener('click',()=>finishRoulette(r));
  root.querySelector('[data-r-accept]')?.addEventListener('click',()=>{r.accepted=r.movie.id;r.acceptedTitle=r.movie.title;saveRoulette();render();});
  root.querySelectorAll('[data-r-action]').forEach(el=>el.addEventListener('click',()=>rouletteAction(el.dataset.rAction)));
  const img=root.querySelector('.roulette-poster img');if(img){const fail=()=>{img.nextElementSibling.textContent='Постер недоступен';};img.addEventListener('error',fail);if(img.complete&&!img.naturalWidth)fail();}
}

init();
