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
  async function moveItems(items, target) {
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
  let brainData = {branches: [], recent: []};
  let brainLoading = false, factsRequest = 0, searchRequest = 0;
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

  function renderEvents() {
    const events = $('brain-events');
    events.replaceChildren();
    if (!brainData.recent.length) {
      events.append(emptyState('Рост памяти пока не начался.', 'spark'));
      return;
    }
    let currentDay = null, group;
    for (const event of brainData.recent) {
      const label = dayLabel(event.time);
      if (label !== currentDay) {
        currentDay = label;
        events.append(element('h3', 'brain-day', label));
        group = element('ol', 'brain-day-events');
        events.append(group);
      }
      const row = element('li', 'brain-event');
      const body = element('div', 'brain-event-body');
      body.append(element('strong', '', event.action), element('span', '', event.detail));
      row.append(body, element('time', '', clock(event.time)));
      group.append(row);
    }
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

  // Рост Мозга: график по дням, дневник недели и уровни тем.
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
  function renderGrowthChart(series) {
    const box = $('brain-growth-chart');
    box.replaceChildren();
    const added = series.reduce((sum, day) => sum + day.added, 0);
    const total = series.length ? series[series.length - 1].total : 0;
    $('brain-growth-summary').textContent = added ?
      'Всего ' + knowledgeCount(total) + ', за 30 дней +' + added + '. Столбец показывает новые знания за день.' :
      'За 30 дней новых знаний не появилось. Загрузите документ на Диск или расскажите что-нибудь в чате.';
    const top = niceMax(Math.max(...series.map(day => day.added), 1));
    const plot = element('div', 'growth-plot');
    const grid = element('div', 'growth-grid');
    for (const value of [top, top / 2, 0]) {
      const line = element('div', 'growth-gridline');
      line.append(element('span', '', Number.isInteger(value) ? value : value.toFixed(1)));
      grid.append(line);
    }
    const bars = element('div', 'growth-bars');
    bars.setAttribute('role', 'img');
    bars.setAttribute('aria-label', 'Новые знания по дням за 30 дней: всего ' + added);
    const tip = element('div', 'growth-tip');
    tip.hidden = true;
    const today = series.length ? series[series.length - 1].date : '';
    series.forEach((day, index) => {
      const col = element('div', 'growth-col' + (day.date === today ? ' today' : ''));
      col.tabIndex = 0;
      const bar = element('span', 'growth-bar' + (day.added ? '' : ' empty'));
      bar.style.setProperty('--i', index);
      bar.style.height = (day.added ? Math.max(2, day.added / top * 100) : 0) + '%';
      col.append(bar);
      const show = () => {
        tip.replaceChildren(element('strong', '', shortDay(day.date, true)),
          element('span', '', '+' + day.added + ' · всего ' + day.total),
          ...(day.quality != null ? [element('span', '', 'экзамен ' + (day.quality * 100).toFixed(1) + '%')] : []));
        tip.hidden = false;
        const left = (index + .5) / series.length * 100;
        tip.style.left = Math.min(88, Math.max(12, left)) + '%';
      };
      col.addEventListener('mouseenter', show);
      col.addEventListener('focus', show);
      col.addEventListener('mouseleave', () => { tip.hidden = true; });
      col.addEventListener('blur', () => { tip.hidden = true; });
      bars.append(col);
    });
    plot.append(grid, bars, tip);
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
  function diaryLine(iconName, strong, rest) {
    const line = element('li', 'diary-line');
    const mark = element('span', 'diary-icon');
    mark.append(svgIcon(iconName));
    const text = element('p');
    text.append(element('strong', '', strong));
    if (rest) text.append(document.createTextNode(' ' + rest));
    line.append(mark, text);
    return line;
  }
  function renderDiary(diary) {
    const box = $('brain-diary');
    box.replaceChildren();
    $('brain-diary-range').textContent = shortDay(diary.since, true) + ' – ' + shortDay(diary.until, true);
    const list = element('ul', 'diary-list');
    if (diary.knowledge) list.append(diaryLine('spark', '+' + knowledgeCount(diary.knowledge),
      diary.from_chat ? '(из них ' + diary.from_chat + ' из чата)' : ''));
    if (diary.documents) list.append(diaryLine('file', diary.documents + ' ' + plural(diary.documents, 'новый документ', 'новых документа', 'новых документов') + ':',
      diary.document_names.join(', ') + (diary.documents > diary.document_names.length ? ' и другие' : '')));
    if (diary.branches) list.append(diaryLine('brain', plural(diary.branches, 'Новая ветка:', 'Новые ветки:', 'Новые ветки:'),
      diary.branch_names.join(', ') + (diary.branches > diary.branch_names.length ? ' и другие' : '')));
    if (diary.top_topics.length) list.append(diaryLine('arrow', 'Быстрее всего росли:',
      diary.top_topics.map(topic => topic.name + ' (+' + topic.week + ')').join(', ')));
    if (diary.exams) list.append(diaryLine('check', diary.exams + ' ' + plural(diary.exams, 'экзамен', 'экзамена', 'экзаменов') + ',',
      'лучший результат ' + (diary.best_quality * 100).toFixed(1) + '%'));
    if (diary.gaps) list.append(diaryLine('search', 'Найдено пробелов: ' + diary.gaps, '— их можно посмотреть в Лаборатории'));
    for (const skill of diary.skills) list.append(diaryLine('settings', 'Навык «' + skill.name + '»',
      skill.status === 'approved' ? 'одобрен' : skill.status === 'proposed' ? 'предложен' : 'отключён'));
    if (!list.children.length) box.append(emptyState('За эту неделю Мозг ничего нового не узнал. Новые документы и сообщения в чате появятся здесь.', 'spark'));
    else box.append(list);
  }
  function renderLevels(topics) {
    const box = $('brain-levels');
    box.replaceChildren();
    if (!topics.length) { box.append(emptyState('Темы появятся, когда в Мозге будут знания.')); return; }
    const largest = Math.max(...topics.map(topic => topic.count), 1);
    for (const topic of topics) {
      const row = element('div', 'level-row');
      const head = element('div', 'level-head');
      const name = button(topic.name, () => openBranch(topic.id), 'level-name');
      name.title = 'Открыть ветку «' + topic.name + '»';
      const badge = element('span', 'level-badge level-' + topic.level);
      const dots = element('span', 'level-dots');
      dots.setAttribute('aria-hidden', 'true');
      for (let i = 1; i <= 4; i++) dots.append(element('i', i <= topic.level ? 'on' : ''));
      badge.append(dots, document.createTextNode(topic.level_name));
      head.append(name, badge);
      const bar = element('span', 'level-bar');
      bar.style.setProperty('--i', topics.indexOf(topic));
      bar.style.setProperty('--fill', Math.max(3, Math.round(topic.count / largest * 100)) + '%');
      const meta = element('small', 'level-meta', knowledgeCount(topic.count) + ' · ' + topic.sources + ' ' +
        plural(topic.sources, 'источник', 'источника', 'источников') + (topic.week ? ' · +' + topic.week + ' за неделю' : ''));
      row.append(head, bar, meta);
      box.append(row);
    }
    box.append(element('p', 'module-muted level-note',
      'Уровень растёт с объёмом знаний и числом независимых источников: Начальный, Растущий, Уверенный, Глубокий. Это мера покрытия, а не проверка истинности.'));
  }
  async function loadGrowth() {
    try {
      const data = await request('brain/growth?' + new URLSearchParams({days: 30, offset: -new Date().getTimezoneOffset()}));
      renderGrowthChart(data.series);
      renderDiary(data.diary);
      renderLevels(data.topics);
      mapFresh = data.branches_week || {};
    } catch (error) {
      $('brain-growth-chart').replaceChildren(emptyState(error.message, 'spark'));
    }
  }

  async function loadBrain() {
    if (brainLoading) return;
    brainLoading = true;
    const refresh = $('brain-refresh');
    refresh.classList.add('spinning'); refresh.disabled = true;
    try {
      const data = await request('brain');
      brainData = {branches: data.branches || [], recent: data.recent || []};
      const stats = data.stats || {};
      $('brain-branches-count').textContent = brainData.branches.length;
      $('brain-facts-count').textContent = stats.facts ?? brainData.branches.reduce((count, row) => count + row.facts, 0);
      $('brain-files-count').textContent = stats.files ?? 0;
      $('brain-chat-count').textContent = stats.chat ?? 0;
      renderEvents();
      await Promise.all([loadLab(), loadGrowth()]);
      renderMap();
    } catch (error) { message(error.message); }
    finally { brainLoading = false; refresh.classList.remove('spinning'); refresh.disabled = false; }
  }
  // Живая карта знаний: ядро, ветки по кругу, знания-листья, потоки и рост.
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const MAP = {width: 1000, height: 640, rx: 1.5};
  let mapNodes = new Map(), mapFresh = {}, mapPlayed = false, openNodeId = null, mapTotal = 0, growthRun = 0;
  const calm = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  function svg(tag, attrs, className) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
    if (className) node.setAttribute('class', className);
    return node;
  }
  function polar(angle, radius) {
    return [MAP.width / 2 + Math.cos(angle) * radius * MAP.rx, MAP.height / 2 + Math.sin(angle) * radius];
  }
  // Радиальная раскладка: сектор ветки пропорционален числу её листьев.
  function layoutMap() {
    const branches = brainData.branches;
    const known = new Set(branches.map(item => item.id));
    const roots = branches.filter(item => item.parent === null || !known.has(item.parent));
    const leaves = node => { const kids = childrenOf(node.id); return kids.length ? kids.reduce((sum, kid) => sum + leaves(kid), 0) : 1; };
    const totalLeaves = roots.reduce((sum, root) => sum + leaves(root), 0) || 1;
    const placed = [];
    let cursor = -Math.PI / 2;
    const place = (node, depth, from, to, parent) => {
      const angle = (from + to) / 2;
      const radius = [0, 125, 205, 262, 300][Math.min(depth, 4)];
      const total = subtreeTotal(node);
      const size = depth === 1 ? Math.min(26, 9 + Math.sqrt(total) * 2.6) : Math.min(14, 4.5 + Math.sqrt(total) * 1.6);
      const [x, y] = polar(angle, radius);
      const item = {node, depth, angle, x, y, size, total, parent, children: []};
      placed.push(item);
      if (parent) parent.children.push(item);
      const kids = childrenOf(node.id).sort((a, b) => a.name.localeCompare(b.name, 'ru'));
      const span = to - from, weight = kids.reduce((sum, kid) => sum + leaves(kid), 0) || 1;
      let start = from;
      for (const kid of kids) {
        const share = span * leaves(kid) / weight;
        place(kid, depth + 1, start, start + share, item);
        start += share;
      }
    };
    for (const root of roots.sort((a, b) => subtreeTotal(b) - subtreeTotal(a))) {
      const share = Math.PI * 2 * leaves(root) / totalLeaves;
      place(root, 1, cursor, cursor + share, null);
      cursor += share;
    }
    return placed;
  }
  function linkPath(from, to) {
    const [cx, cy] = from ? [from.x, from.y] : [MAP.width / 2, MAP.height / 2];
    const bend = polar(to.angle, ([0, 70, 165, 235, 285][Math.min(to.depth, 4)]));
    return `M${cx.toFixed(1)},${cy.toFixed(1)} Q${bend[0].toFixed(1)},${bend[1].toFixed(1)} ${to.x.toFixed(1)},${to.y.toFixed(1)}`;
  }
  // Подпись не должна вылезать за край карты: ветку у края подписываем внутрь
// и укорачиваем имя под оставшееся место (ширина символа — грубая оценка).
function placeLabel(label, item) {
  const root = item.depth === 1, font = MAP.narrow ? (root ? 21 : 17) : (root ? 15 : 12);
  const char = font * .58, pad = 6, name = item.node.name;
  const fit = space => {
    const max = Math.max(4, Math.min(26, Math.floor(space / char)));
    return name.length > max ? name.slice(0, max - 1) + '…' : name;
  };
  if (root) {
    const text = fit(MAP.width - pad * 2), half = text.length * char / 2;
    const shift = Math.max(pad + half - item.x, Math.min(0, MAP.width - pad - half - item.x));
    label.setAttribute('x', shift.toFixed(1));
    label.setAttribute('text-anchor', 'middle');
    label.textContent = text;
    return;
  }
  const gap = item.size + 9, right = MAP.width - item.x - gap - pad, left = item.x - gap - pad;
  let outward = Math.cos(item.angle) >= 0;
  const wanted = Math.min(name.length, 26) * char;
  if ((outward ? right : left) < wanted && (outward ? left : right) > (outward ? right : left)) outward = !outward;
  label.setAttribute('x', (outward ? gap : -gap).toFixed(1));
  label.setAttribute('text-anchor', outward ? 'start' : 'end');
  label.textContent = fit(outward ? right : left);
}

function renderMap() {
    const box = $('brain-map');
    closeMapCard();
    const narrow = box.clientWidth > 0 && box.clientWidth < 640;
    Object.assign(MAP, narrow ? {width: 600, height: 720, rx: 1, narrow} : {width: 1000, height: 640, rx: 1.5, narrow});
    box.classList.toggle('narrow', narrow);
    box.replaceChildren();
    mapNodes = new Map();
    const placed = layoutMap();
    const total = mapTotal = brainData.branches.reduce((sum, item) => sum + item.facts, 0);
    $('brain-map-count').textContent = brainData.branches.length ? brainData.branches.length + ' ' + plural(brainData.branches.length, 'ветка', 'ветки', 'веток') : '';
    const root = svg('svg', {viewBox: `0 0 ${MAP.width} ${MAP.height}`, role: 'group', 'aria-label': 'Карта знаний Мозга'}, 'brain-map-svg');
    const defs = svg('defs');
    defs.innerHTML = '<radialGradient id="map-core"><stop offset="0" stop-color="#fff3cf"/><stop offset=".45" stop-color="#ecca7c"/><stop offset="1" stop-color="#9c7a3a"/></radialGradient>' +
      '<radialGradient id="map-halo"><stop offset="0" stop-color="#d4af5f" stop-opacity=".35"/><stop offset="1" stop-color="#d4af5f" stop-opacity="0"/></radialGradient>' +
      '<radialGradient id="map-node"><stop offset="0" stop-color="#ecca7c"/><stop offset="1" stop-color="#7a5e2c"/></radialGradient>' +
      '<filter id="map-glow" x="-1" y="-1" width="3" height="3"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>';
    root.append(defs);
    // Фон: орбиты и мерцающие звёзды.
    const sky = svg('g', {}, 'map-sky');
    for (const radius of [125, 205, 262]) sky.append(svg('ellipse', {cx: MAP.width / 2, cy: MAP.height / 2, rx: radius * MAP.rx, ry: radius}, 'map-orbit'));
    for (let i = 0; i < 46; i++) {
      const star = svg('circle', {cx: (i * 211 % MAP.width), cy: (i * 137 % MAP.height), r: i % 5 ? .8 : 1.4}, 'map-star');
      star.style.setProperty('--d', (i % 7) * .6 + 's');
      sky.append(star);
    }
    const halo = svg('circle', {cx: MAP.width / 2, cy: MAP.height / 2, r: 150}, 'map-halo');
    halo.style.transformOrigin = `${MAP.width / 2}px ${MAP.height / 2}px`;
    root.append(sky, halo);
    const links = svg('g', {}, 'map-links'), flows = svg('g', {}, 'map-flows'), nodes = svg('g', {}, 'map-nodes');
    root.append(links, flows, nodes);
    const order = [...placed].sort((a, b) => String(a.node.created).localeCompare(String(b.node.created)) || a.depth - b.depth);
    order.forEach((item, index) => { item.order = index; });
    placed.forEach((item, index) => {
      const fresh = mapFresh[item.node.id] || 0;
      const path = svg('path', {d: linkPath(item.parent, item), id: 'map-link-' + index}, 'map-link depth-' + item.depth + (fresh ? ' fresh' : ''));
      path.style.setProperty('--w', Math.max(.8, Math.min(4, Math.sqrt(item.total) * (item.depth === 1 ? .9 : .5))));
      path.style.setProperty('--o', item.order);
      links.append(path);
      // Потоки энергии от ядра к веткам: больше знаний — чаще.
      if (!calm() && (item.depth === 1 || fresh) && item.total) {
        const pulses = item.depth === 1 ? Math.min(3, 1 + Math.floor(item.total / 15)) : 1;
        for (let p = 0; p < pulses; p++) {
          const dot = svg('circle', {r: fresh ? 2.6 : 2}, 'map-flow' + (fresh ? ' fresh' : ''));
          const motion = svg('animateMotion', {dur: (3.2 + (index % 4) * .7) + 's', begin: (p * 1.3 + index * .17).toFixed(2) + 's', repeatCount: 'indefinite'});
          const ref = svg('mpath');
          ref.setAttribute('href', '#map-link-' + index);
          motion.append(ref);
          dot.append(motion);
          flows.append(dot);
        }
      }
      const group = svg('g', {transform: `translate(${item.x.toFixed(1)} ${item.y.toFixed(1)})`, tabindex: 0, role: 'button',
        'aria-label': item.node.name + ': ' + knowledgeCount(item.total) + (fresh ? ', +' + fresh + ' за неделю' : '')},
        'map-node depth-' + item.depth + (fresh ? ' fresh' : '') + (item.depth > 1 ? ' small' : ''));
      group.style.setProperty('--o', item.order);
      const inner = svg('g', {}, 'map-node-body');
      if (fresh) inner.append(svg('circle', {r: item.size + 9}, 'map-aura'));
      // Листья-знания вращаются вокруг ветки.
      const orbit = svg('g', {}, 'map-leaves');
      orbit.style.setProperty('--spin', (18 + (index % 5) * 6) + 's');
      const leaves = Math.min(item.depth === 1 ? 14 : 7, item.node.facts);
      for (let l = 0; l < leaves; l++) {
        const a = l / leaves * Math.PI * 2, r = item.size + 5 + (l % 2) * 3;
        orbit.append(svg('circle', {cx: (Math.cos(a) * r).toFixed(1), cy: (Math.sin(a) * r).toFixed(1), r: item.depth === 1 ? 1.8 : 1.3}, 'map-leaf'));
      }
      inner.append(orbit, svg('circle', {r: item.size}, 'map-dot'));
      if (item.depth === 1) {
        const count = svg('text', {y: 4}, 'map-count');
        count.textContent = item.total;
        inner.append(count);
      }
      const label = svg('text', {y: item.depth === 1 ? -item.size - 6 : 4}, 'map-label' + (item.depth === 1 ? ' root' : ''));
      placeLabel(label, item);
      inner.append(label);
      if (fresh) {
        const badge = svg('text', {x: 0, y: item.size + (item.depth === 1 ? 16 : 13), 'text-anchor': 'middle'}, 'map-fresh');
        badge.textContent = '+' + fresh;
        inner.append(badge);
      }
      group.append(inner);
      const open = () => openMapCard(item);
      group.addEventListener('click', open);
      group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } });
      group.addEventListener('mouseenter', () => highlightChain(item, true));
      group.addEventListener('mouseleave', () => highlightChain(item, false));
      nodes.append(group);
      mapNodes.set(item.node.id, {item, group, path});
    });
    // Ядро поверх всего: общий объём памяти.
    const core = svg('g', {transform: `translate(${MAP.width / 2} ${MAP.height / 2})`}, 'map-core');
    core.append(svg('circle', {r: 52}, 'map-core-ring'), svg('circle', {r: 52}, 'map-core-ring late'), svg('circle', {r: 34, fill: 'url(#map-core)', filter: 'url(#map-glow)'}));
    const coreCount = svg('text', {y: 6}, 'map-core-count');
    coreCount.textContent = total;
    const coreLabel = svg('text', {y: 52 + 20}, 'map-core-label');
    coreLabel.textContent = placed.length ? knowledgeCount(total).replace(/^\d+ /, '') : 'ждёт первых знаний';
    core.append(coreCount, coreLabel);
    root.append(core);
    box.append(root);
    root.style.setProperty('--count', placed.length || 1);
    if (!placed.length) box.append(element('p', 'brain-map-empty', 'Загрузите документ на Диск или расскажите что-нибудь в чате — здесь вырастут первые ветки.'));
    if (!mapPlayed && placed.length) { mapPlayed = true; playGrowth(); }
  }
  function highlightChain(item, on) {
    const box = $('brain-map');
    box.classList.toggle('focusing', on);
    for (let cur = item; cur; cur = cur.parent) {
      const entry = mapNodes.get(cur.node.id);
      entry?.group.classList.toggle('lit', on);
      entry?.path.classList.toggle('lit', on);
    }
  }
  // Повтор роста: ветки появляются в порядке, в котором их узнал Мозг.
  function playGrowth() {
    const svgRoot = $('brain-map').querySelector('svg');
    if (!svgRoot || calm()) return;
    svgRoot.classList.remove('growing');
    void svgRoot.getBoundingClientRect();
    svgRoot.classList.add('growing');
    const counter = svgRoot.querySelector('.map-core-count');
    const run = ++growthRun, target = mapTotal, started = performance.now(), duration = 600 + mapNodes.size * 90;
    const tick = now => {
      if (run !== growthRun) return;
      const t = Math.min(1, (now - started) / duration);
      counter.textContent = Math.round(target * (1 - Math.pow(1 - t, 3)));
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
  function closeMapCard() {
    $('brain-map')?.querySelector('.map-card')?.remove();
    $('brain-map')?.querySelectorAll('.map-node.open').forEach(node => node.classList.remove('open'));
    openNodeId = null;
  }
  async function openMapCard(item) {
    closeMapCard();
    openNodeId = item.node.id;
    const box = $('brain-map');
    mapNodes.get(item.node.id)?.group.classList.add('open');
    const card = element('div', 'map-card');
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', item.node.name);
    const head = element('div', 'map-card-head');
    const titles = element('div');
    const chain = ancestors(item.node);
    if (chain.length) titles.append(element('small', 'map-card-path', chain.map(node => node.name).join(' › ')));
    titles.append(element('h3', '', item.node.name));
    const close = button('', closeMapCard, 'icon-button');
    close.setAttribute('aria-label', 'Закрыть');
    close.append(svgIcon('close'));
    head.append(titles, close);
    const fresh = mapFresh[item.node.id] || 0;
    const stats = element('p', 'map-card-stats', knowledgeCount(item.total) + (item.children.length ? ' · ' + item.children.length + ' ' + plural(item.children.length, 'подветка', 'подветки', 'подветок') : '') + (fresh ? ' · +' + fresh + ' за неделю' : ''));
    const list = element('div', 'map-card-list');
    list.append(element('div', 'brain-skeleton tall'));
    card.append(head, stats, list);
    if (item.children.length) {
      const chips = element('div', 'brain-subbranches');
      item.children.forEach(child => chips.append(button(child.node.name, () => openMapCard(child), 'brain-chip')));
      card.append(chips);
    }
    box.append(card);
    positionMapCard(card, item);
    card.addEventListener('keydown', event => { if (event.key === 'Escape') { closeMapCard(); mapNodes.get(item.node.id)?.group.focus(); } });
    close.focus({preventScroll: true});
    const ticket = ++factsRequest;
    try {
      const data = await request('brain/facts?branch=' + encodeURIComponent(item.node.id));
      if (ticket !== factsRequest || openNodeId !== item.node.id) return;
      list.replaceChildren();
      if (!data.facts.length) list.append(element('p', 'module-muted', item.children.length ? 'Прямых записей нет, знания лежат в подветках.' : 'В этой ветке пока нет записей.'));
      const facts = data.facts;
      facts.slice(0, 3).forEach(fact => list.append(knowledgeCard(fact)));
      if (facts.length > 3) {
        const more = button('Показать все (' + (facts.length >= 100 ? '100+' : facts.length) + ')', () => {
          more.remove();
          facts.slice(3).forEach(fact => list.append(knowledgeCard(fact)));
          positionMapCard(card, item);
        }, 'secondary-button map-card-more');
        list.append(more);
      }
      positionMapCard(card, item);
    } catch (error) {
      if (ticket === factsRequest) list.replaceChildren(emptyState(error.message));
    }
  }
  // Карточка целиком внутри карты: рядом с веткой, но не ниже нижнего края.
  function positionMapCard(card, item) {
    const box = $('brain-map'), width = box.clientWidth, height = box.clientHeight, gap = 8;
    // Карточка — рядом с веткой, на стороне, где больше места, но всегда целиком в карте.
    const x = item.x / MAP.width * width, cardWidth = card.offsetWidth;
    const left = x > width / 2 ? x - cardWidth - 24 : x + 24;
    card.style.left = Math.max(gap, Math.min(left, width - cardWidth - gap)) + 'px';
    if (MAP.narrow) return;
    const wanted = item.y / MAP.height * height - 60;
    card.style.top = Math.max(gap, Math.min(wanted, height - card.offsetHeight - gap)) + 'px';
  }
  function openBranch(id) {
    const entry = mapNodes.get(id);
    if (!entry) { message('Ветка не найдена. Нажмите «Обновить».'); return; }
    $('brain-map').closest('.module-panel').scrollIntoView({behavior: calm() ? 'auto' : 'smooth', block: 'start'});
    openMapCard(entry.item);
  }
  document.addEventListener('click', event => {
    // composedPath видит и элементы, удалённые обработчиком этого же клика.
    const inside = event.composedPath().some(node => node instanceof Element && node.matches('.map-card,.map-node,.brain-chip,.level-name'));
    if (openNodeId !== null && !inside) closeMapCard();
  });
  $('brain-map-replay').addEventListener('click', playGrowth);
  let mapResize;
  addEventListener('resize', () => {
    clearTimeout(mapResize);
    mapResize = setTimeout(() => {
      const box = $('brain-map');
      if (!$('brain-view').hidden && box.clientWidth && (box.clientWidth < 640) !== Boolean(MAP.narrow)) renderMap();
    }, 200);
  });

  async function searchBrain(event) {
    event.preventDefault();
    const query = $('brain-search-input').value.trim();
    const panel = $('brain-search-results');
    if (query.length < 2) { message('Введите хотя бы два символа.'); return; }
    panel.hidden = false;
    panel.replaceChildren(element('div', 'brain-skeleton tall'));
    const ticket = ++searchRequest;
    try {
      const data = await request('brain/search?' + new URLSearchParams({q: query}));
      if (ticket !== searchRequest) return;
      const head = element('div', 'brain-search-head');
      head.append(element('h2', '', data.results.length ?
        'Найдено: ' + knowledgeCount(data.results.length) : 'Ничего не найдено'));
      const close = button('', () => { searchRequest++; panel.hidden = true; panel.replaceChildren(); }, 'icon-button');
      close.setAttribute('aria-label', 'Закрыть результаты поиска');
      close.append(svgIcon('close'));
      head.append(close);
      panel.replaceChildren(head);
      if (!data.results.length) panel.append(element('p', 'module-muted',
        'В Мозге нет знаний, достаточно точно подходящих под запрос «' + query + '». Попробуйте другие слова или загрузите документ на Диск.'));
      for (const item of data.results) panel.append(knowledgeCard(item, item.branch, item.branch_id));
    } catch (error) {
      if (ticket === searchRequest) panel.replaceChildren(emptyState(error.message, 'search'));
    }
  }
  $('brain-search-form').addEventListener('submit', searchBrain);
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