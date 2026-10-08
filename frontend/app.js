const root = document.querySelector('#app');
const toastNode = document.querySelector('#toast');

const state = {
  user: localStorage.getItem('tonight:user'),
  accessCode: sessionStorage.getItem('tonight:access-code') || '',
  session: null,
  setup: null,
  invite: null,
  view: 'loading',
  presence: { lera: false, nikita: false },
  connected: true,
  prefs: { moods: [], energy: null, max_runtime: 120, min_year: 2000, disliked_genres: [] },
  deck: [], total: 20, ws: null, reconnectTimer: null, reconnectAttempts: 0, wasDisconnected: false,
  historyId: null, modal: null, deferMovieId: null, privacyDeleteOpen: false, waitTimer: null, recovering: false, restarting: false, waitError: '', backups: [], backupImportFile: null, searchQuery:'', searchResults:[], weeklyPicks:[], franchises:[], diagnostics:null, usageSummary:null, watchlistQuery:'', watchlistGenre:'',
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
    ${nav ? `<header class="topbar"><button class="brand" data-view="home">Tonight <span>🍿</span></button><nav class="top-actions" aria-label="Основная навигация">
      <button class="icon-button" data-view="history">◷ <span class="nav-label">История</span></button><button class="icon-button" data-view="weekly">✦ <span class="nav-label">Неделя</span></button><button class="icon-button" data-view="franchises">≡ <span class="nav-label">Серии</span></button><button class="icon-button" data-view="diagnostics">✓ <span class="nav-label">Проверить</span></button>
      <button class="icon-button" data-view="watchlist">♡ <span class="nav-label">На потом</span></button>
      <button class="icon-button" data-view="taste">♡ <span class="nav-label">Наш вкус</span></button><button class="icon-button" data-view="search">⌕ <span class="nav-label">Найти</span></button>${identity}
    </nav></header>` : ''}
    <main id="main" class="page ${narrow ? 'narrow' : ''}">${content}</main>
    ${credits}
    ${!state.connected && state.user ? '<div class="reconnect">Связь пропала — восстанавливаем…</div>' : ''}
  </div>`;
}

function render() {
  clearTimeout(state.waitTimer);
  const viewChanged = render.lastView !== state.view;
  render.lastView = state.view;
  if (state.view === 'loading') {
    root.innerHTML = shell('<div class="hero-home"><div class="skeleton"></div></div>', { nav:false });
    if (viewChanged) requestAnimationFrame(() => window.scrollTo(0, 0));
    return;
  }
  const views = {
    setup: renderSetup, home: renderHome, vibe: renderVibe, filters: renderFilters,
    swipe: renderSwipe, waiting: renderWaiting, results: renderResults, quick: renderQuick,
    selected: renderSelected, feedback: renderFeedback, eveningFeedback: renderEveningFeedback, history: renderHistory, weekly: renderWeekly, franchises: renderFranchises, diagnostics: renderDiagnostics,
    taste: renderTaste, watchlist: renderWatchlist, search: renderSearch, error: renderError,
  };
  root.innerHTML = (views[state.view] || renderHome)();
  bindCommon();
  if (state.view === 'swipe') bindSwipeGestures();
  if (state.view === 'waiting') scheduleWaitingCheck();
  if (state.modal) renderModal();
  if (state.deferMovieId) renderDeferDialog();
  if (state.privacyDeleteOpen) renderPrivacyDeleteDialog();
  if (viewChanged) requestAnimationFrame(() => window.scrollTo(0, 0));
}

function renderSetup() {
  const o = state.setup?.ollama || {};
  return shell(`<section class="panel" style="margin-top:8vh">
    <p class="eyebrow">Первый запуск</p><h2>Добро пожаловать в Tonight 🍿</h2>
    <p class="lede">Проверим, что всё готово для выбора фильма.</p>
    <div class="setup-list">
      <div class="setup-row"><span>Каталог готов</span><strong class="ok">✓ ${state.setup?.catalog || 0} фильмов</strong></div>
      <div class="setup-row"><span>Постеры загружены</span><strong class="${state.setup?.posters ? 'ok':'warn'}">${state.setup?.posters ? `✓ ${state.setup.posters}`:'○ Есть запасные обложки'}</strong></div>
      <div class="setup-row"><span>Можно выбирать фильм</span><strong class="ok">✓ Готово</strong></div>
    </div>
    <p class="lede">Всё готово к киновечеру 🍿</p>
    <details class="setup-help"><summary>Если что-то не работает</summary><div class="setup-list technical-list">
      <div class="setup-row"><span>Database</span><strong class="ok">✓ Готова</strong></div>
      <div class="setup-row"><span>Ollama</span><strong class="${o.available ? 'ok':'warn'}">${o.available ? '✓ Подключена':'○ Необязательна'}</strong></div>
      <div class="setup-row"><span>AI model</span><strong class="${o.model_installed ? 'ok':'warn'}">${o.model_installed ? `✓ ${esc(o.model)}`:'○ Работаем без неё'}</strong></div>
      <div class="setup-row"><span>Local network</span><strong class="ok">✓ Tonight доступен</strong></div>
    </div>${!o.model_installed ? `<p>Tonight работает и без Ollama. Для умных подсказок на этом компьютере:</p><div class="choice"><code>${esc(state.setup?.model_command)}</code></div>` : ''}${!state.setup?.posters ? `<p>Чтобы один раз загрузить настоящие постеры через TMDB:</p><div class="choice"><code>${esc(state.setup?.poster_command)}</code></div>` : ''}</details>
    <div class="footer-actions"><button class="button large" data-action="finish-setup">Продолжить</button></div>
  </section>`, { narrow:true, nav:false });
}

function participantLine(id) {
  const person = state.session?.participants?.[id] || {};
  const live = state.presence[id];
  let text = live ? 'в сети' : person.ready ? 'готов 🍿' : person.joined ? (person.progress ? `выбирает: ${person.progress} / ${state.total}` : 'присоединился') : 'ещё не здесь';
  return `<span><i class="dot ${live ? 'online':''}"></i>${names[id]} — ${text}</span>`;
}

function renderHome() {
  if (!state.user) {
    const accessCode = isRemoteClient() ? `<div class="panel" style="margin-bottom:1rem"><label for="access-code"><strong>Код с экрана Tonight</strong></label><input id="access-code" data-access-code inputmode="numeric" autocomplete="one-time-code" maxlength="6" value="${esc(state.accessCode)}" placeholder="6 цифр"><p class="hint">Введите код с экрана компьютера, затем выберите себя.</p></div>` : '';
    return shell(`<section class="hero-home"><div class="hero-lockup"><p class="eyebrow">Домашний кинозал для двоих</p><h1>Tonight <em>🍿</em></h1><p class="lede">Что смотрим сегодня?</p></div>
      ${accessCode}
      <div class="people-grid">
        <button class="person-card" data-user="lera" style="--glow:#ff667c"><span class="person-emoji">🍿</span><span class="person-name">Первый зритель</span><span class="person-status">Это я</span></button>
        <button class="person-card" data-user="nikita" style="--glow:#ff9a59"><span class="person-emoji">🎬</span><span class="person-name">Второй зритель</span><span class="person-status">Это я</span></button>
      </div>
      <div class="session-strip"><span>${esc(state.session?.title || 'Сегодня')}</span><div class="presence">${participantLine('lera')}${participantLine('nikita')}</div></div>
      ${inviteCard()}
    </section>`, {nav:false});
  }
  const s = state.session;
  let title = 'Начнём киновечер?';
  let cta = 'Какой сегодня вайб?';
  if (s?.status === 'completed') { title = 'Ещё один фильм?'; cta = 'Начать новый вечер 🍿'; }
  else if (s?.status === 'recommended') { title = 'Кажется, мэтч уже найден'; cta = 'Показать результат'; }
  else if (s?.status === 'selected') { title = 'Фильм на сегодня выбран'; cta = 'Показать выбор'; }
  else if (s?.participants?.[state.user]?.ready) { title = `Готово, ${names[state.user]}!`; cta = 'Вернуться к ожиданию'; }
  else if (s?.participants?.[state.user]?.energy) { title = 'Продолжим с того же места?'; cta = 'Продолжить выбор'; }
  return shell(`<section class="hero-home"><div class="hero-lockup"><p class="eyebrow">${esc(s?.title || 'Сегодня')}</p><h1>${title}</h1><p class="lede">Пара минут на настроение и реакции — дальше ищем фильм, который не придётся терпеть никому.</p></div>
    <div class="panel"><div class="presence" style="margin-bottom:1.5rem">${participantLine('lera')}${participantLine('nikita')}</div><button class="button large" data-action="continue-session">${cta}</button>${s?.status === 'choosing' && !s?.participants?.[state.user]?.energy ? '<button class="button ghost" data-view="quick">⚡ Быстрый вечер</button>' : ''}<p class="hint">${esc(catalogUpdatedText())} · тренды, популярное и классика</p></div>${inviteCard()}
  </section>`);
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
  if (!movie) return renderWaiting();
  return shell(`<section><div class="progress-line"><div class="track"><i style="width:${(progress/state.total)*100}%"></i></div><strong>${progress + 1} / ${state.total}</strong></div>
    <div class="swipe-stage"><article class="swipe-card" id="swipe-card" tabindex="0" aria-label="${esc(movie.title)}">
      <div class="poster-wrap"><img src="${movie.poster_url}" alt="Постер фильма ${esc(movie.title)}" draggable="false"><div class="poster-shade"></div><div class="poster-copy"><h2>${esc(movie.title)}</h2><div class="meta"><span>${movie.year}</span><span>•</span><span>${movie.genres.join(' · ')}</span><span>•</span><span>${movie.runtime} мин</span></div><p class="card-overview">${esc(movie.overview || 'Описание пока не добавлено')}</p></div></div>
      <div class="reaction-row">${reactionMap.map(([id,e,label]) => `<button class="reaction" data-reaction="${id}" title="${label}">${e}<span>${label}</span></button>`).join('')}</div>
      <p class="hint">← не хочу · ↑ обожаю · → нравится · ↓ норм · ? не смотрел(а)</p>
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

function renderResults() {
  const list = state.session?.recommendations || [];
  if (!list.length) return renderWaiting();
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
  return shell(`<section><div class="result-hero"><img src="${main.backdrop_url}" alt=""><div class="result-content"><span class="match">${main.match}% мэтч</span><p class="eyebrow">Кажется, у нас мэтч 🍿</p><h1>${esc(main.title)}</h1><div class="meta"><span>${main.year}</span><span>•</span><span>${main.runtime} мин</span><span>•</span><span>${main.genres.join(' · ')}</span><span>★ ${main.rating}</span></div><p class="lede" style="margin-top:1rem">${esc(main.overview)}</p><div class="footer-actions" style="justify-content:flex-start">${trailerButton(main)}</div></div></div>
    <h2 class="section-title">Почему выбрали этот фильм</h2><ul class="reason-list">${reasons.map(reason => `<li class="reason">✓ ${esc(reason)}</li>`).join('')}</ul>
    <div class="${stopGenresRespected ? 'filter-proof' : 'constraint-warning'}"><strong>${stopGenresRespected ? 'Стоп-жанры учтены ✓' : 'Этот вариант не прошёл проверку стоп-жанров'}</strong><p>${stopGenresRespected ? (excluded.length ? `В фильме нет: ${esc(excluded.join(', '))}.` : 'Сегодня вы не выбирали стоп-жанры.') : 'Начните выбор заново — такой фильм не должен попадать в результат.'}</p></div>
    ${relaxedText ? `<div class="constraint-warning"><strong>Немного расширили поиск</strong><p>${esc(relaxedText)}</p></div>` : ''}
    <details class="method"><summary>Как Tonight выбирает фильм</summary><p>Сначала убирает стоп-жанры, затем учитывает ваши сегодняшние реакции и ищет вариант, который подойдёт вам обоим.</p></details>
    <h2 class="section-title">Ещё может зайти</h2><div class="movie-rail">${list.slice(1,6).map(m => `<button class="mini-movie" data-movie="${m.id}"><img src="${m.poster_url}" alt=""><strong>${esc(m.title)}</strong><small>${m.match}% · ${m.year}</small><span class="mini-overview">${esc(m.overview || 'Короткое описание появится после обновления каталога')}</span></button>`).join('')}</div>
    <div class="killer"><div><p class="eyebrow">Никаких переговоров</p><h2>Компромисс найден.<br>Отношения спасены.</h2></div><div class="footer-actions"><button class="button large" data-action="accept-main" data-movie-id="${main.id}">✅ Да, смотрим это</button><button class="button secondary" data-action="save-later" data-movie-id="${main.id}">♡ На потом</button><button class="button secondary" data-action="choose">🎲 Выбери за нас</button><button class="button ghost" data-action="restart-session">↻ Выбрать заново</button></div></div>
  </section>`);
}

function renderSelected() {
  const movie = state.session?.selected;
  if (!movie) return renderResults();
  const traits = similarityTraits(movie);
  return shell(`<section class="selected-layout"><img class="selected-poster" src="${movie.poster_url}" alt="Постер ${esc(movie.title)}"><div><p class="eyebrow">Финальное решение</p><h1>${esc(movie.title)}</h1><div class="meta"><span>${movie.year}</span><span>•</span><span>${movie.runtime} мин</span><span>•</span><span>${movie.genres.join(' · ')}</span></div><p class="lede" style="margin-top:1.2rem">${esc(movie.overview)}</p><p class="hint">Будем смотреть? Если да — после просмотра оба поставят свою оценку, и Tonight учтёт её в следующих рекомендациях.</p><div class="footer-actions" style="justify-content:flex-start">${trailerButton(movie)}<button class="button large" data-action="watched">✅ Будем смотреть</button><button class="button secondary large" data-action="decline">✋ Не смотрим</button><button class="button ghost" data-action="choose-another">🎲 Другой вариант</button></div>
    <details class="avoid-box"><summary>🚫 Не предлагать похожее</summary><p>Это сильнее обычного «не смотрим». Ослабим в будущих рекомендациях:</p><ul><li><strong>Сочетание жанров:</strong> ${esc(traits.genres.join(', ') || 'как у этого фильма')}</li><li><strong>Настроение:</strong> ${esc(traits.moods.join(', ') || 'похожее')}</li>${traits.franchise ? '<li><strong>Франшизу:</strong> следующие части этой серии</li>' : ''}</ul><p class="hint">Целый жанр не будет заблокирован. Действие можно отменить в «Наш вкус».</p><button class="button secondary" data-action="confirm-avoid-similar">Подтвердить и выбрать другой</button></details>
    </div></section>`);
}

function renderFeedback() {
  const movie = state.session?.selected;
  return shell(`<section class="waiting"><div><p class="eyebrow">Запомним на будущее</p><h2>Ну как вам?</h2><p class="lede" style="margin-inline:auto">${esc(movie?.title || 'Этот фильм')}</p><div class="feedback-row">${feedbackMap.map(([e,label,value]) => `<button class="feedback" data-feedback="${value}">${e} ${label}</button>`).join('')}</div><p class="hint">Оценку второго увидишь после своей</p></div></section>`, {narrow:true});
}

function renderEveningFeedback() {
  const movie = state.session?.selected;
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
  return shell(`<section><div class="screen-head"><p class="eyebrow">Наша история 🍿</p><h2>Фильмы, которые уже стали нашими вечерами</h2></div>
    ${items.length ? Object.entries(groups).map(([month, movies]) => `<section><h3 class="section-title">${month}</h3><div class="history-grid">${movies.map(item => `<article class="history-card"><img src="${item.movie.poster_url}" alt=""><h3>${esc(item.movie.title)}</h3><div class="ratings">${names.lera} ${faces[item.ratings.lera] || '—'} · ${names.nikita} ${faces[item.ratings.nikita] || '—'}</div></article>`).join('')}</div></section>`).join('') : '<div class="empty">Здесь появится ваш первый совместный фильм 🍿</div>'}
  </section>`);
}

function renderWeekly() {
  const items = state.weeklyPicks || [];
  return shell(`<section><div class="screen-head"><p class="eyebrow">Пять на неделю ✦</p><h2>Можно выбрать без долгих поисков</h2><p class="lede">Короткая локальная подборка для вас двоих. Она обновится на следующей неделе.</p><p class="hint">Tonight ничего не отправляет сам — подборка ждёт здесь, когда понадобится.</p></div>${items.length ? `<div class="history-grid">${items.map((movie, index) => `<article class="history-card"><img src="${movie.poster_url}" alt=""><p class="eyebrow">${index + 1} из 5</p><h3>${esc(movie.title)}</h3><p class="hint">${movie.year} · ${movie.runtime} мин · ${esc(movie.genres.join(' · '))}</p><p class="hint">${esc(movie.weekly_reason)}</p><div class="footer-actions">${trailerButton(movie, 'button secondary')}<button class="button" data-action="select-weekly" data-movie-id="${movie.id}">Выбрать на сегодня</button></div></article>`).join('')}</div>` : '<div class="empty"><h3>Пока подбираем варианты</h3><p>Откройте экран ещё раз через минуту.</p></div>'}</section>`);
}

function renderFranchises() {
  const groups = state.franchises || [];
  const card = group => `<section class="profile-actions"><h3>${esc(group.title)}</h3><p class="hint">Уже посмотрели вместе: ${group.watched_count} из ${group.parts.length}</p><div class="choice-stack">${group.parts.map(part => `<div class="taste-item"><span><strong>${part.franchise_order ? `${part.franchise_order}. ` : ''}${esc(part.title)}</strong><small>${part.watched ? 'Уже посмотрели вместе' : part.released === false ? 'Ещё не вышел в прокат' : part.available ? 'Можно выбрать следующим' : 'Сначала нужна предыдущая часть'}</small></span>${part.available && !part.watched ? `<button class="button ghost small" data-action="select-franchise" data-movie-id="${part.id}">Выбрать на сегодня</button>` : ''}</div>`).join('')}</div>${group.next_movie ? `<p class="hint">Следующая доступная часть: ${esc(group.next_movie.title)}. Это только подсказка — можно выбрать любой фильм.</p>` : '<p class="hint">Пока следующую часть не подсказываем: сначала должна выйти и стать доступной следующая часть серии.</p>'}</section>`;
  return shell(`<section><div class="screen-head"><p class="eyebrow">Серии фильмов ≡</p><h2>Смотреть по порядку — если хочется</h2><p class="lede">Здесь отмечены только фильмы, которые вы посмотрели вместе в Tonight.</p><p class="hint">Это не обязательный маршрут: серия не ограничивает обычный выбор.</p></div>${groups.length ? groups.map(card).join('') : '<div class="empty"><h3>Серий пока нет</h3><p>Когда в локальном каталоге появятся части одной истории, порядок будет здесь.</p></div>'}</section>`);
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
  const cards = visibleItems.length ? `<div class="history-grid">${visibleItems.map(movie => `<article class="history-card"><img src="${movie.poster_url}" alt=""><h3>${esc(movie.title)}</h3><p class="hint">${esc(movie.overview || 'Описание появится после обновления каталога')}</p>${movie.fits_tonight === true ? '<p class="hint">✓ Подходит под сегодняшний план</p>' : ''}${movie.franchise_warning ? `<p class="hint">⚠ ${esc(movie.franchise_warning)}</p>` : ''}${movie.saved_by ? `<p class="hint">Добавил(а): ${esc(names[movie.saved_by])}</p>` : ''}${movie.deferred_reason ? `<p class="hint">Отложили: ${esc(movie.deferred_reason)}</p>` : ''}<div class="footer-actions">${trailerButton(movie, 'button secondary')}<button class="button" data-action="watch-saved" data-movie-id="${movie.id}">✅ Будем смотреть</button><button class="button ghost" data-action="remove-later" data-movie-id="${movie.id}">Убрать</button></div></article>`).join('')}</div>` : `<div class="empty compact"><h3>Ничего не нашли</h3><p>Попробуйте другое слово или жанр.</p><button class="button ghost" data-action="reset-watchlist-filters">Сбросить фильтры</button></div>`;
  return shell(`<section><div class="screen-head"><p class="eyebrow">Общий список ♡</p><h2>На потом</h2><p class="lede">Варианты, которые понравились, но не подошли именно сегодня.</p>${items.some(movie => movie.fits_tonight !== null) ? '<p class="hint">Сначала — то, что подходит под сегодняшний план. Остальные фильмы остаются в списке.</p>' : ''}</div>${items.length ? `${filters}${cards}` : '<div class="empty"><h3>Пока пусто</h3><p>Сохраняйте подходящие фильмы из результатов, чтобы вернуться к ним в другой вечер.</p></div>'}</section>`);
}

function renderSearch() {
  const items = state.searchResults || [];
  return shell(`<section><div class="screen-head"><p class="eyebrow">Поиск по примеру</p><h2>На что похоже настроение?</h2><p class="lede">Напишите название, жанр или деталь — например, «Как Достать ножи» или «смешное на полтора часа».</p></div><form class="search-form" data-action="search-catalog"><input name="query" value="${esc(state.searchQuery)}" placeholder="Название или пример фильма" maxlength="100"><button class="button" type="submit">Найти</button></form>${state.searchQuery ? (items.length ? `<div class="history-grid">${items.map(movie => `<article class="history-card"><img src="${movie.poster_url}" alt=""><h3>${esc(movie.title)}</h3><p class="hint">${movie.year} · ${esc(movie.genres.join(' · '))}</p><p class="hint">${esc(movie.overview)}</p><div class="footer-actions">${trailerButton(movie, 'button secondary')}<button class="button secondary" data-action="select-search-result" data-movie-id="${movie.id}">Выбрать на сегодня</button></div></article>`).join('')}</div>` : '<div class="empty"><p>В локальном каталоге ничего похожего не нашли. Попробуйте название или более короткий запрос.</p></div>') : ''}</section>`);
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
    <section class="profile-actions"><h2 class="section-title">Мой профиль вкуса</h2><p class="lede">Если выводы Tonight стали неактуальны, начните обучение заново. История просмотров и ваши оценки останутся на месте.</p><button class="button ghost" data-action="reset-taste-profile">Начать заново</button></section>
    ${!isRemoteClient() ? `<section class="profile-actions"><h2 class="section-title">Резервные копии</h2><p class="lede">Скачайте данные, чтобы перенести их на другой компьютер или сохранить отдельно. Перед восстановлением Tonight автоматически сделает страховочную копию текущих данных.</p><p class="hint">${latestBackup}</p><div class="footer-actions"><button class="button ghost" data-action="create-backup">Создать копию</button><button class="button ghost" data-action="export-data">Скачать данные</button></div><div class="backup-import"><label>Восстановить из файла <input type="file" data-backup-import accept=".db,application/vnd.sqlite3"></label><button class="button secondary" data-action="import-backup" disabled>Восстановить из файла</button></div>${backupList}</section>` : ''}
    ${!isRemoteClient() ? '<section class="profile-actions privacy-actions"><h2 class="section-title">Личные данные</h2><p class="lede">Можно полностью удалить историю, оценки, реакции, список «На потом», выученный вкус и локальные резервные копии. Каталог, постеры и настройка TMDB останутся.</p><details class="setup-help"><summary>Как Tonight обращается с данными</summary><p>История, реакции и оценки хранятся только на этом компьютере. Tonight не отправляет их разработчику и не использует телеметрию.</p><p>Интернет нужен только для публичного каталога TMDB. Личные предпочтения к этим запросам не добавляются.</p></details><button class="button ghost danger" data-action="open-privacy-delete">Удалить личные данные</button></section>' : ''}
    <section class="avoidances"><h2 class="section-title">Не предлагать похожее</h2><p class="lede">Личные сильные отказы текущего зрителя. Они снижают похожие варианты, но не блокируют жанр целиком.</p>${avoidances.length ? `<div class="avoidance-list">${avoidances.map(rule => `<article><div><strong>${esc(rule.title)}</strong><p>${esc(rule.genres.slice(0,3).join(' · '))}${rule.franchise_key ? ' · включая франшизу' : ''}</p></div><button class="button ghost" data-action="remove-avoidance" data-rule-id="${rule.id}">Отменить</button></article>`).join('')}</div>` : '<div class="empty compact"><p>Сильных отказов пока нет.</p></div>'}</section>
  </section>`);
}

function renderError() {
  return shell(`<section class="waiting"><div><p class="eyebrow">Техническая пауза</p><h2>Tonight не смог загрузиться</h2><p class="lede">${esc(state.error || 'Проверьте, что сервер всё ещё запущен.')}</p><button class="button" data-action="retry">Попробовать снова</button></div></section>`, {nav:false});
}

function bindCommon() {
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
  root.querySelector('[data-watchlist-search]')?.addEventListener('input', event => { state.watchlistQuery=event.target.value; render(); });
  root.querySelector('[data-watchlist-genre]')?.addEventListener('change', event => { state.watchlistGenre=event.target.value; render(); });
  root.querySelector('[data-action="reset-watchlist-filters"]')?.addEventListener('click', () => { state.watchlistQuery=''; state.watchlistGenre=''; render(); });
  root.querySelector('[data-action="choose-another"]')?.addEventListener('click', chooseAnother);
  root.querySelector('[data-action="watched"]')?.addEventListener('click', watched);
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
  root.querySelector('[data-action="skip-evening-feedback"]')?.addEventListener('click', () => { state.view='home'; render(); });
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
  state.modal = null;
  if (view === 'home') { state.view='home'; render(); return; }
  if (view === 'vibe') { state.view='vibe'; render(); return; }
  if (view === 'quick') { state.view='quick'; render(); return; }
  try {
    if (view === 'history') { state.history = (await api('/api/history')).items; state.view='history'; render(); return; }
    if (view === 'weekly') { state.weeklyPicks = (await api('/api/weekly-picks')).items; state.view='weekly'; render(); return; }
    if (view === 'franchises') { state.franchises = (await api('/api/franchises')).items; state.view='franchises'; render(); return; }
    if (view === 'diagnostics') { const usageRequest = isRemoteClient() ? null : api('/api/usage-summary').catch(() => null); const [diagnostics, usage] = await Promise.all([api('/api/diagnostics'), usageRequest]); state.diagnostics=diagnostics; state.usageSummary=usage; state.view='diagnostics'; render(); return; }
    if (view === 'taste') { const backupRequest = isRemoteClient() ? null : api('/api/backups'); const [taste, backups] = await Promise.all([api('/api/taste'), backupRequest]); state.taste = taste; state.backups = backups?.items || []; state.view='taste'; render(); }
    if (view === 'search') { state.view='search'; render(); }
    if (view === 'watchlist') { state.watchlist = (await api('/api/watchlist')).items; state.view='watchlist'; render(); }
  } catch (e) { toast(e.message); }
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
    if (state.session.status === 'selected') state.view='selected';
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
    if (e.target.closest('button')) return;
    active=true; startX=e.clientX; card.setPointerCapture(e.pointerId);
  });
  card.addEventListener('pointermove', e => { if(!active)return; dx=e.clientX-startX; card.style.transform=`translateX(${dx}px) rotate(${dx/25}deg)`; });
  card.addEventListener('pointerup', () => { if(!active)return; active=false; if(Math.abs(dx)>90) react(dx>0?'like':'dislike'); else card.style.transform=''; dx=0; });
  card.addEventListener('pointercancel', () => { active=false; dx=0; card.style.transform=''; });
  card.addEventListener('keydown', e => { const map={ArrowLeft:'dislike',ArrowRight:'like',ArrowUp:'love',ArrowDown:'okay','?':'unseen'}; if(map[e.key]){e.preventDefault();react(map[e.key]);} });
}

async function choose() {
  const button=document.querySelector('[data-action="choose"]'); if(button)button.disabled=true;
  document.querySelector('.result-hero')?.classList.add('roulette');
  try { const movie=await api(`/api/sessions/${state.session.id}/choose`,{method:'POST'}); await new Promise(r=>setTimeout(r,1400)); state.session.selected=movie; state.session.status='selected'; state.view='selected'; render(); }
  catch(e){toast(e.message); if(button)button.disabled=false;}
}

async function acceptMainRecommendation(movieId) {
  if (!movieId) return;
  try {
    const movie = await api(`/api/sessions/${state.session.id}/select/${encodeURIComponent(movieId)}`, {method:'POST'});
    state.session.selected = movie; state.session.status = 'selected'; state.view = 'selected'; render();
  } catch (e) { toast(e.message); }
}

async function chooseAnother() {
  try { const movie=await api(`/api/sessions/${state.session.id}/choose-another`,{method:'POST'}); state.session.selected=movie; render(); toast('Другой вариант — без повторов'); }
  catch(e){toast('Хорошие варианты закончились — начните новый вечер');}
}

async function watched() {
  try { const result=await api(`/api/sessions/${state.session.id}/watched`,{method:'POST'}); state.historyId=result.history_id; state.view='feedback'; render(); }
  catch(e) { toast(e.message); }
}

async function declineMovie() {
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
  try { await api(`/api/history/${state.historyId}/feedback`,{method:'POST',body:JSON.stringify({user_id:state.user,rating})}); state.view='eveningFeedback'; render(); }
  catch(e) { toast(e.message); }
}

async function saveEveningFeedback(fit) {
  try { await api(`/api/history/${state.historyId}/evening-feedback`,{method:'POST',body:JSON.stringify({user_id:state.user,fit})}); toast('Запомнили. Следующий выбор станет точнее'); state.view='home'; render(); }
  catch(e) { toast(e.message); }
}

async function searchCatalog(query) {
  state.searchQuery = String(query || '').trim();
  if (!state.searchQuery) { state.searchResults=[]; render(); return; }
  try { state.searchResults = (await api(`/api/movies/search?q=${encodeURIComponent(state.searchQuery)}`)).items; render(); }
  catch(e) { toast(e.message); }
}

async function selectSearchResult(movieId) {
  try { const movie=await api(`/api/sessions/${state.session.id}/select-catalog/${encodeURIComponent(movieId)}`,{method:'POST'}); state.session.selected=movie; state.session.status='selected'; state.view='selected'; render(); }
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
    state.session.selected = movie; state.session.status = 'selected'; state.view = 'selected'; render();
  } catch (e) { toast(e.message); }
}

function renderModal() {
  const old=document.querySelector('.modal-backdrop'); old?.remove();
  if(!state.modal)return; const m=state.modal;
  const node=document.createElement('div'); node.className='modal-backdrop'; node.innerHTML=`<div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-layout"><img src="${m.poster_url}" alt=""><div><span class="match">${m.match}% мэтч</span><h2 id="modal-title">${esc(m.title)}</h2><div class="meta">${m.year} · ${m.runtime} мин · ${m.genres.join(' · ')}</div><p class="lede" style="margin-top:1rem">${esc(m.overview)}</p><button class="button secondary" data-close>Закрыть</button></div></div></div>`;
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
  if (!nextSession) return;
  if (nextSession.status === 'abandoned') { followRestartedSession(); return; }
  state.session = nextSession;
  if (nextSession.status === 'recommended' && state.view === 'waiting') state.view = 'results';
  if (nextSession.status === 'selected' && ['results','waiting'].includes(state.view)) state.view = 'selected';
  if (nextSession.status === 'completed') openPendingFeedback();
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
    render();
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
  ws.onmessage=e=>{ const data=JSON.parse(e.data); if(data.type==='privacy_reset'){forgetLocalViewer();state.ws=null;toast('Личные данные удалены на основном компьютере');setTimeout(()=>location.reload(),700);return;} if(!data.presence && !data.session) return; if(data.presence)state.presence=data.presence; if(data.session)applyRealtimeSession(data.session); render(); };
  ws.onerror=()=>{};
  ws.onclose=event=>{clearInterval(ws.pinger); if(state.ws!==ws)return; if(event.code===1008 && isRemoteClient()){state.user=null;state.accessCode='';localStorage.removeItem('tonight:user');sessionStorage.removeItem('tonight:access-code');state.view='home';toast('Нужен код с экрана Tonight');render();return;} state.connected=false;state.wasDisconnected=true;render();const delay=Math.min(12000,1200*(2**Math.min(state.reconnectAttempts,3)));state.reconnectAttempts+=1;state.reconnectTimer=setTimeout(()=>{if(state.user&&state.ws===ws)connectWs();},delay);};
}

async function openPendingFeedback() {
  if (!state.user || !state.session) return;
  try {
    const history = await api('/api/history');
    const pending = history.items.find(item => item.session_id === state.session.id && item.ratings[state.user] == null);
    if (pending) { state.historyId = pending.history_id; state.view = 'feedback'; render(); }
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
      if (state.session.status === 'completed') {
        const history = await api('/api/history');
        const pending = history.items.find(item => item.session_id === state.session.id && item.ratings[state.user] == null);
        if (pending) { state.historyId = pending.history_id; state.view = 'feedback'; }
      }
      connectWs();
    }
    render();
  } catch(e) { state.error=e.message; state.view='error'; render(); }
}

init();
