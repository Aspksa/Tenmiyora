(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const {clamp, position, normalized} = window.TenmiyoraLayout;
  const avatar = $('avatar'), chat = $('chat-window'), settings = $('settings-window');
  let state = {appearance: {size: 340, opacity: 100, visible: true, pinned: false, motion: true}, layout: {}, messages: [], connection: {url: 'https://foundation-models.api.cloud.ru/v1', model: '', has_key: false}};
  let ready = false, pending = false, saveTimer, toastTimer, saveQueue = Promise.resolve(), layer = 50;
  let lastChatFocus = null, lastSettingsFocus = null, connectionSaveQueue = Promise.resolve();
  const CLOUDRU_URL = 'https://foundation-models.api.cloud.ru/v1';
  const isTouch = matchMedia('(pointer: coarse)').matches;
  function viewport() { return {width: document.documentElement.clientWidth, height: window.visualViewport ? Math.min(innerHeight, visualViewport.height) : innerHeight}; }
  async function api(path, body) {
    const response = await fetch('/api/' + path, {method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-Tenmiyora-Client': 'web'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    let result;
    try { result = await response.json(); } catch { throw new Error('Сервер недоступен. Запустите Tenmiyora.bat и откройте страницу из трея.'); }
    if (!response.ok) throw new Error(result.error || 'Не удалось выполнить действие.');
    return result;
  }
  function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4200); }
  function scheduleSave() {
    if (!ready) return;
    $('save-status').textContent = 'Сохранение…';
    clearTimeout(saveTimer); saveTimer = setTimeout(flushSave, 260);
  }
  function flushSave() {
    clearTimeout(saveTimer);
    const payload = {appearance: {...state.appearance}, layout: structuredClone(state.layout)};
    saveQueue = saveQueue.catch(() => {}).then(() => api('preferences', payload)).then(() => { $('save-status').textContent = 'Сохранено на этом компьютере'; }).catch((error) => { $('save-status').textContent = 'Не сохранено — повторите изменение'; toast(error.message); });
    return saveQueue;
  }
  function fallbackFor(name, width, height) {
    const vp = viewport(), mobile = vp.width < 760;
    if (name === 'avatar') {
      if (vp.width < 470) return {x: vp.width - width - 18, y: 285};
      return {x: vp.width - width - (vp.width > 1100 ? 83 : 28), y: 185};
    }
    if (name === 'chat') return {x: mobile ? (vp.width - width) / 2 : 285, y: mobile ? (vp.height - height) / 2 : 123};
    return {x: vp.width - width - 24, y: mobile ? (vp.height - height) / 2 : 106};
  }
  function place(element, name) {
    const vp = viewport(), rect = element.getBoundingClientRect();
    const point = position(state.layout[name], rect.width, rect.height, vp.width, vp.height, fallbackFor(name, rect.width, rect.height));
    element.style.left = point.x + 'px'; element.style.top = point.y + 'px'; element.style.right = 'auto';
  }
  function remember(element, name) {
    const rect = element.getBoundingClientRect(), vp = viewport();
    state.layout[name] = normalized(rect.left, rect.top, rect.width, rect.height, vp.width, vp.height);
    scheduleSave();
  }
  function fitWindows() { place(avatar, 'avatar'); if (!chat.hidden) place(chat, 'chat'); if (!settings.hidden) place(settings, 'settings'); }
  function applyAppearance() {
    const a = state.appearance, vp = viewport();
    const maxSize = Math.min(vp.width - 16, vp.height - 45);
    const width = Math.min(a.size, maxSize, vp.width < 470 ? 200 : vp.width < 760 ? 245 : 500);
    avatar.style.width = width + 'px'; avatar.style.height = width + 'px'; avatar.style.opacity = String(a.opacity / 100);
    avatar.hidden = !a.visible; $('avatar-restore').hidden = a.visible;
    avatar.classList.toggle('motion', a.motion); avatar.classList.toggle('pinned', a.pinned);
    $('avatar-size').max = Math.floor(Math.min(maxSize, vp.width < 470 ? 200 : vp.width < 760 ? 245 : 500) / 10) * 10;
    $('avatar-size').value = Math.round(width / 10) * 10; $('avatar-size-value').textContent = Math.round(width) + ' px';
    $('avatar-opacity').value = a.opacity; $('avatar-opacity-value').textContent = a.opacity + '%';
    $('avatar-visible').checked = a.visible; $('avatar-pinned').checked = a.pinned; $('avatar-motion').checked = a.motion;
    place(avatar, 'avatar');
  }
  function front(element) { element.style.zIndex = ++layer; }
  function makeDraggable(element, handle, name, enabled = () => true) {
    let start = null, moved = false, consumedClick = false, holdTimer;
    handle.addEventListener('pointerdown', (event) => {
      if (event.button !== 0 || event.target.closest('a,input,textarea,select') || (name !== 'avatar' && event.target.closest('button'))) return;
      front(element); moved = false;
      const rect = element.getBoundingClientRect();
      start = {id: event.pointerId, x: event.clientX, y: event.clientY, left: rect.left, top: rect.top};
      handle.setPointerCapture(event.pointerId);
      if (name === 'avatar' && event.pointerType !== 'mouse') holdTimer = setTimeout(() => { consumedClick = true; start = null; openSettings(); }, 650);
    });
    handle.addEventListener('pointermove', (event) => {
      if (!start || event.pointerId !== start.id) return;
      const dx = event.clientX - start.x, dy = event.clientY - start.y;
      if (Math.hypot(dx, dy) < 6 && !moved) return;
      clearTimeout(holdTimer);
      if (!enabled()) return;
      moved = true; consumedClick = true;
      element.classList.add('dragging'); handle.classList.add('dragging');
      const vp = viewport(), rect = element.getBoundingClientRect();
      element.style.left = clamp(start.left + dx, 8, Math.max(8, vp.width - rect.width - 8)) + 'px';
      element.style.top = clamp(start.top + dy, 8, Math.max(8, vp.height - rect.height - 8)) + 'px';
      element.style.right = 'auto';
    });
    function finish(event) {
      clearTimeout(holdTimer);
      if (start && event.pointerId === start.id && moved) remember(element, name);
      start = null; element.classList.remove('dragging'); handle.classList.remove('dragging');
    }
    handle.addEventListener('pointerup', finish);
    handle.addEventListener('pointercancel', finish);
    handle.addEventListener('lostpointercapture', finish);
    handle.addEventListener('click', (event) => { if (consumedClick) { event.preventDefault(); event.stopImmediatePropagation(); consumedClick = false; } }, true);
  }
  makeDraggable(avatar, avatar, 'avatar', () => !state.appearance.pinned);
  makeDraggable(chat, $('chat-handle'), 'chat');
  makeDraggable(settings, $('settings-handle'), 'settings');
  avatar.addEventListener('click', () => openChat());
  avatar.addEventListener('contextmenu', (event) => { event.preventDefault(); openSettings(); });
  avatar.addEventListener('keydown', (event) => { if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) { event.preventDefault(); openSettings(); } });
  $('avatar-restore').addEventListener('click', () => { state.appearance.visible = true; applyAppearance(); scheduleSave(); });
  function openChat() { if (chat.hidden) lastChatFocus = document.activeElement; chat.hidden = false; place(chat, 'chat'); front(chat); renderMessages(); $('chat-input').focus({preventScroll: true}); }
  function closeChat() { chat.hidden = true; if (lastChatFocus && lastChatFocus.isConnected) lastChatFocus.focus({preventScroll: true}); }
  function selectTab(name) {
    for (const tab of document.querySelectorAll('[data-tab]')) { const active = tab.dataset.tab === name; tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1; }
    $('appearance-panel').hidden = name !== 'appearance'; $('connection-panel').hidden = name !== 'connection';
  }
  function openSettings(tab = 'appearance') { if (settings.hidden) lastSettingsFocus = document.activeElement; selectTab(tab); settings.hidden = false; place(settings, 'settings'); front(settings); $('tab-' + tab).focus({preventScroll: true}); }
  function closeSettings() { settings.hidden = true; if (lastSettingsFocus && lastSettingsFocus.isConnected) lastSettingsFocus.focus({preventScroll: true}); }
  $('chat-close').addEventListener('click', closeChat); $('settings-close').addEventListener('click', closeSettings);
  document.querySelectorAll('[data-action]').forEach((button) => button.addEventListener('click', () => { const action = button.dataset.action; if (action === 'chat') openChat(); else openSettings(action === 'connection' ? 'connection' : 'appearance'); }));
  document.querySelectorAll('[data-tab]').forEach((tab) => {
    tab.addEventListener('click', () => selectTab(tab.dataset.tab));
    tab.addEventListener('keydown', (event) => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const name = tab.dataset.tab === 'appearance' ? 'connection' : 'appearance'; selectTab(name); $('tab-' + name).focus(); } });
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') { if (!settings.hidden && (chat.hidden || Number(settings.style.zIndex) > Number(chat.style.zIndex))) closeSettings(); else if (!chat.hidden) closeChat(); } });
  for (const element of [chat, settings]) element.addEventListener('pointerdown', () => front(element));
  function route() {
    const requested = location.hash.slice(1);
    const view = ['home', 'brain', 'disk', 'settings'].includes(requested) ? requested : 'home';
    for (const name of ['home', 'brain', 'disk', 'settings']) $(name + '-view').hidden = view !== name;
    $('page-title').textContent = ({home: 'Главная', brain: 'Мозг Tenmiyora', disk: 'Диск Tenmiyora', settings: 'Настройки'})[view];
    document.querySelectorAll('[data-nav]').forEach((item) => { item.classList.toggle('active', item.dataset.nav === view); if (item.dataset.nav === view) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current'); });
    window.TenmiyoraModules?.show(view);
  }
  window.addEventListener('hashchange', route); route();
  for (const [id, property] of [['avatar-size', 'size'], ['avatar-opacity', 'opacity']]) $(id).addEventListener('input', () => { state.appearance[property] = Number($(id).value); applyAppearance(); scheduleSave(); });
  for (const [id, property] of [['avatar-visible', 'visible'], ['avatar-pinned', 'pinned'], ['avatar-motion', 'motion']]) $(id).addEventListener('change', () => { state.appearance[property] = $(id).checked; applyAppearance(); scheduleSave(); });
  $('reset-layout').addEventListener('click', () => { state.layout = {}; state.appearance.size = 340; state.appearance.opacity = 100; state.appearance.visible = true; state.appearance.pinned = false; applyAppearance(); fitWindows(); scheduleSave(); toast('Исходное расположение восстановлено'); });
  function currentProvider() { return $('api-provider').value; }
  function fillModelOptions() {
    const select = $('api-model-select'), saved = $('api-model').value.trim();
    select.replaceChildren();
    const placeholder = new Option((state.model_cache?.models || []).length ? 'Выберите модель для чата' : 'Сначала загрузите модели', '');
    select.append(placeholder);
    const details = state.model_cache?.details || (state.model_cache?.models || []).map(id => ({id, kind: 'unknown', hint: 'Тип не указан API'}));
    const groups = {chat: document.createElement('optgroup'), unknown: document.createElement('optgroup'), other: document.createElement('optgroup')};
    groups.chat.label = 'Диалоговые модели'; groups.unknown.label = 'Тип не указан — возможна поддержка чата'; groups.other.label = 'Другие задачи — не для обычного чата';
    for (const item of details) {
      const option = new Option(item.id, item.id); option.title = item.hint;
      option.disabled = item.kind === 'other'; (groups[item.kind] || groups.unknown).append(option);
    }
    for (const group of Object.values(groups)) if (group.children.length) select.append(group);
    select.append(new Option('Указать идентификатор вручную…', '__manual__'));
    const match = details.find(item => item.id === saved && item.kind !== 'other');
    select.value = saved ? (match ? saved : '__manual__') : '';
    $('manual-model-field').hidden = select.value !== '__manual__'; updateModelDescription();
  }
  function updateModelDescription() {
    const id = $('api-model').value.trim();
    const item = (state.model_cache?.details || []).find(model => model.id === id);
    $('model-description').textContent = item ? item.hint : (id ? 'Идентификатор указан вручную. Поддержка чата определяется провайдером.' : 'Загрузите список из вашего API-аккаунта и выберите текстовую модель.');
  }
  function renderConnection(updateForm = false) {
    const connection = state.connection, configured = Boolean(connection.model && connection.has_key);
    if (updateForm) {
      $('api-provider').value = connection.url === CLOUDRU_URL ? 'cloudru' : 'custom';
      $('api-url').value = connection.url; $('api-model').value = connection.model;
      $('custom-url-field').hidden = currentProvider() === 'cloudru';
      $('api-url').required = currentProvider() !== 'cloudru';
      $('provider-name').textContent = currentProvider() === 'cloudru' ? 'Cloud.ru' : 'Ваш провайдер';
      $('provider-subtitle').textContent = currentProvider() === 'cloudru' ? 'Foundation Models · подключение чата' : 'Совместимый API · подключение чата';
      fillModelOptions();
    }
    $('key-status').textContent = connection.has_key ? 'СОХРАНЁН' : '';
    $('api-key').placeholder = connection.has_key ? 'Ключ сохранён' : 'Введите API-ключ';
    $('delete-key').disabled = !connection.has_key;
    $('connection-hint').hidden = configured;
    $('chat-model-status').textContent = configured ? (connection.url === CLOUDRU_URL ? 'Cloud.ru · ' : '') + connection.model : 'Модель ещё не подключена';
    $('send-message').disabled = !configured || pending;
    $('composer-hint').textContent = configured ? (isTouch ? 'Ваше сообщение для Tenmiyora' : 'Enter — отправить · Shift+Enter — новая строка') : 'Сначала подключите модель в настройках';
    $('connection-summary').textContent = !connection.has_key ? 'Ключ ещё не сохранён' : !connection.model ? 'Ключ сохранён. Выберите модель для чата.' : connection.verified_at ? 'API проверен ' + new Date(connection.verified_at).toLocaleString('ru-RU') + '. Модель: ' + connection.model : 'Ключ и модель сохранены. Можно отправить сообщение или проверить доступ к API.';
  }
  function renderMessages(extra) {
    const log = $('chat-messages'); log.replaceChildren();
    if (!state.messages.length && !extra) {
      const empty = document.createElement('div'); empty.className = 'chat-empty';
      const star = document.createElement('div'); star.className = 'empty-star'; star.textContent = '✧';
      const title = document.createElement('h3'); title.textContent = 'Я здесь. Расскажите.';
      const hint = document.createElement('p'); hint.textContent = 'Идея, вопрос или просто мысль — начните с того, что сейчас важно.';
      const suggestions = document.createElement('div'); suggestions.className = 'chat-suggestions';
      for (const [label, text] of [['Есть идея', 'Помоги мне развить идею: '], ['Нужен план', 'Помоги составить план: ']]) { const button = document.createElement('button'); button.type = 'button'; button.textContent = label; button.addEventListener('click', () => { $('chat-input').value = text; $('chat-input').focus(); }); suggestions.append(button); }
      empty.append(star, title, hint, suggestions); log.append(empty);
    }
    for (const message of [...state.messages, ...(extra ? [extra] : [])]) {
      const article = document.createElement('article'); article.className = 'message ' + message.role;
      const name = document.createElement('span'); name.className = 'message-name'; name.textContent = message.role === 'user' ? 'Вы' : 'Tenmiyora';
      const body = document.createElement('div'); body.className = 'message-body'; body.textContent = message.content;
      article.append(name, body);
      if (message.finish_reason === 'length') { const warning = document.createElement('small'); warning.className = 'provider-limit-note'; warning.textContent = 'Ответ остановлен по лимиту провайдера. Можно попросить модель продолжить.'; article.append(warning); }
      if (message.time) { const time = document.createElement('time'); time.dateTime = message.time; time.textContent = new Date(message.time).toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'}); article.append(time); }
      log.append(article);
    }
    log.scrollTop = log.scrollHeight;
    const count = state.messages.length, ending = count % 10, teens = count % 100;
    const noun = ending === 1 && teens !== 11 ? 'сообщение' : ending >= 2 && ending <= 4 && (teens < 12 || teens > 14) ? 'сообщения' : 'сообщений';
    $('conversation-summary').textContent = count ? count + ' ' + noun + ' · история сохранена' : 'Ваш первый разговор ждёт вас';
  }
  async function sendMessage(event) {
    event.preventDefault(); const content = $('chat-input').value.trim();
    if (!content || pending) return;
    if (!state.connection.has_key || !state.connection.model) { openSettings('connection'); return; }
    pending = true; $('chat-input').value = ''; state.messages.push({role: 'user', content, time: new Date().toISOString()}); renderMessages({role: 'pending', content: 'Tenmiyora обдумывает ответ…'}); renderConnection();
    try { const result = await api('chat', {message: content}); state.messages = result.messages; renderMessages(); }
    catch (error) { try { const latest = await api('state'); state.messages = latest.messages; } catch { /* Keep the visible message if the server is unavailable. */ } renderMessages({role: 'error', content: error.message}); $('chat-input').value = content; }
    finally { pending = false; renderConnection(); }
  }
  $('chat-form').addEventListener('submit', sendMessage);
  $('chat-input').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !isTouch) { event.preventDefault(); $('chat-form').requestSubmit(); } });
  $('clear-chat').addEventListener('click', async () => { if (pending) { toast('Дождитесь ответа модели'); return; } if (!state.messages.length) return; if (!confirm('Удалить историю этого разговора?')) return; try { await api('clear-chat', {}); state.messages = []; renderMessages(); toast('История разговора очищена'); } catch (error) { toast(error.message); } });
  async function saveConnection() {
    const payload = {provider: currentProvider(), url: currentProvider() === 'cloudru' ? CLOUDRU_URL : $('api-url').value.trim(), model: $('api-model').value.trim(), ...($('api-key').value ? {key: $('api-key').value.trim()} : {})};
    connectionSaveQueue = connectionSaveQueue.catch(() => {}).then(() => api('connection', payload)).then(result => { state.connection = result.connection; state.model_cache = result.model_cache; $('api-key').value = ''; renderConnection(true); return result; });
    return connectionSaveQueue;
  }
  function connectionResult(text, error = false) { $('connection-result').textContent = text; $('connection-result').classList.toggle('error', error); }
  async function withConnectionBusy(action) {
    const buttons = [...$('connection-form').querySelectorAll('button')];
    buttons.forEach(item => { item.disabled = true; });
    try { await action(); } catch (error) { connectionResult(error.message, true); }
    finally { buttons.forEach(item => { item.disabled = false; }); $('delete-key').disabled = !state.connection.has_key; }
  }
  $('api-provider').addEventListener('change', () => {
    const cloud = currentProvider() === 'cloudru'; $('custom-url-field').hidden = cloud; $('api-url').required = !cloud;
    $('provider-name').textContent = cloud ? 'Cloud.ru' : 'Ваш провайдер'; $('provider-subtitle').textContent = cloud ? 'Foundation Models · подключение чата' : 'Совместимый API · подключение чата';
    $('api-key').value = '';
    if (cloud) $('api-url').value = CLOUDRU_URL;
    else if (state.connection.url !== CLOUDRU_URL) $('api-url').value = state.connection.url;
    else $('api-url').value = '';
    $('api-model').value = ''; $('api-model-select').replaceChildren(new Option('Сначала загрузите модели', ''), new Option('Указать идентификатор вручную…', '__manual__')); $('manual-model-field').hidden = true;
    connectionResult('Укажите ключ для выбранного провайдера и сохраните подключение.');
  });
  $('api-model-select').addEventListener('change', async () => {
    const value = $('api-model-select').value; $('manual-model-field').hidden = value !== '__manual__';
    if (value === '__manual__') { $('api-model').focus(); return; }
    $('api-model').value = value; updateModelDescription();
    if (!value) return;
    try { await saveConnection(); connectionResult('Модель выбрана и сохранена. Чат использует её.'); }
    catch (error) { connectionResult(error.message, true); }
  });
  $('api-model').addEventListener('input', updateModelDescription);
  $('connection-form').addEventListener('submit', async (event) => { event.preventDefault(); await withConnectionBusy(async () => { await saveConnection(); connectionResult(state.connection.has_key && state.connection.model ? 'Ключ и модель сохранены. Чат использует выбранный API.' : 'Настройки сохранены. Для ответов нужны API-ключ и выбранная модель.'); toast('Настройки подключения сохранены'); }); });
  $('delete-key').addEventListener('click', () => withConnectionBusy(async () => { await connectionSaveQueue.catch(() => {}); const result = await api('delete-key', {}); state.connection = result.connection; state.model_cache = result.model_cache; $('api-key').value = ''; renderConnection(true); connectionResult('API-ключ удалён с этого компьютера.'); }));
  $('load-models').addEventListener('click', () => withConnectionBusy(async () => {
    connectionResult('Получение списка моделей…'); await saveConnection(); const result = await api('models', {}); state.model_cache = result; fillModelOptions();
    connectionResult('Получено моделей: ' + result.models.length + '. Выберите модель в списке. Модели других задач отмечены отдельно.'); $('api-model-select').focus();
  }));
  $('check-connection').addEventListener('click', () => withConnectionBusy(async () => {
    connectionResult('Проверка доступа к API…'); await saveConnection(); const result = await api('check-connection', {}); state.connection = result.connection; state.model_cache = result.model_cache; renderConnection(true); connectionResult(result.message);
  }));
  window.addEventListener('resize', () => { applyAppearance(); fitWindows(); });
  if (window.visualViewport) visualViewport.addEventListener('resize', fitWindows);
  window.addEventListener('pagehide', () => { if (ready) fetch('/api/preferences', {method: 'POST', credentials: 'same-origin', keepalive: true, headers: {'Content-Type': 'application/json', 'X-Tenmiyora-Client': 'web'}, body: JSON.stringify({appearance: state.appearance, layout: state.layout})}).catch(() => {}); });
  window.TenmiyoraUpdates = {
    flush: () => Promise.all([flushSave(), connectionSaveQueue]),
    busy: () => !ready || pending || Boolean($('chat-input').value.trim() || $('api-key').value) ||
      (currentProvider() === 'cloudru' ? CLOUDRU_URL : $('api-url').value.trim()) !== state.connection.url ||
      $('api-model').value.trim() !== state.connection.model || $('save-status').textContent === 'Сохранение…'
  };
  async function startup() {
    $('fatal-error').hidden = true;
    try { const result = await api('state'); state = result; ready = true; applyAppearance(); renderConnection(true); renderMessages(); $('server-status').textContent = 'Сервер запущен'; }
    catch (error) { $('server-status').textContent = 'Нет соединения'; $('fatal-message').textContent = error.message; $('fatal-error').hidden = false; applyAppearance(); renderConnection(); renderMessages(); }
  }
  $('retry-startup').addEventListener('click', startup);
  applyAppearance(); renderMessages(); startup();
})();
