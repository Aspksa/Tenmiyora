(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const client = Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
  const stages = {checking: 0, waiting_ci: 0, available: 0, downloading: 1, verifying: 2, ready: 3, waiting_chat: 3, waiting_user: 3, restarting: 4, installing: 4, health_check: 5, installed: 6, current: 6};
  const working = new Set(['checking', 'downloading', 'verifying', 'waiting_chat', 'waiting_user', 'restarting', 'installing', 'health_check']);
  let boot, polling = false, changing = false, lastPhase, activityTimer;
  async function api(action, body, retry = true) {
    const response = await fetch('/api/update/' + action, {method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', headers: {'Content-Type': 'application/json', 'X-Tenmiyora-Client': 'web'}, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
    if (response.status === 403 && retry) {
      await fetch('/', {cache: 'no-store', credentials: 'same-origin'});
      return api(action, body, false);
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Не удалось выполнить действие');
    return data;
  }
  function render(data) {
    if (boot && data.boot_id !== boot) { location.reload(); return; }
    boot = data.boot_id; lastPhase = data.phase;
    $('update-current').textContent = 'v' + data.current_version;
    $('update-current-sha').textContent = (data.current_commit || '').slice(0, 8);
    $('update-available').textContent = data.available_version ? 'v' + data.available_version : 'Ещё не проверено';
    $('update-available-sha').textContent = (data.available_commit || '').slice(0, 8);
    $('update-message').textContent = data.message;
    $('update-message').classList.toggle('error', Boolean(data.error));
    $('update-progress').value = data.progress || 0;
    if (!changing) $('update-automatic').checked = data.automatic;
    $('update-check').disabled = working.has(data.phase);
    $('update-install').disabled = working.has(data.phase) || !data.available_commit || ['current', 'installed', 'waiting_ci'].includes(data.phase);
    $('update-badge').hidden = ['idle', 'current', 'installed'].includes(data.phase);
    document.querySelectorAll('[data-update-step]').forEach(item => {
      item.classList.toggle('done', Number(item.dataset.updateStep) < stages[data.phase]);
      item.classList.toggle('active', Number(item.dataset.updateStep) === stages[data.phase]);
    });
    $('update-checked-at').textContent = data.checked_at ? 'Последняя проверка: ' + new Date(data.checked_at).toLocaleString('ru-RU') : '';
    $('update-history').replaceChildren();
    const history = [...data.history].reverse();
    if (!history.length) history.push({message: 'Обновлений пока не было'});
    history.forEach(entry => {
      const item = document.createElement('li');
      item.textContent = entry.version ? 'v' + entry.version + ' · ' + (entry.result === 'installed' ? 'Установлено' : 'Выполнен откат') + ' · ' + new Date(entry.time).toLocaleString('ru-RU') : entry.message;
      $('update-history').append(item);
    });
  }
  async function activity() {
    const busy = !window.TenmiyoraUpdates || window.TenmiyoraUpdates.busy();
    await api('activity', {client, busy});
  }
  async function poll() {
    if (polling) return;
    polling = true;
    try { await activity(); render(await api('status')); }
    catch { $('update-message').textContent = ['restarting', 'installing', 'health_check'].includes(lastPhase) ? 'Проект перезапускается. Страница подключится автоматически…' : 'Нет связи с сервером. Ожидаем подключения; при необходимости откройте проект из трея.'; }
    finally { polling = false; }
  }
  $('update-open').addEventListener('click', () => { $('update-panel').hidden = false; $('update-close').focus(); poll(); });
  function close() { $('update-panel').hidden = true; $('update-open').focus(); }
  $('update-close').addEventListener('click', close);
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('update-panel').hidden) { event.stopImmediatePropagation(); close(); } }, true);
  for (const action of ['check', 'install']) $('update-' + action).addEventListener('click', async () => {
    $('update-' + action).disabled = true;
    try { await window.TenmiyoraUpdates.flush(); await activity(); render(await api(action, {})); }
    catch (error) { $('update-message').textContent = error.message; $('update-' + action).disabled = false; }
  });
  $('update-automatic').addEventListener('change', async () => {
    changing = true; $('update-automatic').disabled = true;
    try { render(await api('settings', {automatic: $('update-automatic').checked})); }
    catch (error) { $('update-automatic').checked = !$('update-automatic').checked; $('update-message').textContent = error.message; }
    finally { changing = false; $('update-automatic').disabled = false; }
  });
  document.addEventListener('input', () => { clearTimeout(activityTimer); activityTimer = setTimeout(() => activity().catch(() => {}), 100); });
  document.addEventListener('visibilitychange', poll);
  setInterval(poll, 4000); poll();
})();
