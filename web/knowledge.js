/* Диск и Мозг Tenmiyora. Никаких внешних библиотек и CDN. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let folder = null, searchTimer, loading = false;
  const headers = {'X-Tenmiyora-Client': 'web'};
  function message(text) {
    const area = $('toast');
    area.textContent = text; area.hidden = false;
    clearTimeout(message.timer);
    message.timer = setTimeout(() => { area.hidden = true; }, 5000);
  }
  async function request(path, body) {
    const response = await fetch('/api/' + path, {
      method: body === undefined ? 'GET' : 'POST',
      credentials: 'same-origin',
      headers: {...headers, ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
      ...(body === undefined ? {} : {body: JSON.stringify(body)})
    });
    let payload;
    try { payload = await response.json(); }
    catch { throw Error('Сервер не ответил. Проверьте работу Tenmiyora.'); }
    if (!response.ok) throw Error(payload.error || 'Не удалось выполнить действие.');
    return payload;
  }
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }
  function button(label, callback, className) {
    const node = element('button', className, label);
    node.type = 'button';
    node.addEventListener('click', callback);
    return node;
  }
  function readableBytes(bytes) {
    return bytes < 1024 ? bytes + ' Б' : bytes < 1048576 ?
      (bytes / 1024).toFixed(1) + ' КБ' : (bytes / 1048576).toFixed(1) + ' МБ';
  }
  function date(value) {
    try { return new Date(value).toLocaleString('ru-RU', {dateStyle: 'short', timeStyle: 'short'}); }
    catch { return ''; }
  }
  function icon(name) {
    const wrapper = element('span', 'disk-icon');
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', name === 'folder' ? '#i-folder' : '#i-file');
    svg.append(use); wrapper.append(svg); return wrapper;
  }
  // Вид списка: сортировка и плитка/список запоминаются в браузере.
  const prefs = (() => {
    try { return {sort: 'new', view: 'list', ...JSON.parse(localStorage.getItem('tenmiyora-disk-view') || '{}')}; }
    catch { return {sort: 'new', view: 'list'}; }
  })();
  function savePrefs() {
    try { localStorage.setItem('tenmiyora-disk-view', JSON.stringify(prefs)); } catch {}
  }
  const sorters = {
    'new': (a, b) => String(b.created).localeCompare(String(a.created)),
    'old': (a, b) => String(a.created).localeCompare(String(b.created)),
    'az': (a, b) => a.name.localeCompare(b.name, 'ru', {numeric: true}),
    'za': (a, b) => b.name.localeCompare(a.name, 'ru', {numeric: true}),
    'big': (a, b) => (b.size || 0) - (a.size || 0),
    'small': (a, b) => (a.size || 0) - (b.size || 0)
  };
  let listData = {folders: [], files: []};
  const selected = new Map();
  const key = (kind, id) => kind + ':' + id;
  async function loadDisk() {
    if (loading) return;
    loading = true;
    try {
      const q = $('disk-search').value.trim();
      const data = await request('disk?' + new URLSearchParams({folder: folder || '', q}));
      const breadcrumbs = $('disk-breadcrumbs');
      const home = button('Мой диск', () => navigate(null));
      dropTarget(home, null);
      breadcrumbs.replaceChildren(home);
      for (const crumb of data.breadcrumbs) {
        breadcrumbs.append(element('span', '', '/'));
        const link = button(crumb.name, () => navigate(crumb.id));
        dropTarget(link, crumb.id);
        breadcrumbs.append(link);
      }
      listData = data;
      const present = new Set([...data.folders.map(x => key('folder', x.id)), ...data.files.map(x => key('file', x.id))]);
      for (const k of [...selected.keys()]) if (!present.has(k)) selected.delete(k);
      renderList();
    } catch (error) { message(error.message); }
    finally { loading = false; }
  }
  function renderList() {
    const list = $('disk-list');
    list.className = 'disk-list' + (prefs.view === 'grid' ? ' grid' : '');
    list.replaceChildren();
    const sorter = sorters[prefs.sort] || sorters.new;
    // Папки по размеру не сравниваются: для них «большие/маленькие» — по имени.
    const folderSorter = prefs.sort === 'big' || prefs.sort === 'small' ? sorters.az : sorter;
    const folders = [...listData.folders].sort(folderSorter), files = [...listData.files].sort(sorter);
    const total = folders.length + files.length;
    $('disk-count').textContent = total + ' элементов';
    for (const item of folders) list.append(makeRow('folder', item));
    for (const item of files) list.append(makeRow('file', item));
    if (!total) list.append(element('p', 'disk-empty', $('disk-search').value.trim() ? 'По вашему запросу ничего не найдено.' : 'Папка пуста. Перетащите сюда файлы или папки, или создайте новую.'));
    renderSelection();
  }
  function renderSelection() {
    const bar = $('disk-bulk');
    const all = $('disk-select-all');
    const total = listData.folders.length + listData.files.length;
    all.checked = total > 0 && selected.size === total;
    all.indeterminate = selected.size > 0 && selected.size < total;
    bar.hidden = !selected.size;
    $('disk-bulk-count').textContent = 'Выбрано: ' + selected.size;
    $('disk-bulk-download').hidden = ![...selected.values()].some(x => x.kind === 'file');
  }
  function navigate(id) {
    folder = id;
    $('disk-search').value = '';
    if (id) expandTo(id);
    renderTree();
    loadDisk();
  }
  async function refreshDisk() {
    await Promise.all([loadDisk(), loadTree()]);
  }

  // Дерево: вся структура Диска, раскрытые ветки запоминаются в браузере.
  let treeData = {folders: [], files: []};
  const expanded = new Set((() => {
    try { return JSON.parse(localStorage.getItem('tenmiyora-disk-tree') || '[]'); }
    catch { return []; }
  })());
  function saveExpanded() {
    try { localStorage.setItem('tenmiyora-disk-tree', JSON.stringify([...expanded])); } catch {}
  }
  function expandTo(id) {
    const parents = new Map(treeData.folders.map(x => [x.id, x.parent]));
    for (let node = id, guard = 0; node && guard < 200; node = parents.get(node), guard++) expanded.add(node);
    saveExpanded();
  }
  async function loadTree() {
    try {
      treeData = await request('disk/tree');
      renderTree();
    } catch (error) { message(error.message); }
  }
  function treeIcon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', '#i-' + name);
    svg.setAttribute('aria-hidden', 'true');
    svg.append(use);
    return svg;
  }
  function renderTree() {
    const folders = new Map(), files = new Map();
    for (const item of treeData.folders) {
      if (!folders.has(item.parent)) folders.set(item.parent, []);
      folders.get(item.parent).push(item);
    }
    for (const item of treeData.files) {
      if (!files.has(item.folder)) files.set(item.folder, []);
      files.get(item.folder).push(item);
    }
    const seen = new Set();
    function branch(parent, depth) {
      const group = element('ul', depth ? 'disk-tree-group' : 'disk-tree-root');
      group.setAttribute('role', depth ? 'group' : 'none');
      for (const item of folders.get(parent) || []) {
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        const hasChildren = (folders.get(item.id) || []).length + (files.get(item.id) || []).length > 0;
        const open = expanded.has(item.id);
        const node = element('li', 'disk-tree-node');
        node.setAttribute('role', 'treeitem');
        if (hasChildren) node.setAttribute('aria-expanded', String(open));
        const line = element('div', 'disk-tree-line' + (item.id === folder ? ' current' : ''));
        line.style.setProperty('--depth', depth);
        const toggle = button('', () => {
          open ? expanded.delete(item.id) : expanded.add(item.id);
          saveExpanded(); renderTree();
        }, 'disk-tree-toggle' + (open ? ' open' : ''));
        toggle.setAttribute('aria-label', (open ? 'Свернуть ' : 'Развернуть ') + item.name);
        toggle.disabled = !hasChildren;
        toggle.append(treeIcon('chevron'));
        const name = button('', () => navigate(item.id), 'disk-tree-name');
        name.append(treeIcon('folder'), element('span', '', item.name));
        name.title = item.name;
        const add = button('', () => createFolder(item.id), 'disk-tree-add');
        add.setAttribute('aria-label', 'Новая папка внутри «' + item.name + '»');
        add.title = 'Новая папка внутри';
        add.append(treeIcon('plus'));
        line.append(toggle, name, add);
        dropTarget(line, item.id);
        draggableLine(line, 'folder', item);
        node.append(line);
        if (open && hasChildren) node.append(branch(item.id, depth + 1));
        group.append(node);
      }
      for (const item of files.get(parent) || []) {
        const node = element('li', 'disk-tree-node');
        node.setAttribute('role', 'treeitem');
        const line = element('div', 'disk-tree-line file');
        line.style.setProperty('--depth', depth);
        const name = button('', () => TEXT_EXT.test(item.name) ? openFileDialog(item) : openDocument(item), 'disk-tree-name');
        name.append(treeIcon('file'), element('span', '', item.name));
        name.title = item.name + ' · ' + readableBytes(item.size) + ' · ' + item.status;
        line.append(element('span', 'disk-tree-toggle'), name);
        draggableLine(line, 'file', item);
        node.append(line);
        group.append(node);
      }
      return group;
    }
    const root = element('div', 'disk-tree-line root' + (folder === null ? ' current' : ''));
    const home = button('', () => navigate(null), 'disk-tree-name');
    home.append(treeIcon('disk'), element('span', '', 'Мой диск'));
    const add = button('', () => createFolder(null), 'disk-tree-add');
    add.setAttribute('aria-label', 'Новая папка в корне диска');
    add.title = 'Новая папка в корне';
    add.append(treeIcon('plus'));
    root.append(home, add);
    dropTarget(root, null);
    const body = branch(null, 0);
    $('disk-tree').replaceChildren(root, body);
    if (!treeData.folders.length && !treeData.files.length)
      $('disk-tree').append(element('p', 'disk-tree-empty', 'Пока пусто. Создайте папку или файл.'));
  }
  function draggableLine(line, kind, item) {
    line.draggable = true;
    line.addEventListener('dragstart', event => {
      event.dataTransfer.setData('application/x-tenmiyora-items', JSON.stringify([{kind, id: item.id, name: item.name}]));
      event.dataTransfer.effectAllowed = 'move';
    });
  }
  async function createFolder(parent) {
    const name = prompt('Название новой папки.\nМожно сразу цепочку через «/», например: Проекты/2026/Отчёты');
    if (name === null || !name.trim()) return;
    try {
      const result = await request('disk/folder', {parent, name: name.trim()});
      if (parent) expanded.add(parent);
      expandTo(result.created ? result.created[result.created.length - 1].id : result.id);
      if (result.created && result.created.length > 1) message('Создано папок: ' + result.created.length + '.');
      await refreshDisk();
    } catch (error) { message(error.message); }
  }
  // Окно файла: создание нового или просмотр и правка текстового.
  let fileDialog, editing = null;
  function ensureFileDialog() {
    if (fileDialog) return fileDialog;
    const dialog = element('dialog', 'doc-dialog disk-file-dialog');
    const form = element('form', 'disk-file-form');
    form.method = 'dialog';
    const head = element('div', 'doc-dialog-head');
    const title = element('h3', '', 'Новый файл'); title.id = 'disk-file-title';
    head.append(title);
    head.append(button('Закрыть', () => dialog.close()));
    const place = element('p', 'module-muted');
    place.id = 'disk-file-place';
    const nameLabel = element('label', '', 'Имя файла');
    nameLabel.id = 'disk-file-name-label';
    const nameInput = element('input');
    nameInput.id = 'disk-file-name'; nameInput.maxLength = 180;
    nameInput.placeholder = 'заметка.md';
    nameLabel.append(nameInput);
    const textLabel = element('label', '', 'Текст');
    const textInput = element('textarea');
    textInput.id = 'disk-file-text'; textInput.rows = 14; textInput.maxLength = 100000;
    textInput.placeholder = 'Текст файла. Его содержимое пополнит Мозг так же, как загруженный документ.';
    textLabel.append(textInput);
    const actions = element('div', 'disk-file-actions');
    const cancel = button('Отмена', () => dialog.close(), 'secondary-button');
    const submit = element('button', 'primary-button', 'Создать');
    submit.type = 'submit'; submit.id = 'disk-file-submit';
    actions.append(cancel, submit);
    form.append(head, place, nameLabel, textLabel, actions);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (!editing && !nameInput.value.trim()) { nameInput.focus(); return; }
      submit.disabled = true;
      try {
        const result = editing ?
          await request('disk/text', {id: editing.id, text: textInput.value}) :
          await request('disk/file', {folder, name: nameInput.value.trim(), text: textInput.value});
        dialog.close();
        message((editing ? 'Сохранён «' : 'Создан «') + result.name + '». ' + result.status + '.');
        if (!editing && folder) expandTo(folder);
        await refreshDisk();
      } catch (error) { message(error.message); }
      finally { submit.disabled = false; }
    });
    dialog.append(form);
    document.body.append(dialog);
    return fileDialog = dialog;
  }
  let fileOpenTicket = 0;
  async function openFileDialog(item) {
    // Ответ от более раннего открытия не должен подменить текст и цель сохранения.
    const ticket = ++fileOpenTicket;
    const target = item && item.id ? item : null;
    let text = '';
    if (target) {
      try { text = (await request('disk/text?' + new URLSearchParams({id: target.id}))).text; }
      catch (error) { if (ticket === fileOpenTicket) message(error.message); return; }
      if (ticket !== fileOpenTicket) return;
    }
    const dialog = ensureFileDialog();
    editing = target;
    $('disk-file-name-label').hidden = !!editing;
    $('disk-file-title').textContent = editing ? editing.name : 'Новый файл';
    $('disk-file-submit').textContent = editing ? 'Сохранить' : 'Создать';
    $('disk-file-name').value = ''; $('disk-file-text').value = text;
    // Лимит в 100 000 символов — только для нового файла; правку ограничивает сервер (400 КБ).
    if (editing) $('disk-file-text').removeAttribute('maxlength');
    else $('disk-file-text').maxLength = 100000;
    if (editing) {
      $('disk-file-place').textContent = 'Изменения сохранятся новой версией файла, Мозг переучится на новом тексте.';
    } else {
      const crumbs = [...$('disk-breadcrumbs').querySelectorAll('button')].map(x => x.textContent);
      $('disk-file-place').textContent = 'Папка: ' + (crumbs.join(' / ') || 'Мой диск');
    }
    if (!dialog.open) dialog.showModal();
    (editing ? $('disk-file-text') : $('disk-file-name')).focus();
  }
  // Метка: что Мозг знает о файле.
  function brainBadge(item) {
    const status = String(item.status || '');
    if (/не удалось|требует проверки|ошибк|не выполнен/i.test(status)) return ['error', 'Ошибка изучения'];
    if (/выполняется|ожидает/i.test(status)) return ['busy', 'Мозг изучает…'];
    if (status.startsWith('готово') && item.facts > 0) return ['ok', 'В Мозге · ' + item.facts];
    if (/не поддерживается/i.test(status)) return ['none', 'Формат не изучается'];
    return ['none', 'Не изучен'];
  }
  const TEXT_EXT = /\.(txt|md|markdown|rst|csv|json|ya?ml|log|ini|toml|py|jsx?|tsx?|css|html?|sql|ps1|bat|sh|xml)$/i;
  function closeMenus(except) {
    for (const menu of document.querySelectorAll('.disk-menu[open]')) if (menu !== except) menu.open = false;
  }
  document.addEventListener('click', event => {
    if (!event.target.closest('.disk-menu')) closeMenus();
  });
  function makeRow(kind, item) {
    const row = element('div', 'disk-row' + (selected.has(key(kind, item.id)) ? ' selected' : ''));
    row.draggable = true;
    row.addEventListener('dragstart', event => {
      const items = selected.has(key(kind, item.id)) ? [...selected.values()] : [{kind, id: item.id, name: item.name}];
      event.dataTransfer.setData('application/x-tenmiyora-items', JSON.stringify(items));
      event.dataTransfer.effectAllowed = 'move';
    });
    const check = element('input', 'disk-check');
    check.type = 'checkbox';
    check.checked = selected.has(key(kind, item.id));
    check.setAttribute('aria-label', 'Выбрать «' + item.name + '»');
    check.addEventListener('change', () => {
      check.checked ? selected.set(key(kind, item.id), {kind, id: item.id, name: item.name}) : selected.delete(key(kind, item.id));
      row.classList.toggle('selected', check.checked);
      renderSelection();
    });
    row.append(check, icon(kind));
    if (kind === 'folder') dropTarget(row, item.id);
    const main = element('div', 'disk-item-content');
    main.append(button(item.name, () => kind === 'folder' ? navigate(item.id) : TEXT_EXT.test(item.name) ? openFileDialog(item) : openDocument(item), 'disk-item-name'));
    const meta = element('small', 'disk-item-meta', kind === 'folder' ?
      'Папка · ' + date(item.created) : readableBytes(item.size) + ' · ' + date(item.created));
    main.append(meta);
    if (kind === 'file') {
      const [tone, label] = brainBadge(item);
      const badge = element('span', 'disk-badge ' + tone, label);
      badge.title = item.status;
      main.append(badge);
    }
    row.append(main);
    const actions = element('div', 'disk-row-actions');
    if (kind === 'file') {
      if (brainBadge(item)[0] === 'error') actions.append(button('Переобучить', () => relearn([item])));
      if (TEXT_EXT.test(item.name)) actions.append(button('Открыть', () => openFileDialog(item)));
      actions.append(button('Изучить', () => openDocument(item), 'disk-inline-study'));
    }
    const menu = element('details', 'disk-menu');
    const summary = element('summary', '', '⋯');
    summary.setAttribute('aria-label', 'Действия с «' + item.name + '»');
    summary.title = 'Ещё';
    menu.addEventListener('toggle', () => { if (menu.open) closeMenus(menu); });
    const items = element('div', 'disk-menu-items');
    const entry = (label, callback) => items.append(button(label, () => { menu.open = false; callback(); }));
    if (kind === 'file') {
      entry('Изучить документ', () => openDocument(item));
      entry('Скачать', () => download(item));
      if (!/не поддерживается/i.test(item.status)) entry('Переобучить Мозг', () => relearn([item]));
    } else entry('Новая папка внутри', () => createFolder(item.id));
    entry('Переместить…', () => openMoveDialog([{kind, id: item.id, name: item.name}]));
    entry('Переименовать', async () => {
      const next = prompt('Новое имя:', item.name);
      if (next === null || next.trim() === item.name) return;
      try {
        await request('disk/rename', {kind, id: item.id, name: next.trim()});
        await refreshDisk();
      } catch (error) { message(error.message); }
    });
    entry('Удалить', () => removeItems([{kind, id: item.id, name: item.name}]));
    menu.append(summary, items);
    actions.append(menu);
    row.append(actions);
    return row;
  }
  // Перетаскивание строк и веток дерева на папку = перемещение.
  function dropTarget(node, target) {
    node.addEventListener('dragover', event => {
      if (!event.dataTransfer?.types.includes('application/x-tenmiyora-items')) return;
      event.preventDefault(); event.stopPropagation();
      event.dataTransfer.dropEffect = 'move';
      node.classList.add('drop-over');
    });
    node.addEventListener('dragleave', () => node.classList.remove('drop-over'));
    node.addEventListener('drop', event => {
      if (!event.dataTransfer?.types.includes('application/x-tenmiyora-items')) return;
      event.preventDefault(); event.stopPropagation();
      node.classList.remove('drop-over');
      try { moveItems(JSON.parse(event.dataTransfer.getData('application/x-tenmiyora-items')), target); }
      catch { message('Не удалось переместить.'); }
    });
  }
  // Из выделения убираются объекты, чья папка-предок тоже выделена:
  // папка переносится и удаляется вместе с содержимым.
  function topLevel(items) {
    const chosen = new Set(items.filter(x => x.kind === 'folder').map(x => x.id));
    const parents = new Map(treeData.folders.map(x => [x.id, x.parent]));
    const files = new Map(treeData.files.map(x => [x.id, x.folder]));
    return items.filter(item => {
      let node = item.kind === 'folder' ? parents.get(item.id) : files.get(item.id);
      for (let guard = 0; node && guard < 200; node = parents.get(node), guard++) if (chosen.has(node)) return false;
      return true;
    });
  }
  async function moveItems(items, target) {
    items = topLevel(items);
    let moved = 0;
    for (const item of items) {
      if (item.kind === 'folder' && item.id === target) continue;
      try {
        const result = await request('disk/move', {kind: item.kind, id: item.id, target});
        if (result.moved) moved++;
      } catch (error) { message(item.name + ': ' + error.message); }
    }
    if (moved) {
      if (target) expandTo(target);
      message('Перемещено: ' + moved + '.');
    }
    selected.clear();
    await refreshDisk();
  }
  async function removeItems(items) {
    items = topLevel(items);
    const folders = items.filter(x => x.kind === 'folder');
    const text = items.length === 1 ? '«' + items[0].name + '»' : items.length + ' объектов';
    if (!confirm('Удалить ' + text + '?' + (folders.length ? ' Папки удаляются вместе со всем содержимым.' : '') +
        ' Знания Мозга из удалённых файлов тоже будут удалены.')) return;
    let files = 0;
    for (const item of items) {
      try {
        const result = await request('disk/delete', {kind: item.kind, id: item.id, recursive: true});
        files += result.files || 0;
      } catch (error) { message(item.name + ': ' + error.message); }
    }
    if (folders.length && files) message('Удалено файлов вместе с папками: ' + files + '.');
    selected.clear();
    await refreshDisk();
    if (location.hash === '#brain') await loadBrain();
  }
  async function relearn(items) {
    for (const item of items) {
      try {
        const result = await request('disk/relearn', {id: item.id});
        message('«' + item.name + '»: ' + result.status + '.');
      } catch (error) { message(item.name + ': ' + error.message); }
    }
    await loadDisk();
  }
  let moveDialog;
  function openMoveDialog(items) {
    if (!moveDialog) {
      moveDialog = element('dialog', 'doc-dialog disk-move-dialog');
      const head = element('div', 'doc-dialog-head');
      head.append(element('h3', '', 'Переместить'), button('Закрыть', () => moveDialog.close()));
      const what = element('p', 'module-muted'); what.id = 'disk-move-what';
      const list = element('div', 'disk-move-list'); list.id = 'disk-move-list';
      moveDialog.append(head, what, list);
      document.body.append(moveDialog);
    }
    $('disk-move-what').textContent = (items.length === 1 ? '«' + items[0].name + '»' : 'Объектов: ' + items.length) + ' → выберите папку';
    // Папку нельзя положить в неё саму и во вложенные.
    const blocked = new Set(items.filter(x => x.kind === 'folder').map(x => x.id));
    const children = new Map();
    for (const item of treeData.folders) {
      if (!children.has(item.parent)) children.set(item.parent, []);
      children.get(item.parent).push(item);
    }
    const list = $('disk-move-list');
    list.replaceChildren();
    const option = (id, name, depth, disabled) => {
      const choice = button('', async () => { moveDialog.close(); await moveItems(items, id); }, 'disk-move-option');
      choice.style.setProperty('--depth', depth);
      choice.append(treeIcon(id === null ? 'disk' : 'folder'), element('span', '', name));
      choice.disabled = disabled;
      list.append(choice);
    };
    option(null, 'Мой диск', 0, false);
    const walk = (parent, depth, disabled, seen) => {
      for (const item of children.get(parent) || []) {
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        const off = disabled || blocked.has(item.id);
        option(item.id, item.name, depth, off);
        walk(item.id, depth + 1, off, seen);
      }
    };
    walk(null, 1, false, new Set());
    moveDialog.showModal();
  }
  let documentDialog;
  function ensureDocumentDialog() {
    if (documentDialog) return documentDialog;
    const dialog = element('dialog','doc-dialog');
    const header = element('div','doc-dialog-head');
    header.append(element('h3','','Изучение документа'));
    header.append(button('Закрыть',() => dialog.close()));
    dialog.append(header);
    const status = element('p','module-muted');
    status.id='doc-reading-status';
    const body = element('div','doc-results');
    body.id='doc-reading-results';
    const form = element('form','doc-question-form');
    form.addEventListener('submit',event => event.preventDefault());
    const input = element('input','doc-question-input');
    input.type='text';input.maxLength=600;input.placeholder='Спросите о сроках, обязанностях, условиях…';
    input.setAttribute('aria-label','Вопрос по документу');
    input.id='doc-question-input';
    const ask = button('Найти ответ в документе',() => askDocument());
    ask.id='doc-question-submit';
    form.append(input,ask);
    const deep = button('Глубокий смысловой анализ моделью',() => deepDocument());
    deep.id='doc-deep-trigger';
    const caveat=element('p','module-muted','Дополнительные запросы к модели возможны только с вашего разрешения. Интерпретации не считаются доказанными фактами.');
    dialog.append(status,body,form,caveat,deep);
    dialog.addEventListener('click',event => {
      if (event.target===dialog) dialog.close();
    });
    document.body.append(dialog);
    documentDialog=dialog;
    return dialog;
  }
  let selectedDocument;
  async function openDocument(file) {
    selectedDocument=file;
    const dialog=ensureDocumentDialog();
    $('doc-reading-status').textContent='Чтение структуры и источников…';
    $('doc-reading-results').replaceChildren();
    $('doc-question-input').value='';
    if (!dialog.open) dialog.showModal();
    try {
      const data=await request('document?id='+encodeURIComponent(file.id));
      selectedDocument.estimated_model_calls=data.estimated_model_calls;
      $('doc-reading-status').textContent=(data.complete ? 'Извлечённый текст обработан' : 'Документ прочитан частично')+
        ' · '+data.segment_count+' блоков · '+data.characters+' символов';
      const panel=$('doc-reading-results');
      if (data.limitations.length) {
        const note=element('p','doc-warning',data.limitations.join(' '));panel.append(note);
      }
      panel.append(element('h4','','Смысловые элементы и цитаты'));
      for(const finding of data.findings.slice(0,30)) {
        const card=element('div','doc-citation');
        const heading=finding.categories.join(', ') || 'Дата';
        card.append(element('small','',heading+' · '+finding.locator));
        card.append(element('p','',finding.quote));
        panel.append(card);
      }
      if (!data.findings.length) panel.append(element('p','module-muted','Явные условия не найдены. Можно задать вопрос по исходному тексту.'));
      if(data.possible_conflicts?.length){
        panel.append(element('h4','','Возможные несовпадения — требуют проверки'));
        for(const candidate of data.possible_conflicts.slice(0,10)){
          for(const source of candidate.evidence){
            const line=element('div','doc-citation');
            line.append(element('small','',source.locator));
            line.append(element('p','',source.quote));
            panel.append(line);
          }
        }
      }
    } catch(error) { $('doc-reading-status').textContent=error.message; }
  }
  async function deepDocument() {
    if(!selectedDocument) return;
    const estimated=selectedDocument.estimated_model_calls ?? 'до 80';
    const count=Math.min(Number(estimated)||80,80);
    if (!count) {message('Нет доступного текста для анализа.');return;}
    if (!confirm('Глубокий анализ может выполнить до '+count+
      ' последовательных запросов к выбранной модели. Внешние запросы могут быть платными и передают текст документа провайдеру. Продолжить?')) return;
    const action=$('doc-deep-trigger');
    action.disabled=true;
    $('doc-reading-status').textContent='Идёт последовательный смысловой анализ. Окно не закрывайте.';
    try {
      const data=await request('document/deep',
        {id:selectedDocument.id,question:$('doc-question-input').value.trim(),
         max_batches:80,allow_external:true});
      const panel=$('doc-reading-results');
      const section=element('section','doc-answer');
      section.append(element('h4','','Глубокий смысловой анализ — гипотезы модели'));
      section.append(element('p','',data.message));
      section.append(element('p','',data.processed_batches+' из '+data.total_batches+' частей документа.'));
      if(!data.complete) section.append(element('p','doc-warning',
        'Анализ неполный: '+data.limitations.join(' ')));
      for(const finding of data.findings){
        const card=element('div','doc-citation');
        card.append(element('small','',finding.kind+' · '+finding.locator));
        card.append(element('p','',finding.quote));
        if(finding.interpretation) card.append(element('p','module-muted',
          'Предположение модели: '+finding.interpretation));
        section.append(card);
      }
      if(!data.findings.length) section.append(element('p','module-muted',
        'Модель не вернула интерпретаций с проверяемыми дословными цитатами.'));
      panel.prepend(section);
      $('doc-reading-status').textContent='Смысловой анализ завершён';
    } catch(error) {message(error.message);$('doc-reading-status').textContent='Анализ не завершён: '+error.message;}
    finally{action.disabled=false;}
  }

  async function askDocument(){
    if (!selectedDocument) return;
    const question=$('doc-question-input').value.trim();
    if(question.length<3) {message('Введите вопрос по документу.');return;}
    const action=$('doc-question-submit');
    action.disabled=true;
    try{
      const data=await request('document/ask',{id:selectedDocument.id,question});
      const panel=$('doc-reading-results');
      const answer=element('section','doc-answer');
      answer.append(element('h4','','Ответ по источнику'));
      answer.append(element('p','',data.answer));
      if(!data.complete) answer.append(element('p','doc-warning','Внимание: документ обработан не полностью.'));
      for(const cit of data.citations || []){
        const source=element('div','doc-citation');
        source.append(element('small','',cit.locator));
        source.append(element('p','',cit.quote));
        answer.append(source);
      }
      for(const conflict of data.possible_conflicts || []){
        for(const cit of conflict.evidence){
          const item=element('div','doc-citation');
          item.append(element('small','',cit.locator));
          item.append(element('p','',cit.quote));
          answer.append(item);
        }
      }
      panel.prepend(answer);
    }catch(error){message(error.message);}
    finally{action.disabled=false;}
  }

  async function download(item) {
    try {
      const response = await fetch('/api/disk/download?id=' + encodeURIComponent(item.id),
        {credentials: 'same-origin', headers});
      if (!response.ok) throw Error('Не удалось скачать файл.');
      const blob = await response.blob(), url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = item.name;
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (error) { message(error.message); }
  }
  // entries: [{file, dir}], dir — относительный путь папки внутри текущей ('' — сама текущая).
  // base фиксируется до первого await: переход в другую папку не разрывает загрузку.
  async function upload(entries, base = folder) {
    const folderIds = new Map([['', base]]);
    let step = 0, saved = 0;
    const failed = [];
    for (const {file, dir} of entries) {
      $('disk-count').textContent = 'Загрузка ' + (++step) + ' из ' + entries.length + ': ' + file.name;
      if (file.size > 25 * 1024 * 1024) {
        failed.push(file.name); message(file.name + ': файл больше 25 МБ'); continue;
      }
      try {
        if (!folderIds.has(dir)) {
          const made = await request('disk/folder', {parent: base, name: dir, ensure: true});
          folderIds.set(dir, made.id);
        }
        const response = await fetch('/api/disk/upload', {
          method: 'POST', credentials: 'same-origin',
          headers: {...headers, 'X-Tenmiyora-Filename': encodeURIComponent(file.name),
                    'X-Tenmiyora-Folder': folderIds.get(dir) || '',
                    'X-Tenmiyora-Mime': file.type || 'application/octet-stream'},
          body: file
        });
        const result = await response.json();
        if (!response.ok) throw Error(result.error || 'Ошибка загрузки.');
        saved++;
        message('Сохранён «' + file.name + '». ' + result.status + '.');
      } catch (error) { failed.push(file.name); message(file.name + ': ' + error.message); }
    }
    if (entries.length > 1) message('Загружено файлов: ' + saved + ' из ' + entries.length + '.' +
      (failed.length ? ' Не загружены: ' + failed.slice(0, 5).join(', ') + (failed.length > 5 ? ' и ещё ' + (failed.length - 5) : '') + '.' : ''));
    await refreshDisk();
  }
  const plain = files => files.map(file => ({file, dir: ''}));
  // Перетащенные папки обходятся целиком, структура сохраняется.
  async function droppedEntries(transfer) {
    const roots = [...transfer.items || []].map(x => x.webkitGetAsEntry && x.webkitGetAsEntry()).filter(Boolean);
    if (!roots.some(x => x.isDirectory)) return plain([...transfer.files]);
    const result = [];
    async function walk(entry, dir) {
      if (entry.isFile) {
        const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
        result.push({file, dir});
      } else if (entry.isDirectory) {
        const path = dir ? dir + '/' + entry.name : entry.name;
        const reader = entry.createReader();
        for (;;) {
          const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
          if (!batch.length) break;
          for (const child of batch) await walk(child, path);
        }
        if (!result.some(x => x.dir === path || x.dir.startsWith(path + '/'))) result.push({file: null, dir: path});
      }
    }
    for (const entry of roots) await walk(entry, '');
    return result;
  }
  async function uploadWithFolders(entries, base) {
    // Пустые папки тоже переносятся.
    for (const {dir} of entries.filter(x => !x.file)) {
      try { await request('disk/folder', {parent: base, name: dir, ensure: true}); }
      catch (error) { message(dir + ': ' + error.message); }
    }
    await upload(entries.filter(x => x.file), base);
  }
  $('disk-file-input').addEventListener('change', event => {
    upload(plain([...event.target.files])); event.target.value = '';
  });
  $('disk-folder-input').addEventListener('change', event => {
    const entries = [...event.target.files].map(file => {
      const parts = (file.webkitRelativePath || file.name).split('/');
      return {file, dir: parts.slice(0, -1).join('/')};
    });
    event.target.value = '';
    if (entries.length) upload(entries);
  });
  $('disk-upload-button').addEventListener('click', () => $('disk-file-input').click());
  $('disk-folder-pick').addEventListener('click', event => {
    event.stopPropagation();
    $('disk-folder-input').click();
  });
  $('disk-new-folder').addEventListener('click', () => createFolder(folder));
  $('disk-new-file').addEventListener('click', () => openFileDialog());
  if (matchMedia('(max-width: 960px)').matches) $('disk-tree-details').open = false;
  const dropzone = $('disk-dropzone');
  dropzone.addEventListener('click', () => $('disk-file-input').click());
  dropzone.addEventListener('keydown', event => {
    if (event.target !== dropzone) return;
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); $('disk-file-input').click(); }
  });
  for (const target of [dropzone, $('disk-view')]) {
    target.addEventListener('dragover', event => {
      if (!event.dataTransfer?.types.includes('Files')) return;
      event.preventDefault(); dropzone.classList.add('drag-over');
    });
    target.addEventListener('dragleave', event => {
      if (!event.relatedTarget || !target.contains(event.relatedTarget)) dropzone.classList.remove('drag-over');
    });
    target.addEventListener('drop', async event => {
      if (!event.dataTransfer?.types.includes('Files')) return;
      event.preventDefault(); event.stopPropagation(); dropzone.classList.remove('drag-over');
      const base = folder;
      try { await uploadWithFolders(await droppedEntries(event.dataTransfer), base); }
      catch { message('Не удалось прочитать перетащенные файлы.'); }
    });
  }
  // Сортировка, вид и массовые действия.
  $('disk-sort').value = sorters[prefs.sort] ? prefs.sort : 'new';
  $('disk-sort').addEventListener('change', event => { prefs.sort = event.target.value; savePrefs(); renderList(); });
  function syncView() {
    for (const node of document.querySelectorAll('[data-disk-view]')) node.setAttribute('aria-pressed', String(node.dataset.diskView === prefs.view));
  }
  for (const node of document.querySelectorAll('[data-disk-view]')) node.addEventListener('click', () => {
    prefs.view = node.dataset.diskView; savePrefs(); syncView(); renderList();
  });
  syncView();
  $('disk-select-all').addEventListener('change', event => {
    selected.clear();
    if (event.target.checked) {
      for (const item of listData.folders) selected.set(key('folder', item.id), {kind: 'folder', id: item.id, name: item.name});
      for (const item of listData.files) selected.set(key('file', item.id), {kind: 'file', id: item.id, name: item.name});
    }
    renderList();
  });
  $('disk-bulk-move').addEventListener('click', () => openMoveDialog([...selected.values()]));
  $('disk-bulk-delete').addEventListener('click', () => removeItems([...selected.values()]));
  $('disk-bulk-download').addEventListener('click', async () => {
    for (const item of [...selected.values()].filter(x => x.kind === 'file')) await download(item);
  });
  $('disk-bulk-clear').addEventListener('click', () => { selected.clear(); renderList(); });
  $('disk-search').addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadDisk, 220);
  });

  // ---- Мозг ----
  let brainData = {branches: [], real: [], recent: [], chat: null}, growthTopics = [];
  let brainLoading = false, factsRequest = 0;
  function svgIcon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', '#i-' + name);
    svg.setAttribute('aria-hidden', 'true');
    svg.append(use);
    return svg;
  }
  function plural(count, one, few, many) {
    const n = Math.abs(count) % 100, last = n % 10;
    if (n > 10 && n < 20) return many;
    if (last === 1) return one;
    if (last > 1 && last < 5) return few;
    return many;
  }
  function knowledgeCount(count) {
    return count + ' ' + plural(count, 'знание', 'знания', 'знаний');
  }
  function dayLabel(value) {
    const day = new Date(value);
    if (Number.isNaN(day.getTime())) return '';
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const start = new Date(day); start.setHours(0, 0, 0, 0);
    const diff = Math.round((today - start) / 86400000);
    if (diff === 0) return 'Сегодня';
    if (diff === 1) return 'Вчера';
    return day.toLocaleDateString('ru-RU', {day: 'numeric', month: 'long', year: today.getFullYear() === day.getFullYear() ? undefined : 'numeric'});
  }
  function clock(value) {
    const moment = new Date(value);
    return Number.isNaN(moment.getTime()) ? '' : moment.toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'});
  }
  function emptyState(text, iconName) {
    const box = element('div', 'brain-empty');
    box.append(svgIcon(iconName || 'brain'), element('p', '', text));
    return box;
  }
  function childrenOf(id) {
    return brainData.branches.filter(item => item.parent === id);
  }
  function subtreeTotal(node) {
    // Сообщение из двух тем лежит в обеих ветках, поэтому у корня «Разговоры» свой счёт.
    if (node.messages != null) return node.messages;
    return childrenOf(node.id).reduce((sum, child) => sum + subtreeTotal(child), node.facts);
  }
  function ancestors(node) {
    const byId = new Map(brainData.branches.map(item => [item.id, item]));
    const chain = [];
    for (let parent = byId.get(node.parent); parent && !chain.includes(parent); parent = byId.get(parent.parent)) chain.unshift(parent);
    return chain;
  }

  // Карточка знания: цитата, источник, дата и переход к документу.
  function knowledgeCard(fact, branchName, branchId) {
    const card = element('article', 'brain-fact');
    const head = element('div', 'brain-fact-head');
    const fromFile = fact.source_type === 'file';
    const badge = element('span', 'brain-source ' + (fromFile ? 'is-file' : 'is-chat'));
    badge.append(svgIcon(fromFile ? 'file' : 'chat'), document.createTextNode(fromFile ? 'Файл' : 'Чат'));
    head.append(badge);
    if (branchName) {
      const chip = button(branchName, () => openBranch(branchId), 'brain-chip');
      chip.title = 'Открыть ветку «' + branchName + '»';
      head.append(chip);
    }
    if (fact.created) head.append(element('time', 'brain-fact-date', date(fact.created)));
    card.append(head);
    const text = element('p', 'brain-fact-text', fact.excerpt);
    card.append(text);
    const foot = element('div', 'brain-fact-foot');
    foot.append(element('small', 'brain-locator', fact.locator));
    const actions = element('div', 'brain-fact-actions');
    if (fact.excerpt.length > 320) {
      text.classList.add('clamped');
      const more = button('Полностью', () => {
        const open = text.classList.toggle('clamped');
        more.textContent = open ? 'Полностью' : 'Свернуть';
      });
      actions.append(more);
    }
    if (fromFile && fact.source_name) {
      actions.append(button('Изучить документ', () => openDocument({id: fact.source_id, name: fact.source_name})));
    }
    const copy = button('Копировать', async () => {
      try { await navigator.clipboard.writeText(fact.excerpt + '\n— ' + fact.locator); message('Цитата скопирована.'); }
      catch { message('Не удалось скопировать цитату.'); }
    });
    actions.append(copy);
    foot.append(actions);
    card.append(foot);
    return card;
  }

  // История роста: загрузка и знания из одного документа — одно событие.
  const EVENT_KINDS = {
    'загрузка': ['file', 'Прочитал документ'], 'обновление файла': ['reset', 'Перечитал обновлённый документ'],
    'новые знания': ['spark', 'Новые знания'], 'смысловой анализ': ['brain', 'Разобрал смысл'],
    'переименование': ['settings', 'Переименован документ'], 'удаление': ['close', 'Забыл удалённый документ'],
    'папка': ['folder', 'Новая папка'],
  };
  function mergedEvents(recent) {
    const items = [];
    for (const event of recent) {
      const learned = event.action === 'новые знания' && /^(.*): (\d+)$/.exec(event.detail || '');
      const name = learned ? learned[1] : event.detail;
      const last = items[items.length - 1];
      // Журнал идёт от новых к старым: «новые знания» записаны сразу после «загрузки».
      if (last && last.name === name && ((learned && !last.added && last.action !== 'новые знания') ||
          (!learned && last.action === 'новые знания' && /^(загрузка|обновление файла)$/.test(event.action)))) {
        if (learned) last.added = Number(learned[2]);
        else { last.action = event.action; last.time = event.time; }
        continue;
      }
      items.push({action: event.action, name, time: event.time, added: learned ? Number(learned[2]) : 0});
    }
    return items.slice(0, 20);
  }
  function renderEvents() {
    const events = $('brain-events');
    events.replaceChildren();
    if (!brainData.recent.length) {
      events.append(emptyState('Рост памяти пока не начался.', 'spark'));
      return;
    }
    let currentDay = null, group;
    mergedEvents(brainData.recent).forEach((event, index) => {
      const label = dayLabel(event.time);
      if (label !== currentDay) {
        currentDay = label;
        events.append(element('h3', 'brain-day', label));
        group = element('ol', 'brain-day-events');
        events.append(group);
      }
      const fromChat = event.action === 'новые знания' && /^Сообщение/.test(event.name);
      const [icon, title] = fromChat ? ['chat', 'Запомнил из разговора'] : EVENT_KINDS[event.action] || ['spark', event.action];
      const row = element('li', 'brain-event kind-' + icon);
      row.style.setProperty('--i', index);
      const mark = element('span', 'brain-event-icon');
      mark.append(svgIcon(icon));
      const body = element('div', 'brain-event-body');
      body.append(element('strong', '', title), element('span', '', event.name));
      const side = element('div', 'brain-event-side');
      if (event.added) side.append(element('span', 'brain-event-added', '+' + knowledgeCount(event.added)));
      side.append(element('time', '', clock(event.time)));
      row.append(mark, body, side);
      group.append(row);
    });
  }

  let brainLabBusy=false;
  function labTile(label, value, note) {
    const tile = element('div', 'brain-lab-tile');
    tile.append(element('span', '', label), element('strong', '', value));
    if (note) tile.append(note);
    return tile;
  }
  function renderLab(data) {
    const pane=$('brain-lab-content');
    if(!pane) return;
    pane.replaceChildren();
    const tiles = element('div', 'brain-lab-tiles');
    tiles.append(labTile('Поколений с экзаменами', data.generation_count));
    tiles.append(labTile('Принятое поколение', data.accepted_generation ? '#' + data.accepted_generation.id : 'Нет'));
    const current=data.latest_generation;
    if(current) {
      const score = Math.max(0, Math.min(1, Number(current.quality_score) || 0));
      const meter = element('span', 'brain-meter');
      meter.style.setProperty('--value', (score * 100).toFixed(1) + '%');
      meter.setAttribute('role', 'img');
      meter.setAttribute('aria-label', 'Качество ' + (score * 100).toFixed(1) + '%');
      tiles.append(labTile('Последний результат #' + current.id, (score * 100).toFixed(1) + '%', meter));
    } else {
      tiles.append(labTile('Последний результат', '—'));
    }
    pane.append(tiles);

    const names={
      incomplete_document:'Неполное чтение документов',
      weak_evidence:'Недостаточно подтверждений',
      possible_conflict:'Возможные противоречия',
      missing_origin:'Неизвестный первоисточник'};
    const gaps=Object.entries(data.gap_counts||{});
    const gapBlock = element('div', 'brain-lab-block');
    gapBlock.append(element('h3','','Обнаруженные пробелы'));
    if(!gaps.length) gapBlock.append(element('p','module-muted','Пробелы ещё не обнаружены. Нажмите «Найти пробелы».'));
    else {
      const chips = element('div', 'brain-lab-chips');
      for(const [kind,total] of gaps) {
        const chip = element('span', 'brain-lab-chip', names[kind]||kind);
        chip.append(element('b', '', total));
        chips.append(chip);
      }
      gapBlock.append(chips);
    }
    if(data.gaps?.length){
      const examples=element('ul','brain-lab-gaps');
      for(const gap of data.gaps.slice(0,8)) examples.append(element('li','',gap.detail || gap.kind));
      gapBlock.append(examples);
    }
    const skillBlock = element('div', 'brain-lab-block');
    skillBlock.append(element('h3','','Проверяемые навыки'));
    if(!data.skills?.length) skillBlock.append(element('p','module-muted',
      'Навыки появятся как предложения после обнаружения подходящих проблем.'));
    for(const skill of data.skills || []){
      const row = element('div', 'brain-lab-row');
      const label = skill.status==='proposed'?'Предложен':skill.status==='approved'?'Одобрен':'Отключён';
      row.append(element('span','',skill.name), element('strong','brain-status is-' + skill.status, label));
      skillBlock.append(row);
    }
    pane.append(gapBlock, skillBlock);
    pane.append(element('p','module-muted brain-lab-note',
      'Лаборатория не меняет программу или веса модели. Оценки относятся только к контрольным синтетическим заданиям.'));
  }
  async function loadLab() {
    try { renderLab(await request('brain/lab')); }
    catch(error) { $('brain-lab-status').textContent=error.message; }
  }
  async function runLab(action) {
    if(brainLabBusy) return;
    if(action==='experiment' && !confirm(
      'Провести три последовательных локальных экзамена? Измеряется синтетический корпус без обращения к Cloud.ru.')) return;
    brainLabBusy=true;
    const scan=$('brain-lab-scan'),exam=$('brain-lab-exam');
    scan.disabled=true;exam.disabled=true;
    $('brain-lab-status').classList.add('busy');
    $('brain-lab-status').textContent=
      action==='experiment'?'Локальные испытания выполняются…':'Проверяются источники и пробелы…';
    try {
      const result=await request(action==='experiment'?'brain/lab/experiment':'brain/lab/scan',
        action==='experiment'?{trials:3}:{});
      $('brain-lab-status').textContent=action==='experiment'
        ? ('Поколение №'+result.generation+' · '+result.verdict+' · '
          +result.trials+' испытания; без изменения весов и кода.')
        : 'Локальная проверка пробелов завершена.';
      await Promise.all([loadLab(), loadGrowth()]);
    } catch(error) { $('brain-lab-status').textContent=error.message; }
    finally {brainLabBusy=false;scan.disabled=false;exam.disabled=false;$('brain-lab-status').classList.remove('busy');}
  }
  $('brain-lab-scan').addEventListener('click',()=>runLab('scan'));
  $('brain-lab-exam').addEventListener('click',()=>runLab('experiment'));

  // Рост Мозга: уровень, живой график, дневник по дням и уровни тем.
  const SVGN = 'http://www.w3.org/2000/svg';
  function svgEl(tag, attrs) {
    const node = document.createElementNS(SVGN, tag);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    return node;
  }
  function shortDay(value, withMonth) {
    const day = new Date(value + 'T12:00:00');
    return day.toLocaleDateString('ru-RU', withMonth ? {day: 'numeric', month: 'short'} : {day: 'numeric'});
  }
  function niceMax(value) {
    if (value <= 4) return 4;
    const step = Math.pow(10, Math.floor(Math.log10(value)));
    for (const k of [1, 2, 2.5, 5, 10]) if (k * step >= value) return k * step;
    return value;
  }
  // Кольцо прогресса: доля 0..1, в центре — подпись.
  function progressRing(size, stroke, share, label, caption, className) {
    const box = element('div', 'ring ' + (className || ''));
    box.style.setProperty('--size', size + 'px');
    const r = (size - stroke) / 2, length = 2 * Math.PI * r;
    const svg = svgEl('svg', {viewBox: `0 0 ${size} ${size}`, 'aria-hidden': 'true'});
    svg.append(svgEl('circle', {class: 'ring-track', cx: size / 2, cy: size / 2, r, 'stroke-width': stroke}));
    const arc = svgEl('circle', {class: 'ring-arc', cx: size / 2, cy: size / 2, r, 'stroke-width': stroke,
      'stroke-dasharray': length, 'stroke-dashoffset': length * (1 - Math.max(0.02, Math.min(1, share))),
      transform: `rotate(-90 ${size / 2} ${size / 2})`});
    arc.style.setProperty('--len', length);
    svg.append(arc);
    const center = element('div', 'ring-center');
    center.append(element('strong', '', label));
    if (caption) center.append(element('span', '', caption));
    box.append(svg, center);
    return box;
  }
  function sparkline(values, className) {
    const w = 120, h = 30, top = Math.max(...values, 1);
    const svg = svgEl('svg', {class: 'spark ' + (className || ''), viewBox: `0 0 ${w} ${h}`, preserveAspectRatio: 'none', 'aria-hidden': 'true'});
    const points = values.map((v, i) => [i / Math.max(1, values.length - 1) * w, h - 2 - v / top * (h - 6)]);
    const line = points.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
    svg.append(svgEl('path', {class: 'spark-area', d: line + ` L${w} ${h} L0 ${h} Z`}),
      svgEl('path', {class: 'spark-line', d: line, 'vector-effect': 'non-scaling-stroke'}));
    return svg;
  }
  function renderBrainLevel(brain) {
    const box = $('brain-level');
    box.replaceChildren();
    if (!brain) return;
    const ring = progressRing(168, 10, brain.progress, brain.level, 'уровень', 'ring-brain');
    for (let i = 0; i < 3; i++) ring.append(element('i', 'ring-orbit o' + i));
    const text = element('div', 'brain-level-text');
    text.append(element('span', 'brain-level-eyebrow', 'Мозг сейчас'), element('strong', 'brain-level-name', brain.name));
    text.append(element('p', '', brain.next ?
      'Ещё ' + knowledgeCount(brain.next - brain.total) + ' до уровня «' + brain.next_name + '»' :
      'Высший уровень. Мозг продолжает расти.'));
    box.append(ring, text);
    const stats = $('brain-growth-stats');
    stats.replaceChildren();
    const tile = (value, label, icon) => {
      const item = element('div', 'growth-stat');
      const mark = element('span', 'growth-stat-icon');
      mark.append(svgIcon(icon));
      const body = element('div');
      body.append(element('strong', '', value), element('span', '', label));
      item.append(mark, body);
      stats.append(item);
    };
    tile(brain.total, plural(brain.total, 'знание всего', 'знания всего', 'знаний всего'), 'brain');
    tile('+' + brain.week, 'за неделю', 'spark');
    tile(brain.streak, plural(brain.streak, 'день подряд растёт', 'дня подряд растёт', 'дней подряд растёт'), 'arrow');
    tile(brain.best_day ? '+' + brain.best_day.added : '—', brain.best_day ? 'лучший день, ' + shortDay(brain.best_day.date, true) : 'лучший день', 'check');
  }
  function renderGrowthChart(series) {
    const box = $('brain-growth-chart');
    box.replaceChildren();
    const added = series.reduce((sum, day) => sum + day.added, 0);
    const total = series.length ? series[series.length - 1].total : 0;
    $('brain-growth-summary').textContent = added ?
      'Линия показывает, сколько всего знаний в Мозге. Светящиеся точки отмечают дни, когда он узнал новое: чем крупнее точка, тем больше узнал.' :
      'За 30 дней новых знаний не появилось. Загрузите документ на Диск или расскажите что-нибудь в чате.';
    const top = niceMax(Math.max(total, 1));
    const W = 600, H = 200;
    const plot = element('div', 'growth-plot');
    const grid = element('div', 'growth-grid');
    for (const value of [top, top / 2, 0]) {
      const line = element('div', 'growth-gridline');
      line.append(element('span', '', Number.isInteger(value) ? value : value.toFixed(1)));
      grid.append(line);
    }
    const x = index => series.length > 1 ? index / (series.length - 1) * W : W / 2;
    const y = value => H - value / top * H;
    const svg = svgEl('svg', {class: 'growth-svg', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', 'aria-hidden': 'true'});
    const defs = svgEl('defs');
    const gradient = svgEl('linearGradient', {id: 'growth-fill', x1: 0, y1: 0, x2: 0, y2: 1});
    gradient.append(svgEl('stop', {offset: '0', 'stop-color': '#ecca7c', 'stop-opacity': '.38'}),
      svgEl('stop', {offset: '1', 'stop-color': '#ecca7c', 'stop-opacity': '0'}));
    defs.append(gradient);
    const line = series.map((day, i) => (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(day.total).toFixed(1)).join(' ');
    svg.append(defs, svgEl('path', {class: 'growth-area', d: line + ` L${W} ${H} L0 ${H} Z`, fill: 'url(#growth-fill)'}),
      svgEl('path', {class: 'growth-line', d: line, pathLength: 1, 'vector-effect': 'non-scaling-stroke'}));
    const dots = element('div', 'growth-dots');
    const largest = Math.max(...series.map(day => day.added), 1);
    series.forEach((day, index) => {
      if (!day.added) return;
      const dot = element('i', 'growth-dot' + (index === series.length - 1 ? ' today' : ''));
      dot.style.left = x(index) / W * 100 + '%';
      dot.style.top = y(day.total) / H * 100 + '%';
      dot.style.setProperty('--d', (7 + Math.sqrt(day.added / largest) * 11).toFixed(1) + 'px');
      dot.style.setProperty('--i', index);
      dots.append(dot);
    });
    const cross = element('div', 'growth-cross');
    cross.hidden = true;
    const tip = element('div', 'growth-tip');
    tip.hidden = true;
    const hits = element('div', 'growth-hits');
    hits.setAttribute('role', 'img');
    hits.setAttribute('aria-label', 'Всего знаний за 30 дней: от ' + (series[0]?.total ?? 0) + ' до ' + total + ', новых ' + added);
    series.forEach((day, index) => {
      const col = element('div', 'growth-hit');
      col.tabIndex = 0;
      const show = () => {
        tip.replaceChildren(element('strong', '', shortDay(day.date, true)),
          element('span', '', 'всего ' + day.total + (day.added ? ' · +' + day.added + ' за день' : '')),
          ...(day.quality != null ? [element('span', '', 'экзамен ' + (day.quality * 100).toFixed(1) + '%')] : []));
        const left = x(index) / W * 100;
        tip.hidden = cross.hidden = false;
        tip.style.left = Math.min(86, Math.max(14, left)) + '%';
        cross.style.left = left + '%';
        cross.style.setProperty('--y', y(day.total) / H * 100 + '%');
      };
      col.addEventListener('mouseenter', show);
      col.addEventListener('focus', show);
      col.addEventListener('mouseleave', () => { tip.hidden = cross.hidden = true; });
      col.addEventListener('blur', () => { tip.hidden = cross.hidden = true; });
      hits.append(col);
    });
    plot.append(grid, svg, dots, cross, hits, tip);
    const axis = element('div', 'growth-axis');
    for (const index of [0, Math.floor(series.length / 2), series.length - 1]) {
      if (series[index]) axis.append(element('span', '', index === series.length - 1 ? 'сегодня' : shortDay(series[index].date, true)));
    }
    const table = element('table', 'sr-only');
    const head = element('tr');
    head.append(element('th', '', 'День'), element('th', '', 'Новых знаний'), element('th', '', 'Всего'));
    table.append(head);
    for (const day of series) {
      const row = element('tr');
      row.append(element('td', '', day.date), element('td', '', day.added), element('td', '', day.total));
      table.append(row);
    }
    box.append(plot, axis, table);
  }
  // Дневник: сводка недели и записи по дням, как будто их пишет сам Мозг.
  function quoteList(names) {
    return names.map(name => '«' + name + '»').join(', ');
  }
  function diaryEntry(day) {
    const entry = element('li', 'diary-day');
    const date = new Date(day.date + 'T12:00:00');
    const stamp = element('div', 'diary-stamp');
    stamp.append(element('strong', '', date.getDate()),
      element('span', '', date.toLocaleDateString('ru-RU', {month: 'short'}).replace('.', '')),
      element('small', '', dayLabel(date.toISOString()) === 'Сегодня' ? 'сегодня' : date.toLocaleDateString('ru-RU', {weekday: 'short'})));
    const body = element('div', 'diary-body');
    const say = (icon, html) => {
      const line = element('p', 'diary-note');
      const mark = element('span', 'diary-note-icon');
      mark.append(svgIcon(icon));
      const text = element('span', 'diary-text');
      text.append(...html);
      line.append(mark, text);
      body.append(line);
    };
    const strong = text => element('strong', '', text);
    const plain = text => document.createTextNode(text);
    if (day.knowledge) say('spark', [plain('Узнал '), strong(knowledgeCount(day.knowledge)),
      plain(day.chat ? (day.chat === day.knowledge ? ' из разговора с вами.' : ', из них ' + day.chat + ' из разговора с вами.') : '.')]);
    if (day.documents.length) say('file', [plain(day.documents.length > 1 ? 'Прочитал документы ' : 'Прочитал документ '), strong(quoteList(day.documents)), plain('.')]);
    if (day.branches.length) {
      const chips = element('span', 'diary-chips');
      day.branches.forEach(name => chips.append(element('span', 'diary-chip', name)));
      say('brain', [plain(day.branches.length > 1 ? 'Выросли новые ветки: ' : 'Выросла новая ветка: '), chips]);
    }
    if (day.exam != null) say('check', [plain('Сдал экзамен на '), strong((day.exam * 100).toFixed(1) + '%'), plain('.')]);
    if (day.self.length) {
      const list = element('ul', 'diary-self');
      day.self.forEach(item => list.append(element('li', '', item.summary)));
      say('moon', [plain('Пока вы отдыхали:'), list]);
    }
    entry.append(stamp, body);
    return entry;
  }
  function renderDiary(diary) {
    const box = $('brain-diary');
    box.replaceChildren();
    $('brain-diary-range').textContent = shortDay(diary.since, true) + ' – ' + shortDay(diary.until, true);
    const summary = element('div', 'diary-summary');
    const big = (value, label) => {
      const cell = element('div', 'diary-big' + (value ? '' : ' zero'));
      cell.append(element('strong', '', value), element('span', '', label));
      summary.append(cell);
    };
    big('+' + diary.knowledge, plural(diary.knowledge, 'знание', 'знания', 'знаний'));
    big(diary.documents, plural(diary.documents, 'документ', 'документа', 'документов'));
    big(diary.branches, plural(diary.branches, 'новая ветка', 'новые ветки', 'новых веток'));
    big(diary.exams, plural(diary.exams, 'экзамен', 'экзамена', 'экзаменов'));
    box.append(summary);
    if (diary.top_topics.length) {
      const fast = element('p', 'diary-fast');
      fast.append(element('span', '', 'Быстрее всего росли'));
      diary.top_topics.forEach(topic => fast.append(element('span', 'diary-chip', topic.name + ' +' + topic.week)));
      box.append(fast);
    }
    const days = (diary.days || []).filter(day => day.knowledge || day.documents.length || day.branches.length || day.self.length || day.exam != null);
    if (!days.length) { box.append(emptyState('За эту неделю Мозг ничего нового не узнал. Новые документы и сообщения в чате появятся здесь.', 'spark')); return; }
    const list = element('ol', 'diary-days');
    days.forEach((day, index) => { const entry = diaryEntry(day); entry.style.setProperty('--i', index); list.append(entry); });
    box.append(list);
    const extra = [];
    if (diary.gaps) extra.push('найдено пробелов: ' + diary.gaps + ' (см. Лабораторию)');
    for (const skill of diary.skills) extra.push('навык «' + skill.name + '» ' +
      (skill.status === 'approved' ? 'одобрен' : skill.status === 'proposed' ? 'предложен' : 'отключён'));
    if (extra.length) box.append(element('p', 'module-muted diary-extra', 'Ещё за неделю: ' + extra.join('; ') + '.'));
  }
  function levelHint(topic) {
    if (!topic.next) return 'Высший уровень темы';
    const parts = [];
    if (topic.next.count) parts.push('+' + knowledgeCount(topic.next.count));
    if (topic.next.sources) parts.push('ещё ' + topic.next.sources + ' ' + plural(topic.next.sources, 'источник', 'источника', 'источников'));
    return 'До «' + topic.next.name + '»: ' + parts.join(' и ');
  }
  function renderLevels(topics) {
    const box = $('brain-levels');
    box.replaceChildren();
    if (!topics.length) { box.append(emptyState('Темы появятся, когда в Мозге будут знания.')); return; }
    topics.forEach((topic, index) => {
      const card = element('div', 'level-card level-' + topic.level);
      card.style.setProperty('--i', index);
      const ring = progressRing(58, 5, topic.next ? topic.next.progress : 1, topic.level, '', 'ring-topic');
      ring.title = topic.next ? 'Прогресс до уровня «' + topic.next.name + '»: ' + Math.round(topic.next.progress * 100) + '%' : 'Высший уровень';
      const body = element('div', 'level-body');
      const head = element('div', 'level-head');
      const name = button(topic.name, () => openBranch(topic.id), 'level-name');
      name.title = 'Открыть ветку «' + topic.name + '»';
      head.append(name, element('span', 'level-badge', topic.level_name));
      const meta = element('small', 'level-meta', knowledgeCount(topic.count) + ' · ' + topic.sources + ' ' +
        plural(topic.sources, 'источник', 'источника', 'источников') + (topic.week ? ' · +' + topic.week + ' за неделю' : ''));
      const foot = element('div', 'level-foot');
      foot.append(element('span', 'level-hint', levelHint(topic)), sparkline(topic.spark || []));
      body.append(head, meta, foot);
      card.append(ring, body);
      box.append(card);
    });
    box.append(element('p', 'module-muted level-note',
      'Число в кольце — уровень темы, кольцо — путь до следующего. Уровень растёт с объёмом знаний и числом независимых источников. Это мера покрытия, а не проверка истинности.'));
  }
  // ---- Графики роста: одиннадцать разных взглядов на то, как растёт Мозг ----
  let growthData = null, chartNarrow = false;
  const GOLD = '#ecca7c', HEAT = ['#26221a', '#4a3c20', '#7a5e2c', '#b38a40', '#ecca7c'];
  const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
  function chartCard(box, title, note, className) {
    const card = element('section', 'chart-card ' + (className || ''));
    const head = element('div', 'chart-head');
    const text = element('div');
    text.append(element('h3', '', title));
    if (note) text.append(element('p', '', note));
    head.append(text);
    const body = element('div', 'chart-body');
    const tip = element('div', 'chart-tip');
    tip.hidden = true;
    card.append(head, body, tip);
    box.append(card);
    // Подсказка у метки: при наведении и при фокусе с клавиатуры.
    const bind = (node, lines) => {
      node.setAttribute('tabindex', '0');
      node.setAttribute('aria-label', lines.join(', '));
      const show = () => {
        tip.replaceChildren(element('strong', '', lines[0]), ...lines.slice(1).map(line => element('span', '', line)));
        tip.hidden = false;
        const cardBox = card.getBoundingClientRect(), mark = node.getBoundingClientRect();
        const left = mark.left + mark.width / 2 - cardBox.left;
        tip.style.left = Math.max(70, Math.min(cardBox.width - 70, left)) + 'px';
        tip.style.top = Math.max(8, mark.top - cardBox.top - 8) + 'px';
        node.classList.add('hot');
      };
      const hide = () => { tip.hidden = true; node.classList.remove('hot'); };
      node.addEventListener('pointerenter', show);
      node.addEventListener('focus', show);
      node.addEventListener('pointerleave', hide);
      node.addEventListener('blur', hide);
    };
    return {card, body, bind, head};
  }
  function chartSvg(width, height, label) {
    return svgEl('svg', {viewBox: `0 0 ${width} ${height}`, class: 'chart-svg', role: 'img', 'aria-label': label});
  }
  function chartText(x, y, text, className, anchor) {
    const node = svgEl('text', {x, y, class: className || 'chart-axis', 'text-anchor': anchor || 'middle'});
    node.textContent = text;
    return node;
  }
  function smooth(points) {
    // Плавная кривая через точки (монотонная по x), без выбросов за данные.
    if (points.length < 2) return points.length ? `M${points[0][0]} ${points[0][1]}` : '';
    let d = `M${points[0][0].toFixed(1)} ${points[0][1].toFixed(1)}`;
    for (let i = 1; i < points.length; i++) {
      const [x0, y0] = points[i - 1], [x1, y1] = points[i], mx = (x0 + x1) / 2;
      d += ` C${mx.toFixed(1)} ${y0.toFixed(1)} ${mx.toFixed(1)} ${y1.toFixed(1)} ${x1.toFixed(1)} ${y1.toFixed(1)}`;
    }
    return d;
  }
  function chartEmpty(body, text) {
    body.append(element('p', 'chart-empty', text));
  }

  // 1. Поток тем: каждая тема — свой цветной поток, толщина — сколько узнал за день.
  function chartStream(box, stream, dates) {
    const {body, bind} = chartCard(box, 'Поток тем', 'Как каждая тема наполнялась день за днём. Толщина потока — новые знания.', 'span-12 is-stream');
    const total = stream.reduce((sum, topic) => sum + topic.days.reduce((a, b) => a + b, 0), 0);
    if (!total) { chartEmpty(body, 'За 30 дней темы не пополнялись.'); return; }
    const W = chartNarrow ? 270 : 1000, H = chartNarrow ? 170 : 220, n = dates.length;
    // Скользящее среднее за три дня, чтобы поток не рвался в пустые дни.
    const soft = stream.map(topic => topic.days.map((_, i) => {
      const part = topic.days.slice(Math.max(0, i - 1), i + 2);
      return part.reduce((a, b) => a + b, 0) / part.length;
    }));
    const sums = dates.map((_, i) => soft.reduce((sum, days) => sum + days[i], 0));
    const top = Math.max(...sums, .5);
    const x = i => i / (n - 1) * W, y = v => H / 2 + v / top * (H / 2 - 12);
    const svgNode = chartSvg(W, H, 'Поток тем за 30 дней: ' + stream.map(topic => topic.name).join(', '));
    const base = sums.map(sum => -sum / 2);
    const layers = svgEl('g', {class: 'stream-layers'});
    soft.forEach((days, k) => {
      const lower = base.map((b, i) => b + soft.slice(0, k).reduce((sum, other) => sum + other[i], 0));
      const upper = lower.map((v, i) => v + days[i]);
      const up = smooth(upper.map((v, i) => [x(i), y(v)]));
      const down = smooth(lower.map((v, i) => [x(i), y(v)]).reverse()).replace(/^M/, 'L');
      const path = svgEl('path', {d: up + ' ' + down + ' Z', fill: topicColor(stream[k].id), class: 'stream-layer'});
      path.style.setProperty('--i', k);
      const sum = stream[k].days.reduce((a, b) => a + b, 0);
      bind(path, [stream[k].name, '+' + knowledgeCount(sum) + ' за 30 дней']);
      layers.append(path);
    });
    svgNode.append(layers);
    body.append(svgNode, chartDates(dates));
    const legend = element('div', 'chart-legend');
    stream.forEach(topic => {
      const chip = element('span', 'chart-key');
      chip.style.setProperty('--c', topicColor(topic.id));
      chip.append(element('i'), document.createTextNode(topic.name));
      legend.append(chip);
    });
    body.append(legend);
  }
  function chartDates(dates) {
    const axis = element('div', 'chart-dates');
    for (const index of [0, Math.floor(dates.length / 2), dates.length - 1]) {
      if (dates[index]) axis.append(element('span', '', index === dates.length - 1 ? 'сегодня' : shortDay(dates[index], true)));
    }
    return axis;
  }

  // 2. Прирост по дням: столбцы растут снизу, сегодняшний светится.
  function chartDaily(box, series) {
    const {body, bind} = chartCard(box, 'Прирост по дням', 'Сколько новых знаний Мозг получил в каждый из 30 дней.', 'span-8');
    const W = chartNarrow ? 270 : 600, H = 180, n = series.length, step = W / n, top = niceMax(Math.max(...series.map(day => day.added), 1));
    const svgNode = chartSvg(W, H + 4, 'Прирост по дням: всего ' + series.reduce((sum, day) => sum + day.added, 0));
    const defs = svgEl('defs');
    const gradient = svgEl('linearGradient', {id: 'chart-bar-fill', x1: 0, y1: 0, x2: 0, y2: 1});
    gradient.append(svgEl('stop', {offset: 0, 'stop-color': '#fff1c8'}), svgEl('stop', {offset: 1, 'stop-color': '#9c7a3a'}));
    defs.append(gradient);
    svgNode.append(defs);
    for (const value of [top, top / 2]) {
      svgNode.append(svgEl('line', {x1: 0, x2: W, y1: H - value / top * H, y2: H - value / top * H, class: 'chart-grid'}));
      svgNode.append(chartText(2, H - value / top * H - 4, Number.isInteger(value) ? value : value.toFixed(1), 'chart-axis', 'start'));
    }
    svgNode.append(svgEl('line', {x1: 0, x2: W, y1: H, y2: H, class: 'chart-base'}));
    series.forEach((day, i) => {
      const h = day.added ? Math.max(4, day.added / top * H) : 2;
      const bar = svgEl('rect', {x: i * step + step * .19, y: H - h, width: step * .62, height: h, rx: Math.min(4, step * .3),
        class: 'chart-bar' + (day.added ? '' : ' zero') + (i === n - 1 ? ' today' : ''), fill: day.added ? 'url(#chart-bar-fill)' : ''});
      bar.style.setProperty('--i', i);
      bind(bar, [shortDay(day.date, true), day.added ? '+' + knowledgeCount(day.added) : 'без новых знаний']);
      svgNode.append(bar);
    });
    body.append(svgNode, chartDates(series.map(day => day.date)));
  }

  // 3. Часы Мозга: в какие часы суток он узнаёт новое.
  function chartClock(box, hours) {
    const {body, bind} = chartCard(box, 'Часы Мозга', 'В какое время суток приходят знания.', 'span-4');
    const total = hours.reduce((a, b) => a + b, 0);
    if (!total) { chartEmpty(body, 'Пока нет данных.'); return; }
    const S = 260, c = S / 2, inner = 42, outer = 112, top = Math.max(...hours);
    const peak = hours.indexOf(top);
    const svgNode = chartSvg(S, S, 'Часы Мозга: больше всего знаний около ' + peak + ' часов');
    svgNode.append(svgEl('circle', {cx: c, cy: c, r: outer, class: 'clock-ring'}), svgEl('circle', {cx: c, cy: c, r: inner + (outer - inner) / 2, class: 'clock-ring'}));
    const arc = (r, a) => [c + Math.sin(a) * r, c - Math.cos(a) * r];
    hours.forEach((value, hour) => {
      const a0 = hour / 24 * Math.PI * 2 + .03, a1 = (hour + 1) / 24 * Math.PI * 2 - .03;
      const r = inner + (value ? Math.max(.08, Math.sqrt(value / top)) : .03) * (outer - inner);
      const [x0, y0] = arc(inner, a0), [x1, y1] = arc(r, a0), [x2, y2] = arc(r, a1), [x3, y3] = arc(inner, a1);
      const d = `M${x0.toFixed(1)} ${y0.toFixed(1)} L${x1.toFixed(1)} ${y1.toFixed(1)} A${r.toFixed(1)} ${r.toFixed(1)} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)} L${x3.toFixed(1)} ${y3.toFixed(1)} A${inner} ${inner} 0 0 0 ${x0.toFixed(1)} ${y0.toFixed(1)}Z`;
      const wedge = svgEl('path', {d, class: 'clock-wedge' + (value ? '' : ' zero') + (hour === peak ? ' peak' : '')});
      wedge.style.setProperty('--i', hour);
      wedge.style.transformOrigin = `${c}px ${c}px`;
      bind(wedge, [hour + ':00–' + (hour + 1) % 24 + ':00', value ? '+' + knowledgeCount(value) : 'тишина']);
      svgNode.append(wedge);
    });
    for (const [hour, label] of [[0, '0'], [6, '6'], [12, '12'], [18, '18']]) {
      const [x, y] = arc(outer + 13, hour / 24 * Math.PI * 2);
      svgNode.append(chartText(x, y + 4, label));
    }
    svgNode.append(chartText(c, c - 2, peak + ' ч', 'clock-peak'), chartText(c, c + 16, 'пик', 'chart-axis'));
    body.append(svgNode);
  }

  // 4. Календарь: 12 недель, чем ярче клетка — тем больше узнал.
  function chartHeatmap(box, days) {
    const {body, bind} = chartCard(box, 'Календарь роста', 'Двенадцать недель. Яркая клетка — день, когда Мозг узнал много.', 'span-8');
    const cell = 15, gap = 4, left = 26, topPad = 18;
    const first = new Date(days[0].date + 'T12:00:00');
    const shift = (first.getDay() + 6) % 7;
    const cols = Math.ceil((days.length + shift) / 7);
    const W = left + cols * (cell + gap), H = topPad + 7 * (cell + gap);
    const top = Math.max(...days.map(day => day.added), 1);
    const svgNode = chartSvg(W, H, 'Календарь роста за 12 недель');
    svgNode.style.maxWidth = Math.round(W * 1.9) + 'px';
    [0, 2, 4].forEach(row => svgNode.append(chartText(0, topPad + row * (cell + gap) + cell - 3, WEEKDAYS[row], 'chart-axis', 'start')));
    let month = -1;
    days.forEach((day, index) => {
      const pos = index + shift, col = Math.floor(pos / 7), row = pos % 7;
      const moment = new Date(day.date + 'T12:00:00');
      if (moment.getMonth() !== month && row === 0) {
        month = moment.getMonth();
        svgNode.append(chartText(left + col * (cell + gap), 11, moment.toLocaleDateString('ru-RU', {month: 'short'}).replace('.', ''), 'chart-axis', 'start'));
      }
      const level = day.added ? Math.max(1, Math.ceil(day.added / top * 4)) : 0;
      const rect = svgEl('rect', {x: left + col * (cell + gap), y: topPad + row * (cell + gap), width: cell, height: cell, rx: 3,
        fill: HEAT[level], class: 'heat-cell' + (level === 4 ? ' max' : '') + (index === days.length - 1 ? ' today' : '')});
      rect.style.setProperty('--i', col);
      bind(rect, [moment.toLocaleDateString('ru-RU', {day: 'numeric', month: 'long', weekday: 'short'}), day.added ? '+' + knowledgeCount(day.added) : 'без новых знаний']);
      svgNode.append(rect);
    });
    body.append(svgNode);
    const scale = element('div', 'heat-scale');
    scale.append(element('span', '', 'меньше'));
    HEAT.forEach(color => { const swatch = element('i'); swatch.style.background = color; scale.append(swatch); });
    scale.append(element('span', '', 'больше'));
    body.append(scale);
  }

  // 5. Откуда знания: документы и чат.
  function chartSources(box, sources) {
    const {body, bind} = chartCard(box, 'Откуда знания', 'Доля документов с Диска и разговоров в чате.', 'span-4 is-sources');
    const parts = [['Документы', sources.file, '#e8bb5c'], ['Чат', sources.chat, CHAT_COLOR], ['Другое', sources.other, '#8a826f']].filter(part => part[1]);
    const total = parts.reduce((sum, part) => sum + part[1], 0);
    if (!total) { chartEmpty(body, 'Знаний пока нет.'); return; }
    const S = 220, c = S / 2, r = 80, stroke = 26, length = 2 * Math.PI * r;
    const svgNode = chartSvg(S, S, parts.map(part => part[0] + ' ' + part[1]).join(', '));
    svgNode.append(svgEl('circle', {cx: c, cy: c, r, class: 'donut-track', 'stroke-width': stroke}));
    let offset = 0;
    const gapLen = parts.length > 1 ? 3 : 0;
    parts.forEach(([name, value, color], index) => {
      const share = value / total * length;
      const seg = svgEl('circle', {cx: c, cy: c, r, fill: 'none', stroke: color, 'stroke-width': stroke, class: 'donut-seg',
        'stroke-dasharray': `${Math.max(1, share - gapLen)} ${length}`, 'stroke-dashoffset': -offset, transform: `rotate(-90 ${c} ${c})`});
      seg.style.setProperty('--i', index);
      bind(seg, [name, knowledgeCount(value) + ' · ' + Math.round(value / total * 100) + '%']);
      svgNode.append(seg);
      offset += share;
    });
    svgNode.append(chartText(c, c + 4, total, 'donut-total'), chartText(c, c + 24, plural(total, 'знание', 'знания', 'знаний'), 'chart-axis'));
    body.append(svgNode);
    const legend = element('div', 'chart-legend column');
    parts.forEach(([name, value, color]) => {
      const chip = element('span', 'chart-key');
      chip.style.setProperty('--c', color);
      chip.append(element('i'), document.createTextNode(name), element('b', '', Math.round(value / total * 100) + '%'));
      legend.append(chip);
    });
    body.append(legend);
  }

  // 6. Карта тем: площадь — сколько знаний в теме.
  function squarify(items, x, y, w, h) {
    const out = [];
    let rest = items.slice();
    while (rest.length) {
      const total = rest.reduce((sum, item) => sum + item.value, 0);
      const horizontal = w >= h, side = horizontal ? h : w;
      let row = [], best = Infinity;
      for (const item of rest) {
        const next = row.concat(item), sum = next.reduce((s, it) => s + it.value, 0);
        const thick = sum / total * (horizontal ? w : h);
        const worst = Math.max(...next.map(it => { const len = it.value / sum * side; return Math.max(thick / len, len / thick); }));
        if (worst > best) break;
        best = worst; row = next;
      }
      const sum = row.reduce((s, it) => s + it.value, 0), thick = sum / total * (horizontal ? w : h);
      let pos = horizontal ? y : x;
      for (const item of row) {
        const len = item.value / sum * side;
        out.push(horizontal ? {...item, x, y: pos, w: thick, h: len} : {...item, x: pos, y, w: len, h: thick});
        pos += len;
      }
      if (horizontal) { x += thick; w -= thick; } else { y += thick; h -= thick; }
      rest = rest.slice(row.length);
    }
    return out;
  }
  function chartTreemap(box, topics) {
    const {body, bind} = chartCard(box, 'Карта тем', 'Чем больше плитка, тем больше знаний в теме.', 'span-6');
    if (!topics.length) { chartEmpty(body, 'Темы появятся с первыми знаниями.'); return; }
    const sorted = [...topics].sort((a, b) => b.count - a.count);
    const items = sorted.slice(0, 6).map(topic => ({name: topic.name, value: topic.count, color: topicColor(topic.id), week: topic.week}));
    const rest = sorted.slice(6).reduce((sum, topic) => sum + topic.count, 0);
    if (rest) items.push({name: 'Другие темы', value: rest, color: '#5d5647', week: 0});
    const W = chartNarrow ? 270 : 600, H = chartNarrow ? 270 : 260;
    const svgNode = chartSvg(W, H, 'Карта тем: ' + items.map(item => item.name + ' ' + item.value).join(', '));
    squarify(items.filter(item => item.value > 0), 0, 0, W, H).forEach((tile, index) => {
      const group = svgEl('g', {class: 'tree-tile'});
      group.style.setProperty('--i', index);
      const rect = svgEl('rect', {x: tile.x + 1.5, y: tile.y + 1.5, width: Math.max(0, tile.w - 3), height: Math.max(0, tile.h - 3), rx: 6, fill: tile.color});
      group.append(rect);
      if (tile.w > 70 && tile.h > 40) {
        const name = chartText(tile.x + 10, tile.y + 22, tile.name.length > (tile.w - 16) / 7.4 ? tile.name.slice(0, Math.floor((tile.w - 16) / 7.4) - 1) + '…' : tile.name, 'tree-name', 'start');
        group.append(name, chartText(tile.x + 10, tile.y + 42, tile.value, 'tree-value', 'start'));
      }
      bind(group, [tile.name, knowledgeCount(tile.value) + (tile.week ? ' · +' + tile.week + ' за неделю' : '')]);
      svgNode.append(group);
    });
    body.append(svgNode);
  }

  // 7. Сила тем: паутина по самым крупным темам.
  function chartRadar(box, topics) {
    const {body, bind} = chartCard(box, 'Сила тем', 'Объём знаний по главным темам: чем дальше от центра, тем сильнее тема.', 'span-6');
    const items = [...topics].sort((a, b) => b.count - a.count).slice(0, 6);
    if (items.length < 3) { chartEmpty(body, 'Паутина появится, когда тем станет хотя бы три.'); return; }
    const W = chartNarrow ? 270 : 600, H = chartNarrow ? 280 : 260, c = [W / 2, H / 2 + 6], R = chartNarrow ? 78 : 98, top = Math.max(...items.map(item => item.count));
    const svgNode = chartSvg(W, H, 'Сила тем: ' + items.map(item => item.name + ' ' + item.count).join(', '));
    const point = (i, share) => {
      const a = -Math.PI / 2 + i / items.length * Math.PI * 2;
      return [c[0] + Math.cos(a) * R * share * (chartNarrow ? 1 : 1.35), c[1] + Math.sin(a) * R * share];
    };
    for (const share of [.25, .5, .75, 1]) {
      svgNode.append(svgEl('polygon', {points: items.map((_, i) => point(i, share).map(v => v.toFixed(1)).join(',')).join(' '), class: 'radar-grid'}));
    }
    items.forEach((item, i) => {
      const [x, y] = point(i, 1);
      svgNode.append(svgEl('line', {x1: c[0], y1: c[1], x2: x, y2: y, class: 'radar-axis'}));
      const [lx, ly] = point(i, 1.16);
      svgNode.append(chartText(lx, ly + 4, item.name.length > 18 ? item.name.slice(0, 17) + '…' : item.name, 'radar-label', Math.abs(lx - c[0]) < 10 ? 'middle' : lx > c[0] ? 'start' : 'end'));
    });
    const shares = items.map(item => Math.max(.08, Math.sqrt(item.count / top)));
    const shape = svgEl('polygon', {points: shares.map((share, i) => point(i, share).map(v => v.toFixed(1)).join(',')).join(' '), class: 'radar-shape'});
    shape.style.transformOrigin = `${c[0]}px ${c[1]}px`;
    svgNode.append(shape);
    items.forEach((item, i) => {
      const [x, y] = point(i, shares[i]);
      const dot = svgEl('circle', {cx: x, cy: y, r: 6, fill: topicColor(item.id), class: 'radar-dot'});
      bind(dot, [item.name, knowledgeCount(item.count) + ' · уровень ' + item.level + ' «' + item.level_name + '»']);
      svgNode.append(dot);
    });
    body.append(svgNode);
  }

  // 8. Ветвление: сколько веток было к каждому дню.
  function chartBranches(box, series) {
    const {body, bind} = chartCard(box, 'Ветвление', 'Как прибавлялись ветки за 30 дней.', 'span-4');
    if (!series.length || !series[series.length - 1].total) { chartEmpty(body, 'Веток пока нет.'); return; }
    const W = 300, H = 150, n = series.length, low = series[0].total, high = Math.max(series[n - 1].total, low + 1);
    const x = i => i / (n - 1) * W, y = v => H - 10 - (v - low) / (high - low) * (H - 30);
    let d = `M0 ${y(series[0].total).toFixed(1)}`;
    series.forEach((day, i) => { if (i) d += ` H${x(i).toFixed(1)} V${y(day.total).toFixed(1)}`; });
    const svgNode = chartSvg(W, H, 'Ветвление: от ' + low + ' до ' + series[n - 1].total + ' веток');
    svgNode.append(svgEl('path', {d: d + ` V${H} H0 Z`, class: 'step-area'}), svgEl('path', {d, class: 'step-line', pathLength: 1}));
    series.forEach((day, i) => {
      if (!i || day.total === series[i - 1].total) return;
      const dot = svgEl('circle', {cx: x(i), cy: y(day.total), r: 4.5, class: 'step-dot'});
      bind(dot, [shortDay(day.date, true), '+' + (day.total - series[i - 1].total) + ' · всего ' + day.total]);
      svgNode.append(dot);
    });
    svgNode.append(chartText(W - 2, y(series[n - 1].total) - 10, series[n - 1].total, 'chart-value', 'end'));
    body.append(svgNode);
  }

  // 9. По неделям: восемь недель, последняя сравнивается с прошлой.
  function chartWeeks(box, weeks) {
    const {body, bind, head} = chartCard(box, 'По неделям', 'Новые знания за каждую из восьми недель.', 'span-4');
    const last = weeks[weeks.length - 1]?.added || 0, before = weeks[weeks.length - 2]?.added || 0;
    if (before || last) {
      const delta = before ? Math.round((last - before) / before * 100) : null;
      head.append(element('span', 'chart-delta' + (delta !== null && delta < 0 ? ' down' : ''), delta === null ? 'новая неделя' : (delta >= 0 ? '+' : '') + delta + '%'));
    }
    const W = 300, H = 150, top = niceMax(Math.max(...weeks.map(week => week.added), 1)), step = W / weeks.length;
    const svgNode = chartSvg(W, H + 18, 'По неделям: ' + weeks.map(week => week.added).join(', '));
    weeks.forEach((week, i) => {
      const h = week.added ? Math.max(4, week.added / top * (H - 22)) : 2;
      const bar = svgEl('rect', {x: i * step + step * .16, y: H - h, width: step * .68, height: h, rx: 4,
        class: 'week-bar' + (i === weeks.length - 1 ? ' current' : '') + (week.added ? '' : ' zero')});
      bar.style.setProperty('--i', i);
      bind(bar, [shortDay(week.since, true) + ' – ' + shortDay(week.until, true), '+' + knowledgeCount(week.added)]);
      svgNode.append(bar);
      if (week.added) svgNode.append(chartText(i * step + step / 2, H - h - 5, week.added, 'chart-value small'));
    });
    svgNode.append(chartText(step / 2, H + 15, '−7 нед.'), chartText(W - step / 2, H + 15, 'эта'));
    body.append(svgNode);
  }

  // 10. Ритм недели: в какие дни недели Мозг растёт.
  function chartWeekdays(box, weekdays) {
    const {body, bind} = chartCard(box, 'Ритм недели', 'В какие дни недели приходят знания.', 'span-4');
    const top = Math.max(...weekdays, 1);
    if (!weekdays.some(Boolean)) { chartEmpty(body, 'Пока нет данных.'); return; }
    const W = 300, H = 150, step = W / 7;
    const svgNode = chartSvg(W, H + 18, 'Ритм недели: ' + WEEKDAYS.map((name, i) => name + ' ' + weekdays[i]).join(', '));
    weekdays.forEach((value, i) => {
      const cx = i * step + step / 2, cy = H - 8 - value / top * (H - 26);
      svgNode.append(svgEl('line', {x1: cx, x2: cx, y1: H, y2: cy, class: 'pop-stem'}));
      const dot = svgEl('circle', {cx, cy, r: value ? 6 + value / top * 5 : 3, class: 'pop-dot' + (value === top ? ' peak' : '')});
      dot.style.setProperty('--i', i);
      bind(dot, [WEEKDAYS[i], value ? '+' + knowledgeCount(value) : 'тишина']);
      svgNode.append(dot, chartText(cx, H + 15, WEEKDAYS[i]));
    });
    body.append(svgNode);
  }

  // 11. Разговоры: сколько вы писали Tenmiyora каждый день.
  function chartChat(box, chat) {
    const {body, bind} = chartCard(box, 'Разговоры', 'Ваши сообщения в чате по дням. Темы разговоров видны на карте в ветке «Разговоры».', 'span-12 is-chat');
    const series = chat?.series || [];
    if (!series.some(day => day.messages)) { chartEmpty(body, 'За 30 дней сообщений не было.'); return; }
    const W = chartNarrow ? 270 : 1000, H = 150, n = series.length, top = niceMax(Math.max(...series.map(day => day.messages), 1));
    const x = i => i / (n - 1) * W, y = v => H - 6 - v / top * (H - 20);
    const line = smooth(series.map((day, i) => [x(i), y(day.messages)]));
    const svgNode = chartSvg(W, H, 'Разговоры за 30 дней: ' + series.reduce((sum, day) => sum + day.messages, 0) + ' сообщений');
    const defs = svgEl('defs');
    const gradient = svgEl('linearGradient', {id: 'chart-chat-fill', x1: 0, y1: 0, x2: 0, y2: 1});
    gradient.append(svgEl('stop', {offset: 0, 'stop-color': CHAT_COLOR, 'stop-opacity': '.4'}), svgEl('stop', {offset: 1, 'stop-color': CHAT_COLOR, 'stop-opacity': '0'}));
    defs.append(gradient);
    svgNode.append(defs, svgEl('line', {x1: 0, x2: W, y1: H, y2: H, class: 'chart-base'}),
      svgEl('path', {d: line + ` L${W} ${H} L0 ${H} Z`, fill: 'url(#chart-chat-fill)', class: 'chat-area'}),
      svgEl('path', {d: line, class: 'chat-line', pathLength: 1}));
    series.forEach((day, i) => {
      if (!day.messages) return;
      const dot = svgEl('circle', {cx: x(i), cy: y(day.messages), r: 5, class: 'chat-dot'});
      bind(dot, [shortDay(day.date, true), messageCount(day.messages)]);
      svgNode.append(dot);
    });
    body.append(svgNode, chartDates(series.map(day => day.date)));
  }

  function renderCharts() {
    const box = $('brain-charts');
    if (!box || !growthData) return;
    // Вкладка «Рост» может быть ещё скрыта: тогда ширину берём у страницы.
    chartNarrow = (box.clientWidth || document.getElementById('main-content').clientWidth || innerWidth) < 560;
    box.replaceChildren();
    const charts = growthData.charts || {};
    const dates = growthData.series.map(day => day.date);
    chartStream(box, charts.stream || [], dates);
    chartDaily(box, growthData.series);
    chartClock(box, charts.hours || []);
    chartHeatmap(box, charts.heatmap || []);
    chartSources(box, charts.sources || {file: 0, chat: 0, other: 0});
    chartTreemap(box, growthTopics);
    chartRadar(box, growthTopics);
    chartWeeks(box, charts.weeks || []);
    chartWeekdays(box, charts.weekdays || []);
    chartBranches(box, charts.branches || []);
    chartChat(box, brainData.chat);
  }
  async function loadGrowth() {
    try {
      const data = await request('brain/growth?' + new URLSearchParams({days: 30, offset: -new Date().getTimezoneOffset()}));
      growthData = data;
      growthTopics = data.topics || [];
      growthBrain = data.brain || null;
      renderStageLine();
      renderOverview();
      renderBrainLevel(data.brain);
      renderGrowthChart(data.series);
      renderDiary(data.diary);
      renderLevels(growthTopics);
      mapFresh = data.branches_week || {};
    } catch (error) {
      $('brain-growth-chart').replaceChildren(emptyState(error.message, 'spark'));
    }
  }

  // Ветки из чата: темы ваших разговоров. Это не знания, а то, о чём вы говорили.
  const CHAT_ROOT = 'chat';
  function chatBranches(chat) {
    if (!chat.topics.length) return [];
    // Счёт корня приходит с сервера по самим сообщениям, а не складывается из тем.
    const root = {id: CHAT_ROOT, parent: null, name: 'Разговоры', facts: 0, chat: true,
      created: chat.first, last: chat.last, week: chat.week, messages: chat.messages, spark: chat.spark};
    return [root, ...chat.topics.map(topic => ({id: 'chat:' + topic.name, parent: CHAT_ROOT, name: topic.name,
      facts: topic.messages, created: topic.first, last: topic.last, week: topic.week, chat: true, topic}))];
  }
  function messageCount(count) {
    return count + ' ' + plural(count, 'сообщение', 'сообщения', 'сообщений');
  }
  async function loadBrain() {
    if (brainLoading) return;
    brainLoading = true;
    const refresh = $('brain-refresh');
    refresh.classList.add('spinning'); refresh.disabled = true;
    try {
      const data = await request('brain?' + new URLSearchParams({offset: -new Date().getTimezoneOffset()}));
      const real = data.branches || [], chat = data.chat || {topics: [], series: [], messages: 0};
      brainData = {branches: real.concat(chatBranches(chat)), real, recent: data.recent || [], chat};
      const stats = data.stats || {};
      $('brain-branches-count').textContent = real.length;
      $('brain-talks-count').textContent = chat.topics.length;
      $('brain-facts-count').textContent = stats.facts ?? real.reduce((count, row) => count + row.facts, 0);
      $('brain-files-count').textContent = stats.files ?? 0;
      $('brain-chat-count').textContent = stats.chat ?? 0;
      renderEvents();
      await Promise.all([loadLab(), loadGrowth(), loadActivity(), loadIdle()]);
      mapBorn = newBranches(brainData.branches.map(row => row.id));
      renderMap();
      renderCharts();
    } catch (error) { message(error.message); }
    finally { brainLoading = false; refresh.classList.remove('spinning'); refresh.disabled = false; }
  }
  // Живая карта знаний: ядро, ветки по кругу, знания-листья, потоки и рост.
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const MAP = {width: 1000, height: 640, rx: 1.5, ring: 150};
  let mapNodes = new Map(), mapFresh = {}, mapPlayed = false, openNodeId = null, mapTotal = 0, growthRun = 0;
  // Все ветки дерева, даже не нарисованные: по ним открывается панель ветки из знаний и уровней.
  let mapAll = new Map();
  let mapTopics = [], mapActivity = {synapses: [], alive: {}}, mapSynapses = [], mapBorn = new Set(), pulseSeen = null, sleepMode = null;
  const KNOWN_KEY = 'tenmiyora.brain.known', DAY = 864e5;
  async function loadActivity() {
    try {
      mapActivity = await request('brain/activity');
      if (pulseSeen === null) pulseSeen = mapActivity.last_pulse || 0;
    } catch { mapActivity = {synapses: [], alive: {}}; }
  }
  // Новые с прошлого визита ветки «рождаются» на карте. Первый визит — без рождений.
  function newBranches(ids) {
    let known = null;
    try { known = JSON.parse(localStorage.getItem(KNOWN_KEY)); } catch { known = null; }
    try { localStorage.setItem(KNOWN_KEY, JSON.stringify(ids)); } catch { /* без памяти браузера просто без рождений */ }
    if (!Array.isArray(known)) return mapBorn;
    const seen = new Set(known);
    return new Set([...mapBorn, ...ids.filter(id => !seen.has(id))]);
  }
  // Когда ветку в последний раз пополняли или спрашивали: своё время или подветок.
  function lastAlive(item) {
    const own = Date.parse((item.node.chat ? item.node.last : mapActivity.alive?.[item.node.id]) || '') || 0;
    return Math.max(own, ...item.children.map(lastAlive));
  }
  const calm = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  // Цвета тем подобраны под тёмно-золотой фон и различимы между собой.
  const TOPIC_COLORS = ['#e8bb5c', '#5ec8b8', '#a58cf0', '#ef8a6b', '#6fa8ef', '#e27fae', '#a6cc6a', '#f2a14a'];
  const CHAT_COLOR = '#8fd3f4';
  // Цвет следует за темой, а не за местом в списке: тот же, что на карте, в любом графике.
  function topicColor(id) {
    const roots = brainData.real.filter(item => item.parent === null || !brainData.real.some(other => other.id === item.parent))
      .map(item => item.id).sort((a, b) => a - b);
    const index = roots.indexOf(id);
    return TOPIC_COLORS[(index < 0 ? 0 : index) % TOPIC_COLORS.length];
  }
  function svg(tag, attrs, className) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    if (className) node.setAttribute('class', className);
    return node;
  }
  function polar(angle, radius) {
    return [MAP.width / 2 + Math.cos(angle) * radius * MAP.rx, MAP.height / 2 + Math.sin(angle) * radius];
  }
  // Карта по уровням: сначала только главные темы, подветки — у раскрытой темы.
  // Так карта не превращается в кашу, когда веток становятся сотни.
  let openTopic = null;
  function layoutMap() {
    const branches = brainData.branches;
    const known = new Set(branches.map(item => item.id));
    const roots = branches.filter(item => item.parent === null || !known.has(item.parent))
      .sort((a, b) => subtreeTotal(b) - subtreeTotal(a));
    if (openTopic !== null && !roots.some(root => root.id === openTopic)) openTopic = null;
    const placed = [];
    // Раскрытой теме нужно место под два внешних кольца, иначе подветки срежет край карты.
    const deep = openTopic !== null;
    const extra = deep ? (MAP.narrow ? 78 : 134) : 0;
    const outer = Math.min((MAP.width / 2 - 56) / MAP.rx, MAP.height / 2 - 52);
    // Чем больше тем, тем шире круг: иначе узлы слипаются у ядра.
    const ring = MAP.ring = Math.max(92, Math.min(252, 128 + roots.length * 7, outer - extra));
    const deepest = MAP.narrow ? 2 : 3;
    mapAll = new Map();
    // Дерево ветки строится целиком, даже если часть узлов на карте не рисуется:
    // панель ветки должна показывать все подветки и их знания, что бы ни было видно.
    const model = (node, parent) => {
      const item = {node, depth: parent ? parent.depth + 1 : 1, parent, total: subtreeTotal(node),
                    children: [], hidden: 0, ghost: false, angle: 0, x: 0, y: 0, size: 0};
      mapAll.set(node.id, item);
      item.children = childrenOf(node.id).map(kid => model(kid, item));
      return item;
    };
    const place = (item, from, to) => {
      const depth = item.depth;
      const angle = (from + to) / 2;
      const radius = [0, ring, ring + 78, ring + 134][Math.min(depth, 3)];
      // Пока одна тема раскрыта, остальные отступают в тень точками: место — раскрытой.
      item.ghost = deep && depth === 1 && item.node.id !== openTopic;
      item.size = item.ghost ? 6 : depth === 1 ? Math.min(28, 10 + Math.sqrt(item.total) * 2.6)
        : Math.min(15, 5 + Math.sqrt(item.total) * 1.6);
      item.angle = angle;
      [item.x, item.y] = polar(angle, radius);
      placed.push(item);
      // Подветки рисуются только у раскрытой темы и только два уровня вглубь.
      if (depth >= deepest || (depth === 1 && item.node.id !== openTopic)) {
        item.hidden = item.children.length;
        return;
      }
      const shown = [...item.children].sort((a, b) => b.total - a.total)
        .slice(0, depth === 1 ? (MAP.narrow ? 8 : 12) : 6);
      item.hidden = item.children.length - shown.length;
      const weight = shown.reduce((sum, kid) => sum + Math.sqrt(kid.total + 1), 0) || 1;
      let start = from;
      for (const kid of shown.sort((a, b) => a.node.name.localeCompare(b.node.name, 'ru'))) {
        const share = (to - from) * Math.sqrt(kid.total + 1) / weight;
        place(kid, start, start + share);
        start += share;
      }
    };
    // Темы делят круг поровну: большая тема не прижимает соседей друг к другу.
    const weights = roots.map(root => root.id === openTopic ? Math.max(roots.length * .7, 6) : 1);
    const sum = weights.reduce((a, b) => a + b, 0) || 1;
    // Раскрытая тема всегда разворачивается вправо: там больше всего места под подветки.
    let cursor = -Math.PI / 2;
    if (deep) {
      const index = roots.findIndex(root => root.id === openTopic);
      const before = weights.slice(0, index).reduce((a, b) => a + b, 0) + weights[index] / 2;
      cursor = -Math.PI * 2 * before / sum;
    }
    roots.forEach((root, index) => {
      const share = Math.PI * 2 * weights[index] / sum;
      place(model(root, null), cursor, cursor + share);
      cursor += share;
    });
    return placed;
  }
  function linkPath(from, to) {
    const [cx, cy] = from ? [from.x, from.y] : [MAP.width / 2, MAP.height / 2];
    const bend = polar(to.angle, [0, MAP.ring * .5, MAP.ring + 30, MAP.ring + 100][Math.min(to.depth, 3)]);
    return `M${cx.toFixed(1)},${cy.toFixed(1)} Q${bend[0].toFixed(1)},${bend[1].toFixed(1)} ${to.x.toFixed(1)},${to.y.toFixed(1)}`;
  }
  // Подпись ветки: короткая, в одну-две строки, и не вылезает за край карты.
  // Длинное название переносится по словам; полное — во всплывающей подсказке и карточке.
  const LABEL = {font: [13, 11], narrow: [18, 15], line: 1.2, perLine: 16};
  function wrapName(name, perLine) {
    const lines = [];
    let line = '';
    for (const word of name.split(/\s+/)) {
      if (!line) line = word;
      else if ((line + ' ' + word).length <= perLine) line += ' ' + word;
      else { lines.push(line); line = word; }
    }
    if (line) lines.push(line);
    if (lines.length > 2) lines.splice(1, lines.length, lines.slice(1).join(' '));
    // Обрезаем по границе слова, чтобы не было «персоналом и ка…».
    return lines.map(text => {
      if (text.length <= perLine) return text;
      const cut = text.slice(0, perLine - 1), space = cut.lastIndexOf(' ');
      return (space > perLine / 3 ? cut.slice(0, space) : cut).trimEnd() + '…';
    });
  }
  function placeLabel(label, item) {
    const root = item.depth === 1, font = (MAP.narrow ? LABEL.narrow : LABEL.font)[root ? 0 : 1];
    const char = font * .56, pad = 6, name = item.node.name;
    const gap = item.size + 7, right = MAP.width - item.x - gap - pad, left = item.x - gap - pad;
    let outward = Math.cos(item.angle) >= 0;
    if (!root) {
      const wanted = Math.min(name.length, LABEL.perLine) * char;
      if ((outward ? right : left) < wanted && (outward ? left : right) > (outward ? right : left)) outward = !outward;
    }
    const room = root ? MAP.width - pad * 2 : (outward ? right : left);
    const lines = wrapName(name, Math.max(5, Math.min(LABEL.perLine, Math.floor(room / char))));
    const step = font * LABEL.line;
    // Корень подписан над узлом (строки растут вверх), ветка — сбоку, по центру.
    const first = root ? -item.size - 6 - (lines.length - 1) * step : 4 - (lines.length - 1) * step / 2;
    let x = 0, anchor = 'middle';
    if (root) {
      const half = Math.max(...lines.map(text => text.length)) * char / 2;
      x = Math.max(pad + half - item.x, Math.min(0, MAP.width - pad - half - item.x));
    } else {
      x = outward ? gap : -gap;
      anchor = outward ? 'start' : 'end';
    }
    label.setAttribute('text-anchor', anchor);
    label.replaceChildren(...lines.map((text, i) => {
      const span = svg('tspan', {x: x.toFixed(1), y: (first + i * step).toFixed(1)});
      span.textContent = text;
      return span;
    }));
    // Место, которое подпись займёт на карте: по нему потом убираются наложения.
    const width = Math.max(...lines.map(text => text.length)) * char;
    const shift = anchor === 'middle' ? -width / 2 : anchor === 'end' ? -width : 0;
    return {x1: item.x + x + shift, x2: item.x + x + shift + width,
            y1: item.y + first - font, y2: item.y + first + (lines.length - 1) * step + 3};
  }
  // Подписи, которые налезают на соседние, прячутся: крупная тема важнее мелкой ветки.
  // Спрятанная подпись возвращается при наведении и когда ветка открыта.
  function hideCrowdedLabels(labelled) {
    const boxes = labelled.map(entry => Object.assign({rank: entry.item.depth * 1e6 - entry.item.total}, entry.box));
    const hidden = TenmiyoraLayout.crowded(boxes);
    labelled.forEach((entry, index) => { if (hidden.has(index)) entry.group.classList.add('quiet'); });
  }

  function renderMap() {
    const box = $('brain-map');
    closeMapCard();
    const narrow = box.clientWidth > 0 && box.clientWidth < 640;
    Object.assign(MAP, narrow ? {width: 600, height: 720, rx: 1, narrow} : {width: 1000, height: 640, rx: 1.5, narrow});
    box.classList.toggle('narrow', narrow);
    box.replaceChildren();
    mapNodes = new Map();
    growthRun++;  // Старый показ роста относится к прежней карте.
    $('brain-map-replay').disabled = false;
    const placed = layoutMap();
    const labelled = [];
    // Свой цвет у каждой темы: ветка, её подветки, знания и токи окрашены одинаково.
    const tops = placed.filter(item => item.depth === 1).sort((a, b) => Number(Boolean(a.node.chat)) - Number(Boolean(b.node.chat)) || a.node.id - b.node.id);
    tops.forEach(item => { item.color = item.node.chat ? CHAT_COLOR : topicColor(item.node.id); });
    for (const item of placed) if (!item.color) { let top = item; while (top.parent) top = top.parent; item.color = top.color || TOPIC_COLORS[0]; }
    const total = mapTotal = brainData.real.reduce((sum, item) => sum + item.facts, 0);
    const shown = brainData.branches.filter(item => item.id !== CHAT_ROOT).length;
    $('brain-map-count').textContent = shown ? shown + ' ' + plural(shown, 'ветка', 'ветки', 'веток') : '';
    const root = svg('svg', {viewBox: `0 0 ${MAP.width} ${MAP.height}`, role: 'group', 'aria-label': 'Карта знаний Мозга'}, 'brain-map-svg');
    const defs = svg('defs');
    defs.innerHTML = '<radialGradient id="map-core"><stop offset="0" stop-color="#fff3cf"/><stop offset=".45" stop-color="#ecca7c"/><stop offset="1" stop-color="#9c7a3a"/></radialGradient>' +
      '<radialGradient id="map-halo"><stop offset="0" stop-color="#d4af5f" stop-opacity=".35"/><stop offset="1" stop-color="#d4af5f" stop-opacity="0"/></radialGradient>' +
      '<radialGradient id="map-node"><stop offset="0" stop-color="#ecca7c"/><stop offset="1" stop-color="#7a5e2c"/></radialGradient>' +
      '<filter id="map-glow" x="-1" y="-1" width="3" height="3"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>';
    root.append(defs);
    // Фон: орбиты и мерцающие звёзды.
    const sky = svg('g', {}, 'map-sky');
    for (const radius of [MAP.ring * .55, MAP.ring, MAP.ring + 78]) sky.append(svg('ellipse', {cx: MAP.width / 2, cy: MAP.height / 2, rx: radius * MAP.rx, ry: radius}, 'map-orbit'));
    for (let i = 0; i < 46; i++) {
      const star = svg('circle', {cx: (i * 211 % MAP.width), cy: (i * 137 % MAP.height), r: i % 5 ? .8 : 1.4}, 'map-star');
      star.style.setProperty('--d', (i % 7) * .6 + 's');
      sky.append(star);
    }
    const halo = svg('circle', {cx: MAP.width / 2, cy: MAP.height / 2, r: 150}, 'map-halo');
    halo.style.transformOrigin = `${MAP.width / 2}px ${MAP.height / 2}px`;
    root.append(sky, halo);
    // Волны сна расходятся от ядра, когда Мозг «спит» и перебирает знания.
    const waves = svg('g', {}, 'map-waves');
    for (let i = 0; i < 3; i++) {
      const wave = svg('ellipse', {cx: MAP.width / 2, cy: MAP.height / 2, rx: 120 * MAP.rx, ry: 120}, 'map-wave');
      wave.style.animationDelay = i * 2.4 + 's';
      waves.append(wave);
    }
    const synapses = svg('g', {}, 'map-synapses'), links = svg('g', {}, 'map-links'), flows = svg('g', {}, 'map-flows');
    const nodes = svg('g', {}, 'map-nodes'), impulses = svg('g', {}, 'map-impulses');
    root.append(waves, synapses, links, flows, impulses, nodes);
    mapSynapses = [];
    const order = [...placed].sort((a, b) => String(a.node.created).localeCompare(String(b.node.created)) || a.depth - b.depth);
    order.forEach((item, index) => { item.order = index; });
    const now = Date.now();
    placed.forEach((item, index) => {
      const fresh = (item.node.chat ? item.node.week : mapFresh[item.node.id]) || 0, born = mapBorn.has(item.node.id);
      // Давно не пополнялась и не понадобилась — ветка тускнеет; вопрос о ней снова её зажжёт.
      const alive = lastAlive(item), idle = alive ? (now - alive) / DAY : 0;
      item.idleDays = Math.floor(idle);
      const rest = fresh || born ? '' : idle > 45 ? ' dormant' : idle > 14 ? ' resting' : '';
      const chatty = (item.node.chat ? ' chat' : '') + (item.ghost ? ' ghost' : '');
      const path = svg('path', {d: linkPath(item.parent, item), id: 'map-link-' + index}, 'map-link depth-' + item.depth + (fresh ? ' fresh' : '') + (born ? ' born' : '') + rest + chatty);
      path.style.setProperty('--w', Math.max(.8, Math.min(4, Math.sqrt(item.total) * (item.depth === 1 ? .9 : .5))));
      path.style.setProperty('--o', item.order);
      links.append(path);
      path.style.setProperty('--c', item.color);
      // Нейронные токи: светящийся штрих плавно течёт от ядра к ветке. Больше знаний — больше токов.
      if (!calm() && !item.ghost && (item.depth === 1 || fresh) && item.total) {
        const currents = item.depth === 1 ? Math.min(3, 1 + Math.floor(item.total / 15)) : 1;
        for (let p = 0; p < currents; p++) {
          const current = svg('path', {d: path.getAttribute('d'), pathLength: 100}, 'map-current' + (fresh ? ' fresh' : ''));
          current.style.setProperty('--c', item.color);
          current.style.animationDuration = (4.2 + (index % 4) * .8) + 's';
          current.style.animationDelay = (p * 1.6 + index * .23).toFixed(2) + 's';
          flows.append(current);
        }
      }
      const group = svg('g', {transform: `translate(${item.x.toFixed(1)} ${item.y.toFixed(1)})`, tabindex: 0, role: 'button',
        'aria-label': item.node.name + ': ' + (item.node.chat ? messageCount(item.total) + ' в чате' : knowledgeCount(item.total)) + (fresh ? ', +' + fresh + ' за неделю' : '')},
        'map-node depth-' + item.depth + (fresh ? ' fresh' : '') + (item.depth > 1 ? ' small' : '') + (born ? ' born' : '') + rest + chatty);
      group.style.setProperty('--o', item.order);
      group.style.setProperty('--c', item.color);
      const inner = svg('g', {}, 'map-node-body');
      if (fresh) inner.append(svg('circle', {r: item.size + 9}, 'map-aura'));
      if (born) for (let ring = 0; ring < 2; ring++) {
        const burst = svg('circle', {r: item.size + 6}, 'map-birth');
        burst.style.animationDelay = (1 + ring * .5) + 's';
        inner.append(burst);
      }
      // Листья-знания вращаются вокруг ветки.
      const orbit = svg('g', {}, 'map-leaves');
      orbit.style.setProperty('--spin', (18 + (index % 5) * 6) + 's');
      const leaves = item.ghost ? 0 : Math.min(item.depth === 1 ? 14 : 7, item.node.facts);
      for (let l = 0; l < leaves; l++) {
        const a = l / leaves * Math.PI * 2, r = item.size + 5 + (l % 2) * 3;
        orbit.append(svg('circle', {cx: (Math.cos(a) * r).toFixed(1), cy: (Math.sin(a) * r).toFixed(1), r: item.depth === 1 ? 1.8 : 1.3}, 'map-leaf'));
      }
      inner.append(orbit, svg('circle', {r: item.size}, 'map-dot'),
        svg('circle', {r: (item.size * .42).toFixed(1), cx: (-item.size * .3).toFixed(1), cy: (-item.size * .32).toFixed(1)}, 'map-dot-shine'));
      if (item.node.chat && item.depth === 1) {
        // Ветка разговоров отмечена облачком реплики.
        inner.append(svg('path', {d: 'M-7 -5h14a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3h-7l-5 4v-4h-2a3 3 0 0 1-3-3v-6a3 3 0 0 1 3-3z', transform: `translate(${-item.size * .9} ${item.size * .8}) scale(.8)`}, 'map-chat-mark'));
      }
      if (item.depth === 1 && !item.ghost) {
        const count = svg('text', {y: 4}, 'map-count');
        count.textContent = item.total;
        inner.append(count);
      }
      const tip = svg('title');
      tip.textContent = item.node.name;
      group.append(tip);
      const label = svg('text', {}, 'map-label' + (item.depth === 1 ? ' root' : ''));
      const box = placeLabel(label, item);
      // Имя притухшей темы не занимает место на карте: оно есть в панели тем и в подсказке.
      if (item.ghost) group.classList.add('quiet'); else labelled.push({item, group, box});
      inner.append(label);
      // «новая» — только у самых свежих веток: когда новыми стали все, метка ничего не говорит.
      const newest = born && (mapBorn.size <= 6 || item.depth === 1);
      if ((fresh || newest) && !item.ghost) {
        const badge = svg('text', {x: 0, y: item.size + (item.depth === 1 ? 16 : 13), 'text-anchor': 'middle'}, 'map-fresh');
        badge.textContent = newest ? 'новая' : '+' + fresh;
        inner.append(badge);
      }
      // Сколько подветок спрятано под этой темой.
      if (item.hidden && !item.ghost) {
        const more = svg('g', {transform: `translate(0 ${(item.size + (item.depth === 1 ? 2 : 1)).toFixed(1)})`}, 'map-more');
        const text = svg('text', {y: 15, 'text-anchor': 'middle'}, 'map-more-count');
        text.textContent = '+' + item.hidden;
        more.append(text);
        inner.append(more);
      }
      group.append(inner);
      // Нажатие на тему раскрывает её подветки, на подветку — открывает панель.
      const open = () => { if (item.depth === 1 && childrenOf(item.node.id).length) toggleTopic(item.node.id); else openMapCard(item); };
      group.addEventListener('click', open);
      group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } });
      group.addEventListener('mouseenter', () => highlightChain(item, true));
      group.addEventListener('mouseleave', () => highlightChain(item, false));
      nodes.append(group);
      mapNodes.set(item.node.id, {item, group, path});
    });
    // Синапсы: дуги между темами с общими источниками или вместе нужными в ответах.
    (mapActivity.synapses || []).forEach((link, index) => {
      const a = mapNodes.get(link.a)?.item, b = mapNodes.get(link.b)?.item;
      if (!a || !b) return;
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      const qx = mx + (MAP.width / 2 - mx) * .45, qy = my + (MAP.height / 2 - my) * .45;
      const d = `M${a.x.toFixed(1)},${a.y.toFixed(1)} Q${qx.toFixed(1)},${qy.toFixed(1)} ${b.x.toFixed(1)},${b.y.toFixed(1)}`;
      // Дуга переливается из цвета одной темы в цвет другой — видно, кто с кем связан.
      const gradient = svg('linearGradient', {id: 'map-syn-grad-' + index, gradientUnits: 'userSpaceOnUse',
        x1: a.x.toFixed(1), y1: a.y.toFixed(1), x2: b.x.toFixed(1), y2: b.y.toFixed(1)});
      gradient.append(svg('stop', {offset: 0, 'stop-color': a.color}), svg('stop', {offset: 1, 'stop-color': b.color}));
      defs.append(gradient);
      const path = svg('path', {d, id: 'map-syn-' + index, stroke: `url(#map-syn-grad-${index})`}, 'map-synapse' + (link.used ? ' used' : ''));
      path.style.setProperty('--w', Math.min(3, .6 + Math.log2(1 + link.weight) * .45).toFixed(2));
      const why = [];
      if (link.shared) why.push(link.shared + ' ' + plural(link.shared, 'общий источник', 'общих источника', 'общих источников'));
      if (link.used) why.push(link.used + ' ' + plural(link.used, 'раз', 'раза', 'раз') + ' вместе в ответах');
      const tip = svg('title');
      tip.textContent = a.node.name + ' ⇄ ' + b.node.name + (why.length ? ': ' + why.join(', ') : '');
      const hit = svg('path', {d}, 'map-synapse-hit');
      hit.append(tip);
      hit.addEventListener('mouseenter', () => { highlightChain(a, true, b); });
      hit.addEventListener('mouseleave', () => { highlightChain(a, false, b); });
      synapses.append(path, hit);
      // Обмен: навстречу друг другу плывут две искры, каждая в цвете своей темы.
      if (!calm()) for (const [from, color] of [[0, a.color], [1, b.color]]) {
        const spark = svg('circle', {r: link.used ? 2.2 : 1.6}, 'map-syn-spark');
        spark.style.setProperty('--c', color);
        const motion = svg('animateMotion', {dur: (7 + index % 5) + 's', begin: (index * .9 + from * 3.5).toFixed(1) + 's', repeatCount: 'indefinite',
          keyPoints: from ? '1;0' : '0;1', keyTimes: '0;1', calcMode: 'linear'});
        const ref = svg('mpath');
        ref.setAttribute('href', '#map-syn-' + index);
        motion.append(ref);
        spark.append(motion);
        synapses.append(spark);
      }
      mapSynapses.push({a: link.a, b: link.b, path});
    });
    // Ядро поверх всего: общий объём памяти.
    const core = svg('g', {transform: `translate(${MAP.width / 2} ${MAP.height / 2})`}, 'map-core');
    core.append(svg('circle', {r: 52}, 'map-core-ring'), svg('circle', {r: 34, fill: 'url(#map-core)', filter: 'url(#map-glow)'}, 'map-core-ball'));
    const coreCount = svg('text', {y: 6}, 'map-core-count');
    coreCount.textContent = total;
    const coreLabel = svg('text', {y: 52 + 20}, 'map-core-label');
    coreLabel.textContent = placed.length ? knowledgeCount(total).replace(/^\d+ /, '') : 'ждёт первых знаний';
    core.append(coreCount, coreLabel);
    root.append(core);
    box.append(root);
    root.style.setProperty('--count', placed.length || 1);
    if (!placed.length) box.append(element('p', 'brain-map-empty', 'Загрузите документ на Диск или расскажите что-нибудь в чате — здесь вырастут первые ветки.'));
    hideCrowdedLabels(labelled);
    renderLegend(tops);
    updateSleep();
    if (!mapPlayed && placed.length) { mapPlayed = true; playGrowth(); }
  }
  // Раскрытие темы: карта перерисовывается, выбранная тема получает больше места.
  function toggleTopic(id) {
    openTopic = openTopic === id ? null : id;
    mapPlayed = true;  // Повтор роста при раскрытии не нужен.
    renderMap();
    if (openTopic !== null) mapNodes.get(openTopic)?.group.focus({preventScroll: true});
    // На узком экране карта выше списка тем: показываем её, иначе раскрытие не видно.
    if (openTopic !== null && MAP.narrow) $('brain-map').scrollIntoView({block: 'center', behavior: calm() ? 'auto' : 'smooth'});
  }
  function highlightChain(item, on, partner) {
    const box = $('brain-map');
    box.classList.toggle('focusing', on);
    if (partner) for (let cur = partner; cur; cur = cur.parent) mapNodes.get(cur.node.id)?.group.classList.toggle('lit', on);
    for (let cur = item; cur; cur = cur.parent) {
      const entry = mapNodes.get(cur.node.id);
      entry?.group.classList.toggle('lit', on);
      entry?.path.classList.toggle('lit', on);
    }
    // Видно, с кем тема обменивается: её дуги и темы на том конце тоже светятся.
    for (const link of mapSynapses) {
      if (partner && !((link.a === item.node.id && link.b === partner.node.id) || (link.b === item.node.id && link.a === partner.node.id))) continue;
      if (link.a !== item.node.id && link.b !== item.node.id) continue;
      link.path.classList.toggle('lit', on);
      if (!partner) mapNodes.get(link.a === item.node.id ? link.b : link.a)?.group.classList.toggle('lit', on);
    }
  }
  // Легенда: цвет каждой темы; наведение подсвечивает тему, нажатие открывает её.
  function renderLegend(tops) {
    const box = $('brain-map-topics');
    if (!box) return;
    mapTopics = [...tops].sort((a, b) => b.total - a.total);
    $('brain-topics-count').textContent = mapTopics.length ? mapTopics.length + ' ' + plural(mapTopics.length, 'тема', 'темы', 'тем') : '';
    $('brain-topics-filter').hidden = mapTopics.length < 8;
    paintTopics();
  }
  // Список тем рядом с картой: цвет, название, доля знаний. Нажатие раскрывает тему.
  function paintTopics() {
    const box = $('brain-map-topics');
    if (!box) return;
    const query = $('brain-topics-filter').value.trim().toLowerCase();
    const shown = query ? mapTopics.filter(item => item.node.name.toLowerCase().includes(query)) : mapTopics;
    const largest = Math.max(...mapTopics.map(item => item.total), 1);
    box.replaceChildren();
    if (!shown.length) { box.append(element('p', 'module-muted topics-empty', query ? 'Такой темы нет.' : 'Темы появятся с первыми знаниями.')); return; }
    for (const item of shown) {
      const row = button('', () => { if (childrenOf(item.node.id).length) toggleTopic(item.node.id); else openMapCard(item); }, 'topic-row');
      row.setAttribute('role', 'listitem');
      row.style.setProperty('--c', item.color);
      row.style.setProperty('--share', Math.max(3, item.total / largest * 100) + '%');
      row.classList.toggle('open', item.node.id === openTopic);
      const kids = childrenOf(item.node.id).length;
      row.append(element('i', 'topic-dot'), element('span', 'topic-name', item.node.name),
        element('b', 'topic-count', item.node.chat ? item.total + ' ✉' : item.total));
      row.title = item.node.name + (kids ? ' · ' + kids + ' ' + plural(kids, 'подветка', 'подветки', 'подветок') : '');
      row.addEventListener('mouseenter', () => highlightChain(item, true));
      row.addEventListener('mouseleave', () => highlightChain(item, false));
      row.addEventListener('focus', () => highlightChain(item, true));
      row.addEventListener('blur', () => highlightChain(item, false));
      box.append(row);
    }
  }
  // Импульс вопроса: искра бежит от ядра по цепочке веток, ветки вспыхивают и просыпаются.
  function flash(group) {
    if (!group.isConnected) return;
    group.classList.remove('firing', 'resting', 'dormant');
    void group.getBoundingClientRect();
    group.classList.add('firing');
    setTimeout(() => group.classList.remove('firing'), 1400);
  }
  function firePulse(ids) {
    const svgRoot = $('brain-map').querySelector('svg');
    if (!svgRoot) return;
    const layer = svgRoot.querySelector('.map-impulses'), core = svgRoot.querySelector('.map-core');
    flash(core);
    const step = calm() ? 0 : 420, lit = new Set();
    for (const id of ids) {
      const entry = mapNodes.get(id);
      if (!entry) continue;
      const chain = [];
      for (let cur = entry.item; cur; cur = cur.parent) chain.unshift(cur);
      chain.forEach((item, depth) => {
        const target = mapNodes.get(item.node.id);
        if (!calm()) setTimeout(() => {
          if (!layer.isConnected) return;
          const spark = svg('circle', {r: 3.4}, 'map-impulse');
          const motion = svg('animateMotion', {dur: (step / 1000) + 's', begin: 'indefinite', fill: 'freeze'});
          const ref = svg('mpath');
          ref.setAttribute('href', '#' + target.path.id);
          motion.append(ref);
          spark.append(motion);
          layer.append(spark);
          motion.beginElement();
          setTimeout(() => spark.remove(), step + 300);
        }, depth * step);
        if (!lit.has(item.node.id)) {
          lit.add(item.node.id);
          setTimeout(() => { flash(target.group); target.path.classList.remove('resting', 'dormant'); }, (depth + 1) * step);
        }
      });
    }
  }
  async function pollPulses() {
    if ($('brain-view').hidden || document.hidden || pulseSeen === null) return;
    try {
      const data = await request('brain/pulses?since=' + pulseSeen);
      // База могла смениться (восстановление копии): начинаем отсчёт заново.
      pulseSeen = data.last < pulseSeen ? data.last : Math.max(pulseSeen, ...data.pulses.map(p => p.id));
      data.pulses.slice(-5).forEach((pulse, i) => setTimeout(() => firePulse(pulse.branches), i * 1100));
    } catch { /* следующий опрос попробует снова */ }
  }
  setInterval(pollPulses, 4000);
  // Ночью (23:00–7:00) Мозг «спит»: карта темнеет, по ней идут медленные волны.
  function updateSleep() {
    const box = $('brain-map'), hour = new Date().getHours();
    // sleepMode — ручной выбор кнопкой с луной; null — по часам.
    const asleep = sleepMode ?? (hour >= 23 || hour < 7 || idleState === 'working' || idleState === 'resting');
    box.classList.toggle('sleeping', asleep);
    let badge = box.querySelector('.brain-map-sleep');
    if (asleep && !badge) {
      badge = element('p', 'brain-map-sleep');
      box.append(badge);
    }
    if (badge) badge.textContent = idleState === 'working' && idleTask ? 'Мозг спит и работает: ' + idleTask.toLowerCase() : 'Мозг спит и перебирает знания';
    if (!asleep) badge?.remove();
    const toggle = $('brain-map-sleep');
    toggle.setAttribute('aria-pressed', String(asleep));
  }
  setInterval(updateSleep, 60000);

  // Самостоятельный рост: настройки, состояние, вопросы к пользователю и журнал.
  let idleState = null, idleTask = '', idleData = null, idleSaving = false;
  const IDLE_TASKS = {exam: 'Самоэкзамен', gaps: 'Поиск пробелов', tidy: 'Порядок в темах', documents: 'Разбор документа моделью'};
  async function loadIdle() {
    try {
      const data = await request('brain/idle?' + new URLSearchParams({offset: -new Date().getTimezoneOffset()}));
      if (!idleSaving) renderIdle(data);  // Не перебиваем ещё не сохранённый выбор.
    }
    catch (error) { $('brain-idle-state').textContent = error.message; }
  }
  const IDLE_HEAD = {off: 'Выключен', waiting: 'Ждёт тишины', working: 'Работает', resting: 'Отдыхает'};
  const IDLE_ICONS = {exam: 'check', gaps: 'search', tidy: 'brain', documents: 'file'};
  function idleLine(data) {
    const s = data.settings;
    if (data.state === 'off') return 'Включите, и Мозг будет сам себя экзаменовать, искать пробелы и наводить порядок, пока вас нет.';
    if (data.state === 'working') return 'Сейчас: ' + (IDLE_TASKS[data.task] || 'задача').toLowerCase() + '…';
    if (data.state === 'resting') return 'Текущие задачи сделаны. Скоро проверит снова.';
    const left = Math.max(1, Math.ceil((s.idle_minutes * 60 - data.idle_seconds) / 60));
    return 'Начнёт через ' + left + ' мин после вашего последнего действия.';
  }
  // Вкладки внутри «Сам растёт»: вопросы, отчёт, выводы и настройки — по одному разделу за раз.
  const idleTabs = [...document.querySelectorAll('[data-idle-tab]')];
  function selectIdleTab(name, focus) {
    for (const tab of idleTabs) {
      const on = tab.dataset.idleTab === name;
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
      $('idle-pane-' + tab.dataset.idleTab).hidden = !on;
      if (on && focus) tab.focus();
    }
  }
  idleTabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectIdleTab(tab.dataset.idleTab));
    tab.addEventListener('keydown', event => {
      const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
      if (!step) return;
      event.preventDefault();
      selectIdleTab(idleTabs[(index + step + idleTabs.length) % idleTabs.length].dataset.idleTab, true);
    });
  });
  function idleCount(id, count) {
    const badge = $(id);
    badge.textContent = count || '';
    badge.hidden = !count;
  }
  function renderIdleStats(data) {
    const box = $('brain-idle-stats');
    box.replaceChildren();
    const done = data.done_today ?? 0;
    const tile = (value, label, iconName) => {
      const cell = element('div', 'idle-stat');
      const mark = element('span', 'idle-stat-icon');
      mark.append(svgIcon(iconName));
      const body = element('div');
      body.append(element('strong', '', value), element('span', '', label));
      cell.append(mark, body);
      box.append(cell);
    };
    tile(data.questions.length, plural(data.questions.length, 'вопрос к вам', 'вопроса к вам', 'вопросов к вам'), 'chat');
    tile(done, plural(done, 'задача сегодня', 'задачи сегодня', 'задач сегодня'), 'check');
    tile(data.settings.cloud ? data.cloud_used_today + ' / ' + data.settings.cloud_daily : 'нет', data.settings.cloud ? 'запросов к модели' : 'модель не нужна', 'file');
  }
  function renderIdleLog(log) {
    const box = $('brain-idle-log');
    box.replaceChildren();
    if (!log.length) { box.append(emptyState('Здесь появится отчёт: что Мозг сделал, пока вас не было.', 'moon')); return; }
    let currentDay = null, list;
    log.forEach((item, index) => {
      const label = dayLabel(item.time);
      if (label !== currentDay) {
        currentDay = label;
        box.append(element('h3', 'brain-day', label));
        list = element('ol', 'idle-log-day');
        box.append(list);
      }
      const row = element('li', 'idle-log-item kind-' + item.task);
      row.style.setProperty('--i', index);
      const mark = element('span', 'idle-log-icon');
      mark.append(svgIcon(IDLE_ICONS[item.task] || 'spark'));
      const body = element('div', 'idle-log-body');
      const head = element('div', 'idle-log-head');
      head.append(element('strong', '', item.task_name));
      if (item.cloud) head.append(element('span', 'brain-idle-cloud', 'Cloud.ru'));
      head.append(element('time', '', clock(item.time)));
      body.append(head, element('p', '', item.summary));
      row.append(mark, body);
      list.append(row);
    });
  }
  function renderIdle(data) {
    idleData = data;
    const previous = idleState;
    idleState = data.state; idleTask = IDLE_TASKS[data.task] || '';
    if (previous !== idleState) updateSleep();
    const s = data.settings;
    $('brain-idle-title').textContent = IDLE_HEAD[data.state] || 'Сам растёт';
    $('brain-idle-state').textContent = idleLine(data);
    $('brain-idle-state').dataset.state = data.state;
    $('brain-idle-orb').dataset.state = data.state;
    $('brain-idle-enabled').checked = s.enabled;
    $('brain-idle-cloud').checked = s.cloud;
    $('brain-idle-minutes').value = String(s.idle_minutes);
    $('brain-idle-daily').value = String(s.cloud_daily);
    $('brain-idle-run').disabled = !s.enabled || data.state === 'working';
    for (const id of ['brain-idle-minutes', 'brain-idle-cloud']) $(id).disabled = !s.enabled;
    $('brain-idle-daily').disabled = !s.enabled || !s.cloud;
    $('brain-idle-note').textContent = !s.cloud ? 'Без модели Мозг сам себя экзаменует, ищет пробелы и наводит порядок в темах. Всё на компьютере, бесплатно.' :
      !data.model_connected ? 'Чтобы разбирать документы, подключите модель: правый щелчок по аватару → Cloud.ru и модели.' :
      'Сегодня запросов к модели: ' + data.cloud_used_today + ' из ' + s.cloud_daily + '. Тексты документов уходят в Cloud.ru только в этих пределах.';
    renderIdleStats(data);
    idleCount('idle-count-questions', data.questions.length);
    idleCount('idle-count-log', data.log.length);
    idleCount('idle-count-insights', data.insights.length);
    // Тот же набор вопросов не перерисовываем: иначе опрос стирал бы недописанный ответ.
    // Новая формулировка тех же вопросов ждёт, пока вы дописываете ответ.
    updateBadges();
    const overviewKey = data.questions.length + '|' + (data.questions[0]?.text || '');
    if (overviewKey !== renderIdle.overviewKey) { renderIdle.overviewKey = overviewKey; renderOverview(); }
    const questions = $('brain-idle-questions'), ids = data.questions.map(q => q.id).join(',');
    const key = ids + '|' + data.questions.map(q => q.text + JSON.stringify(q.details || {})).join('|');
    const drafting = [...questions.querySelectorAll('textarea')].some(area => area.value.trim());
    if ((questions.dataset.key !== key && !(drafting && questions.dataset.ids === ids)) || !questions.childElementCount) {
      questions.dataset.key = key;
      questions.dataset.ids = ids;
      questions.replaceChildren();
      if (!data.questions.length) questions.append(emptyState('Вопросов пока нет. Они появятся, когда Мозг найдёт пробел или противоречие.', 'chat'));
      for (const q of data.questions) questions.append(idleQuestion(q));
    }
    renderIdleLog(data.log);
    const insights = $('brain-idle-insights');
    insights.replaceChildren();
    if (!data.insights.length) {
      insights.append(emptyState(s.cloud ? 'Модель ещё не разобрала ни одного документа.' : 'Выводы появятся, если в настройках включить разбор документов моделью.', 'file'));
      return;
    }
    insights.append(element('p', 'module-muted idle-pane-note', 'Это толкования модели, а не проверенные факты. Цитата сверена с документом.'));
    for (const item of data.insights.slice(0, 12)) {
      const card = element('div', 'brain-idle-insight');
      card.append(element('p', '', item.text), element('blockquote', '', item.quote),
        element('span', 'module-muted', item.file + (item.locator ? ' · ' + item.locator : '')));
      insights.append(card);
    }
  }
  async function idleAnswer(q, action, text) {
    try {
      const result = await request('brain/idle/question', {id: q.id, action, ...(text ? {text} : {})});
      message(action === 'merge' ? 'Темы объединены в «' + result.merged_into + '».' : action === 'answer' ? 'Спасибо, Мозг запомнил ответ.' : 'Вопрос скрыт.');
      if (action === 'dismiss') await loadIdle(); else await loadBrain();
    } catch (error) { message(error.message); }
  }
  const QUESTION_KINDS = {weak_recall: 'Слабое место', single_source: 'Один источник', conflict: 'Противоречие', merge: 'Порядок в темах'};
  // Вопрос Мозга: о чём он, конкретная цитата, зачем спрашивает и как ответить.
  function idleQuestion(q) {
    const d = q.details || {};
    const card = element('div', 'brain-idle-question kind-' + q.kind);
    const head = element('div', 'idle-q-head');
    head.append(element('span', 'idle-q-kind', QUESTION_KINDS[q.kind] || 'Вопрос'));
    if (q.topic && q.kind !== 'conflict') head.append(element('span', 'idle-q-topic', q.topic));
    card.append(head, element('p', 'idle-q-text', q.text));
    if (d.quote) {
      const quote = element('blockquote', 'idle-q-quote', d.quote);
      if (d.source) quote.append(element('cite', '', d.source));
      card.append(quote);
    }
    let reply = null;
    const openReply = prefill => {
      if (!reply) {
        actions.hidden = true;
        reply = element('form', 'brain-idle-reply');
        const area = element('textarea');
        area.rows = 3; area.maxLength = 4000; area.minLength = 70;
        area.setAttribute('aria-label', 'Ваш ответ');
        area.placeholder = (d.example || 'Напишите своими словами, хотя бы пару предложений.') + ' Мозг запомнит ответ как сообщение из чата.';
        const counter = element('small', 'idle-q-counter');
        const update = () => { const left = 70 - area.value.trim().length; counter.textContent = left > 0 ? 'Ещё хотя бы ' + left + ' ' + plural(left, 'символ', 'символа', 'символов') : 'Можно запоминать'; counter.classList.toggle('ok', left <= 0); };
        area.addEventListener('input', update);
        const send = element('button', 'primary-button', 'Запомнить');
        send.type = 'submit';
        const cancel = button('Отмена', () => { reply.remove(); reply = null; actions.hidden = false; }, 'secondary-button');
        const row = element('div', 'idle-q-send');
        row.append(send, cancel, counter);
        reply.append(area, row);
        reply.addEventListener('submit', event => { event.preventDefault(); idleAnswer(q, 'answer', area.value.trim()); });
        card.append(reply);
        update();
      }
      const area = reply.querySelector('textarea');
      if (prefill) { area.value = prefill; area.dispatchEvent(new Event('input')); }
      area.focus();
    };
    if (d.options?.length) {
      const options = element('div', 'idle-q-options');
      d.options.forEach((option, index) => {
        const pick = button('', () => openReply('Правильно так: «' + option.text + '». Источник: ' + option.source + '.'), 'idle-q-option');
        pick.append(element('span', 'idle-q-option-mark', index ? 'Б' : 'А'), element('span', 'idle-q-option-text', option.text), element('cite', '', option.source));
        pick.title = 'Выбрать этот вариант';
        options.append(pick);
      });
      card.append(options);
    }
    if (d.why) card.append(element('p', 'idle-q-why', d.why));
    const actions = element('div', 'brain-idle-actions');
    if (q.kind === 'merge') {
      actions.append(button('Объединить', () => idleAnswer(q, 'merge'), 'primary-button'),
        button('Не надо', () => idleAnswer(q, 'dismiss'), 'secondary-button'));
    } else {
      actions.append(button(d.options ? 'Написать свой ответ' : 'Ответить', () => openReply(), 'primary-button'),
        button('Скрыть', () => idleAnswer(q, 'dismiss'), 'secondary-button'));
    }
    card.append(actions);
    return card;
  }
  // Изменения во время сохранения не теряются: копятся и уходят следующим запросом.
  let idlePending = null;
  async function saveIdle(change) {
    idlePending = {...idlePending, ...change};
    if (idleSaving) return;
    idleSaving = true;
    try {
      while (idlePending) {
        const next = idlePending;
        idlePending = null;
        try { idleData = await request('brain/idle/settings', next); }
        catch (error) { message(error.message); }
      }
    } finally {
      idleSaving = false;
      if (idleData) renderIdle(idleData);
    }
  }
  $('brain-idle-enabled').addEventListener('change', event => saveIdle({enabled: event.target.checked}));
  $('brain-idle-minutes').addEventListener('change', event => saveIdle({idle_minutes: Number(event.target.value)}));
  $('brain-idle-daily').addEventListener('change', event => saveIdle({cloud_daily: Number(event.target.value)}));
  $('brain-idle-cloud').addEventListener('change', event => {
    if (event.target.checked && !confirm('В режиме ожидания Мозг будет отправлять тексты документов с Диска в Cloud.ru, чтобы модель разобрала их. ' +
      'Это может стоить денег по тарифу Cloud.ru. Число запросов ограничено дневным лимитом. Включить?')) { event.target.checked = false; return; }
    saveIdle({cloud: event.target.checked});
  });
  $('brain-idle-run').addEventListener('click', async () => {
    try { await request('brain/idle/run', {}); message('Мозг начал работу.'); setTimeout(loadIdle, 1500); }
    catch (error) { message(error.message); }
  });
  setInterval(() => { if (!$('brain-view').hidden && !document.hidden) loadIdle(); }, 15000);
  // Повтор роста: ветки появляются в порядке, в котором их узнал Мозг.
  // «Показать рост»: ветки вырастают по очереди, в том порядке, в каком Мозг их узнал.
  function playGrowth() {
    const svgRoot = $('brain-map').querySelector('svg');
    if (!svgRoot || !mapNodes.size) return;
    const run = ++growthRun, counter = svgRoot.querySelector('.map-core-count');
    const box = $('brain-map');
    box.querySelector('.brain-map-story')?.remove();
    if (calm()) { counter.textContent = mapTotal; return; }
    const order = [...mapNodes.values()].sort((a, b) => a.item.order - b.item.order);
    const step = Math.max(160, Math.min(650, 6500 / order.length));
    const story = element('p', 'brain-map-story');
    story.setAttribute('aria-live', 'polite');
    box.append(story);
    order.forEach(entry => { entry.group.classList.remove('shown'); entry.path.classList.remove('shown'); });
    svgRoot.classList.add('replaying');
    counter.textContent = 0;
    $('brain-map-replay').disabled = true;
    let count = 0;
    order.forEach((entry, index) => setTimeout(() => {
      if (run !== growthRun) return;
      entry.path.classList.add('shown');
      entry.group.classList.add('shown');
      count += entry.item.node.chat ? 0 : entry.item.node.facts;
      counter.textContent = count;
      const when = entry.item.node.created ? shortDate(entry.item.node.created) + ' · ' : '';
      story.replaceChildren(element('span', 'brain-map-story-date', when), document.createTextNode(
        (entry.item.depth === 1 ? 'новая тема «' : 'выросла ветка «') + entry.item.node.name + '»'));
      story.style.setProperty('--c', entry.item.color);
    }, 300 + index * step));
    setTimeout(() => {
      if (run !== growthRun) return;
      svgRoot.classList.remove('replaying');
      counter.textContent = mapTotal;
      story.replaceChildren(document.createTextNode('Сегодня: ' + knowledgeCount(mapTotal) + ' в ' + order.length + ' ' + plural(order.length, 'ветке', 'ветках', 'ветках')));
      $('brain-map-replay').disabled = false;
      setTimeout(() => { if (run === growthRun) story.classList.add('done'); }, 2500);
    }, 300 + order.length * step + 700);
  }
  function closeMapCard() {
    document.querySelectorAll('.map-card,.brain-drawer-backdrop').forEach(node => node.remove());
    $('brain-map')?.querySelectorAll('.map-node.open').forEach(node => node.classList.remove('open'));
    document.body.classList.remove('drawer-open');
    openNodeId = null;
  }
  function shortDate(value) {
    const moment = new Date(value);
    return Number.isNaN(moment.getTime()) ? '' : moment.toLocaleDateString('ru-RU', {day: 'numeric', month: 'short'});
  }
  // Панель ветки: статистика, откуда знания, связи и сами знания с поиском.
  async function openMapCard(item) {
    if (item.node.chat) { openChatCard(item); return; }
    const returnFocus = mapNodes.get(item.node.id)?.group;
    closeMapCard();
    openNodeId = item.node.id;
    mapNodes.get(item.node.id)?.group.classList.add('open');
    const backdrop = element('div', 'brain-drawer-backdrop');
    const card = element('aside', 'map-card brain-drawer');
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', item.node.name);
    const head = element('div', 'drawer-head');
    const titles = element('div');
    const chain = ancestors(item.node);
    if (chain.length) titles.append(element('small', 'map-card-path', chain.map(node => node.name).join(' › ')));
    titles.append(element('h3', '', item.node.name));
    const topic = growthTopics.find(row => row.id === item.node.id);
    if (topic) {
      const badge = element('p', 'drawer-level');
      badge.append(element('span', 'level-badge', topic.level_name), document.createTextNode(levelHint(topic)));
      titles.append(badge);
    }
    const close = button('', () => { closeMapCard(); returnFocus?.focus(); }, 'icon-button');
    close.setAttribute('aria-label', 'Закрыть');
    close.append(svgIcon('close'));
    head.append(titles, close);
    const scroll = element('div', 'drawer-scroll');
    const fresh = mapFresh[item.node.id] || 0;
    const tiles = element('div', 'drawer-tiles');
    const tile = (value, label) => { const cell = element('div', 'drawer-tile'); cell.append(element('strong', '', value), element('span', '', label)); tiles.append(cell); return cell; };
    tile(item.total, plural(item.total, 'знание', 'знания', 'знаний'));
    const docsTile = tile('…', 'документов'), chatTile = tile('…', 'из чата');
    tile(fresh ? '+' + fresh : '0', 'за неделю');
    const pulse = element('div', 'drawer-pulse');
    scroll.append(tiles, pulse);
    if (item.idleDays > 14 && !fresh) scroll.append(element('p', 'map-card-rest',
      'Не пополнялась и не была нужна ' + item.idleDays + ' ' + plural(item.idleDays, 'день', 'дня', 'дней') + '. Спросите о ней в чате, и ветка снова загорится.'));
    const sources = element('section', 'drawer-section');
    sources.append(element('h4', '', 'Откуда знания'), element('div', 'brain-skeleton'));
    scroll.append(sources);
    const linked = mapSynapses.filter(link => link.a === item.node.id || link.b === item.node.id)
      .map(link => mapNodes.get(link.a === item.node.id ? link.b : link.a)?.item).filter(Boolean);
    const chipsSection = (title, items) => {
      if (!items.length) return;
      const section = element('section', 'drawer-section');
      const row = element('div', 'brain-subbranches');
      items.slice(0, 10).forEach(other => row.append(button(other.node.name, () => openMapCard(other), 'brain-chip')));
      section.append(element('h4', '', title), row);
      scroll.append(section);
    };
    chipsSection('Подветки', item.children);
    chipsSection('Связана с темами', linked);
    const knowledge = element('section', 'drawer-section');
    const knowledgeHead = element('div', 'drawer-section-head');
    const filterInput = element('input', 'drawer-filter');
    filterInput.type = 'search';
    filterInput.placeholder = 'Найти в ветке';
    filterInput.setAttribute('aria-label', 'Найти в знаниях ветки');
    knowledgeHead.append(element('h4', '', 'Знания'), filterInput);
    const list = element('div', 'map-card-list');
    list.append(element('div', 'brain-skeleton tall'));
    knowledge.append(knowledgeHead, list);
    scroll.append(knowledge);
    card.append(head, scroll);
    document.body.append(backdrop, card);
    document.body.classList.add('drawer-open');
    backdrop.addEventListener('click', closeMapCard);
    card.addEventListener('keydown', event => { if (event.key === 'Escape') { closeMapCard(); returnFocus?.focus(); } });
    close.focus({preventScroll: true});
    const ticket = ++factsRequest;
    try {
      const data = await request('brain/facts?branch=' + encodeURIComponent(item.node.id));
      if (ticket !== factsRequest || openNodeId !== item.node.id) return;
      const stats = data.stats || {total: 0, chat: 0, documents: 0, sources: [], spark: []};
      docsTile.querySelector('strong').textContent = stats.documents;
      docsTile.querySelector('span').textContent = plural(stats.documents, 'документ', 'документа', 'документов');
      chatTile.querySelector('strong').textContent = stats.chat;
      if (stats.spark?.length) {
        pulse.append(sparkline(stats.spark, 'drawer-spark'));
        const note = element('p', '', 'Рост за 14 дней' + (stats.first ? ' · первое знание ' + shortDate(stats.first) : '') +
          (stats.last ? ' · последнее ' + shortDate(stats.last) : ''));
        pulse.append(note);
      }
      let filter = null, filterTicket = 0, filterTimer;
      const paintList = (shown, empty) => {
        list.replaceChildren();
        if (!shown.length) { list.append(element('p', 'module-muted', empty)); return; }
        let limit = 6;
        const more = button('', () => { limit += 12; paint(); }, 'secondary-button map-card-more');
        const paint = () => {
          list.replaceChildren(...shown.slice(0, limit).map(fact => knowledgeCard(fact)));
          if (shown.length > limit) { more.textContent = 'Показать ещё (' + (shown.length - limit) + ')'; list.append(more); }
        };
        paint();
      };
      // Фильтр по источнику и поиск идут на сервер: по всем записям ветки с подветками, а не по первым 100.
      const draw = () => {
        const query = filterInput.value.trim();
        const ticket = ++filterTicket;
        clearTimeout(filterTimer);
        // У темы без своих записей сразу показываем знания её подветок.
        const subtree = !filter && !query && !data.facts.length && item.children.length;
        if (!filter && !query && !subtree) {
          paintList(data.facts, 'В этой ветке пока нет записей.');
          return;
        }
        filterTimer = setTimeout(async () => {
          try {
            const params = new URLSearchParams({branch: item.node.id});
            if (filter) params.set('source', filter.type === 'chat' ? 'chat' : 'file:' + filter.id);
            if (query) params.set('q', query);
            if (subtree) params.set('subtree', '1');
            const found = await request('brain/facts?' + params);
            if (ticket !== filterTicket || openNodeId !== item.node.id) return;
            paintList(found.facts, 'Ничего не найдено.');
          } catch (error) { if (ticket === filterTicket) list.replaceChildren(emptyState(error.message)); }
        }, query ? 250 : 0);
      };
      filterInput.addEventListener('input', draw);
      // Источники: полоски по числу знаний, по нажатию фильтруют список.
      sources.replaceChildren(element('h4', '', 'Откуда знания' + (item.children.length ? ' (вместе с подветками)' : '')));
      const rows = stats.sources.map(source => ({...source, icon: 'file'}));
      if (stats.chat) rows.push({type: 'chat', id: null, name: 'Разговоры в чате', count: stats.chat, icon: 'chat'});
      rows.sort((a, b) => b.count - a.count);
      const largest = Math.max(...rows.map(row => row.count), 1);
      if (!rows.length) sources.append(element('p', 'module-muted', 'Источников пока нет.'));
      const bars = element('div', 'source-bars');
      rows.forEach((row, index) => {
        const line = button('', () => {
          const same = filter && filter.type === row.type && filter.id === row.id;
          filter = same ? null : {type: row.type, id: row.id};
          bars.querySelectorAll('.source-bar').forEach(node => node.classList.toggle('active', !same && node === line));
          bars.querySelectorAll('.source-bar').forEach(node => node.setAttribute('aria-pressed', String(!same && node === line)));
          draw();
        }, 'source-bar');
        line.setAttribute('aria-pressed', 'false');
        line.title = filter ? '' : 'Показать знания только из этого источника';
        line.style.setProperty('--share', Math.max(4, row.count / largest * 100) + '%');
        line.style.setProperty('--i', index);
        const icon = element('span', 'source-bar-icon');
        icon.append(svgIcon(row.icon));
        line.append(icon, element('span', 'source-bar-name', row.name), element('span', 'source-bar-count', row.count));
        bars.append(line);
      });
      if (rows.length) sources.append(bars);
      if (stats.documents > stats.sources.length) sources.append(element('p', 'module-muted drawer-small', 'И ещё ' + (stats.documents - stats.sources.length) + ' ' + plural(stats.documents - stats.sources.length, 'документ', 'документа', 'документов') + ' с меньшим вкладом.'));
      draw();
    } catch (error) {
      if (ticket === factsRequest) list.replaceChildren(emptyState(error.message));
    }
  }
  // Панель ветки из чата: сколько раз и когда говорили на тему, последние реплики.
  function openChatCard(item) {
    const returnFocus = mapNodes.get(item.node.id)?.group;
    closeMapCard();
    openNodeId = item.node.id;
    mapNodes.get(item.node.id)?.group.classList.add('open');
    const backdrop = element('div', 'brain-drawer-backdrop');
    const card = element('aside', 'map-card brain-drawer is-chat');
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', item.node.name);
    const head = element('div', 'drawer-head');
    const titles = element('div');
    if (item.parent) titles.append(element('small', 'map-card-path', 'Разговоры'));
    titles.append(element('h3', '', item.node.name));
    const close = button('', () => { closeMapCard(); returnFocus?.focus(); }, 'icon-button');
    close.setAttribute('aria-label', 'Закрыть');
    close.append(svgIcon('close'));
    head.append(titles, close);
    const scroll = element('div', 'drawer-scroll');
    const topics = item.parent ? [item.node.topic] : brainData.chat.topics;
    const spark = item.parent ? item.node.topic.spark : brainData.chat.spark;
    const tiles = element('div', 'drawer-tiles');
    const tile = (value, label) => { const cell = element('div', 'drawer-tile'); cell.append(element('strong', '', value), element('span', '', label)); tiles.append(cell); };
    tile(item.total, plural(item.total, 'сообщение', 'сообщения', 'сообщений'));
    tile(item.node.week ? '+' + item.node.week : '0', 'за неделю');
    if (!item.parent) tile(item.children.length, plural(item.children.length, 'тема', 'темы', 'тем'));
    tile(shortDate(item.node.created), 'впервые');
    scroll.append(tiles);
    if (spark.some(Boolean)) {
      const pulse = element('div', 'drawer-pulse');
      pulse.append(sparkline(spark, 'drawer-spark'), element('p', '', 'Разговоры за 14 дней · последний ' + shortDate(item.node.last)));
      scroll.append(pulse);
    }
    scroll.append(element('p', 'map-card-rest chat-note', 'Это темы ваших разговоров с Tenmiyora. Знанием Мозга сообщение становится, когда в нём есть содержательное утверждение, а не вопрос или просьба.'));
    if (!item.parent) {
      const section = element('section', 'drawer-section');
      const row = element('div', 'brain-subbranches');
      item.children.slice(0, 12).forEach(other => row.append(button(other.node.name + ' · ' + other.total, () => openMapCard(other), 'brain-chip')));
      section.append(element('h4', '', 'Темы'), row);
      scroll.append(section);
    }
    const samples = topics.flatMap(topic => topic.samples).sort((a, b) => String(b.time).localeCompare(String(a.time))).slice(0, 8);
    const section = element('section', 'drawer-section');
    section.append(element('h4', '', 'Последние реплики'));
    for (const sample of samples) {
      const quote = element('blockquote', 'chat-sample');
      quote.append(element('p', '', sample.text), element('time', '', dayLabel(sample.time) + ', ' + clock(sample.time)));
      section.append(quote);
    }
    if (!samples.length) section.append(element('p', 'module-muted', 'Реплик нет.'));
    scroll.append(section);
    card.append(head, scroll);
    document.body.append(backdrop, card);
    document.body.classList.add('drawer-open');
    backdrop.addEventListener('click', closeMapCard);
    card.addEventListener('keydown', event => { if (event.key === 'Escape') { closeMapCard(); returnFocus?.focus(); } });
    close.focus({preventScroll: true});
  }
  function openBranch(id) {
    let item = mapNodes.get(id)?.item || mapAll.get(id);
    if (!item) { message('Ветка не найдена. Нажмите «Обновить».'); return; }
    // Ветка под свёрнутой темой: раскрываем её тему, чтобы ветку было видно и на карте.
    if (!mapNodes.has(id)) {
      let top = item;
      while (top.parent) top = top.parent;
      if (top.node.id !== openTopic) {
        toggleTopic(top.node.id);
        item = mapNodes.get(id)?.item || mapAll.get(id) || item;
      }
    }
    openMapCard(item);
  }
  // Панель ветки закрывается крестиком, Escape или нажатием на затемнённый фон: фон перекрывает всю страницу,
  // поэтому отдельный обработчик «клика снаружи» не нужен и не закрывает панель, открытую с меток или уровней.
  $('brain-topics-filter').addEventListener('input', paintTopics);
  $('brain-map-replay').addEventListener('click', playGrowth);
  $('brain-map-sleep').addEventListener('click', () => { sleepMode = !$('brain-map').classList.contains('sleeping'); updateSleep(); });
  let mapResize;
  addEventListener('resize', () => {
    clearTimeout(mapResize);
    mapResize = setTimeout(() => {
      const box = $('brain-map');
      if (!$('brain-view').hidden && box.clientWidth && (box.clientWidth < 640) !== Boolean(MAP.narrow)) renderMap();
      const charts = $('brain-charts');
      if (charts?.clientWidth && (charts.clientWidth < 560) !== chartNarrow) renderCharts();
    }, 200);
  });

  // ---- Вкладки Мозга и «Главное» ----
  const BRAIN_TAB_KEY = 'tenmiyora.brain.tab';
  const brainTabs = [...document.querySelectorAll('[data-brain-tab]')];
  let growthBrain = null;
  function selectTab(name, focus) {
    if (!brainTabs.some(tab => tab.dataset.brainTab === name)) name = 'overview';
    for (const tab of brainTabs) {
      const on = tab.dataset.brainTab === name;
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
      $('brain-pane-' + tab.dataset.brainTab).hidden = !on;
      if (on && focus) tab.focus();
    }
    try { localStorage.setItem(BRAIN_TAB_KEY, name); } catch { /* вкладка просто не запомнится */ }
  }
  function goTab(name) {
    selectTab(name);
    const bar = document.querySelector('.brain-tabs');
    if (bar && bar.getBoundingClientRect().top < 0) bar.scrollIntoView({block: 'start'});
  }
  brainTabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectTab(tab.dataset.brainTab));
    tab.addEventListener('keydown', event => {
      const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
      if (event.key === 'Home' || event.key === 'End') {
        event.preventDefault();
        selectTab(brainTabs[event.key === 'Home' ? 0 : brainTabs.length - 1].dataset.brainTab, true);
      } else if (step) {
        event.preventDefault();
        selectTab(brainTabs[(index + step + brainTabs.length) % brainTabs.length].dataset.brainTab, true);
      }
    });
  });
  selectTab((() => { try { return localStorage.getItem(BRAIN_TAB_KEY); } catch { return null; } })() || 'overview');

  // «Главное»: вопросы к вам, уровень Мозга и что он узнал последним.
  function overviewCard(title, iconName, tab, className) {
    const card = element('section', 'overview-card ' + (className || ''));
    const head = element('div', 'overview-head');
    const name = element('h2');
    name.append(svgIcon(iconName), document.createTextNode(title));
    head.append(name);
    if (tab) {
      const more = button('', () => goTab(tab), 'overview-more');
      more.append(document.createTextNode('Открыть'), svgIcon('arrow'));
      more.setAttribute('aria-label', 'Открыть вкладку «' + title + '»');
      head.append(more);
    }
    card.append(head);
    return card;
  }
  function renderOverview() {
    const box = $('brain-overview');
    if (!box) return;
    box.replaceChildren();
    const ask = overviewCard('Вопросы к вам', 'chat', 'idle', 'is-questions');
    const questions = idleData?.questions || [];
    ask.append(element('strong', 'overview-big', questions.length || '0'));
    ask.append(element('p', 'overview-note', questions.length ? '«' + questions[0].text.slice(0, 140) + (questions[0].text.length > 140 ? '…' : '') + '»' :
      'Мозг спросит, когда найдёт пробел или противоречие.'));
    const level = overviewCard('Мозг сейчас', 'spark', 'growth', 'is-level');
    if (growthBrain) {
      const row = element('div', 'overview-level');
      row.append(progressRing(76, 6, growthBrain.progress, growthBrain.level, '', 'ring-mini'));
      const text = element('div');
      text.append(element('strong', '', growthBrain.name), element('span', '', knowledgeCount(growthBrain.total) + ' · +' + growthBrain.week + ' за неделю'));
      row.append(text);
      level.append(row);
    }
    const recent = overviewCard('Последнее, что узнал', 'file', 'growth', 'is-recent');
    const events = mergedEvents(brainData.recent).slice(0, 3);
    if (!events.length) recent.append(element('p', 'overview-note', 'Пока ничего. Загрузите документ на Диск.'));
    for (const event of events) {
      const row = element('p', 'overview-event');
      row.append(element('span', '', /^Сообщение/.test(event.name) ? 'Разговор в чате' : event.name), element('time', '', dayLabel(event.time).toLowerCase() + ' ' + clock(event.time)));
      recent.append(row);
    }
    box.append(ask, level, recent);
  }
  function updateBadges() {
    const badge = $('brain-badge-idle'), count = idleData?.questions?.length || 0;
    badge.hidden = !count;
    badge.textContent = count || '';
  }
  function renderStageLine() {
    if (!growthBrain) return;
    const parts = ['Уровень ' + growthBrain.level + ' · ' + growthBrain.name, knowledgeCount(growthBrain.total)];
    if (growthBrain.week) parts.push('+' + growthBrain.week + ' за неделю');
    $('brain-stage-line').textContent = parts.join(' · ');
  }

  $('brain-refresh').addEventListener('click', loadBrain);
  window.TenmiyoraModules = {
    show(view) {
      if (view === 'brain') loadBrain();
      if (view === 'disk') refreshDisk();
    }
  };
  const initial = location.hash.replace('#', '');
  if (initial === 'brain' || initial === 'disk') window.TenmiyoraModules.show(initial);
})();