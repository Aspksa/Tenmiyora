/* Диск и Мозг Tenmiyora. Никаких внешних библиотек и CDN. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let folder = null, searchTimer, loading = false;
  let selectedBranch = null;
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
  async function loadDisk() {
    if (loading) return;
    loading = true;
    try {
      const q = $('disk-search').value.trim();
      const data = await request('disk?' + new URLSearchParams({folder: folder || '', q}));
      const breadcrumbs = $('disk-breadcrumbs');
      breadcrumbs.replaceChildren(button('Мой диск', () => navigate(null)));
      for (const crumb of data.breadcrumbs) {
        breadcrumbs.append(element('span', '', '/'));
        breadcrumbs.append(button(crumb.name, () => navigate(crumb.id)));
      }
      const list = $('disk-list');
      list.replaceChildren();
      const total = data.folders.length + data.files.length;
      $('disk-count').textContent = total + ' элементов';
      for (const item of data.folders) list.append(makeRow('folder', item));
      for (const item of data.files) list.append(makeRow('file', item));
      if (!total) list.append(element('p', 'disk-empty', q ? 'По вашему запросу ничего не найдено.' : 'Папка пуста. Перетащите сюда файлы или создайте папку.'));
    } catch (error) { message(error.message); }
    finally { loading = false; }
  }
  function navigate(id) {
    folder = id;
    $('disk-search').value = '';
    loadDisk();
  }
  function makeRow(kind, item) {
    const row = element('div', 'disk-row');
    row.append(icon(kind));
    const main = element('div', 'disk-item-content');
    main.append(button(item.name, () => kind === 'folder' ? navigate(item.id) : download(item), 'disk-item-name'));
    main.append(element('small', 'disk-item-meta', kind === 'folder' ?
      'Папка · ' + date(item.created) :
      readableBytes(item.size) + ' · ' + item.status + ' · ' + date(item.created)));
    row.append(main);
    const actions = element('div', 'disk-row-actions');
    if (kind === 'file') {
      actions.append(button('Изучить', () => openDocument(item)));
      actions.append(button('Скачать', () => download(item)));
    }
    actions.append(button('Имя', async () => {
      const next = prompt('Новое имя:', item.name);
      if (next === null || next.trim() === item.name) return;
      try {
        await request('disk/rename', {kind, id: item.id, name: next.trim()});
        await loadDisk();
      } catch (error) { message(error.message); }
    }));
    actions.append(button('Удалить', async () => {
      if (!confirm('Удалить «' + item.name + '»? Связанные знания из файла тоже будут удалены.')) return;
      try {
        await request('disk/delete', {kind, id: item.id});
        await loadDisk();
        if (location.hash === '#brain') await loadBrain();
      } catch (error) { message(error.message); }
    }));
    row.append(actions);
    return row;
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
  async function upload(files) {
    for (const file of files) {
      if (file.size > 25 * 1024 * 1024) {
        message(file.name + ': файл больше 25 МБ'); continue;
      }
      $('disk-count').textContent = 'Загрузка: ' + file.name;
      try {
        const response = await fetch('/api/disk/upload', {
          method: 'POST', credentials: 'same-origin',
          headers: {...headers, 'X-Tenmiyora-Filename': encodeURIComponent(file.name),
                    'X-Tenmiyora-Folder': folder || '',
                    'X-Tenmiyora-Mime': file.type || 'application/octet-stream'},
          body: file
        });
        const result = await response.json();
        if (!response.ok) throw Error(result.error || 'Ошибка загрузки.');
        message('Сохранён «' + file.name + '». ' + result.status + '.');
      } catch (error) { message(file.name + ': ' + error.message); }
    }
    await loadDisk();
  }
  $('disk-file-input').addEventListener('change', event => {
    upload([...event.target.files]); event.target.value = '';
  });
  $('disk-upload-button').addEventListener('click', () => $('disk-file-input').click());
  $('disk-new-folder').addEventListener('click', async () => {
    const name = prompt('Название новой папки:');
    if (name === null) return;
    try {
      await request('disk/folder', {parent: folder, name: name.trim()});
      await loadDisk();
    } catch (error) { message(error.message); }
  });
  const dropzone = $('disk-dropzone');
  dropzone.addEventListener('click', () => $('disk-file-input').click());
  dropzone.addEventListener('keydown', event => {
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
    target.addEventListener('drop', event => {
      event.preventDefault(); dropzone.classList.remove('drag-over');
      if (event.dataTransfer?.files.length) upload([...event.dataTransfer.files]);
    });
  }
  $('disk-search').addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadDisk, 220);
  });

  // ---- Мозг ----
  let brainData = {branches: [], recent: []};
  let brainLoading = false, brainLoaded = false, factsRequest = 0, searchRequest = 0;
  const expanded = new Set();
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

  function renderTree() {
    const list = $('brain-tree');
    const filter = $('brain-filter').value.trim().toLowerCase();
    list.replaceChildren();
    const branches = brainData.branches;
    $('brain-tree-count').textContent = branches.length ? branches.length + ' ' + plural(branches.length, 'ветка', 'ветки', 'веток') : '';
    if (!branches.length) {
      list.append(emptyState('Пока нет знаний. Загрузите текстовый документ на Диск или поделитесь содержательной информацией в чате.'));
      return;
    }
    const roots = branches.filter(item => item.parent === null || !branches.some(other => other.id === item.parent));
    const totals = new Map();
    const total = node => {
      if (!totals.has(node.id)) totals.set(node.id, subtreeTotal(node));
      return totals.get(node.id);
    };
    const largest = Math.max(1, ...roots.map(total));
    const matches = node => !filter || node.name.toLowerCase().includes(filter) ||
      childrenOf(node.id).some(matches);
    function addNode(node, depth) {
      if (!matches(node)) return;
      const children = childrenOf(node.id);
      const open = Boolean(filter) || expanded.has(node.id);
      const row = element('div', 'brain-node' + (node.id === selectedBranch ? ' active' : ''));
      row.style.setProperty('--depth', depth);
      row.setAttribute('role', 'treeitem');
      row.setAttribute('aria-level', depth + 1);
      row.setAttribute('aria-selected', node.id === selectedBranch ? 'true' : 'false');
      if (children.length) {
        row.setAttribute('aria-expanded', open ? 'true' : 'false');
        const caret = button('', () => {
          if (expanded.has(node.id)) expanded.delete(node.id); else expanded.add(node.id);
          renderTree();
        }, 'brain-caret' + (open ? ' open' : ''));
        caret.setAttribute('aria-label', (open ? 'Свернуть' : 'Развернуть') + ' «' + node.name + '»');
        caret.append(svgIcon('chevron'));
        row.append(caret);
      } else {
        row.append(element('span', 'brain-caret-space'));
      }
      const main = button('', () => selectBranch(node), 'brain-branch');
      main.append(element('span', 'brain-branch-name', node.name));
      const count = total(node);
      main.title = node.name + ' · ' + knowledgeCount(count);
      if (depth === 0) {
        const bar = element('span', 'brain-weight');
        bar.style.setProperty('--weight', Math.max(4, Math.round(count / largest * 100)) + '%');
        main.append(bar);
      }
      main.append(element('small', '', count));
      row.append(main);
      list.append(row);
      if (open) children.forEach(child => addNode(child, depth + 1));
    }
    roots.forEach(root => addNode(root, 0));
    if (!list.children.length) list.append(element('p', 'module-muted brain-tree-none', 'Нет веток с таким названием.'));
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
    } catch (error) {
      $('brain-growth-chart').replaceChildren(emptyState(error.message, 'spark'));
    }
  }

  async function loadBrain() {
    if (brainLoading) return;
    brainLoading = true;
    const refresh = $('brain-refresh');
    refresh.classList.add('spinning'); refresh.disabled = true;
    if (!brainLoaded) $('brain-tree').replaceChildren(...Array.from({length: 5}, () => element('div', 'brain-skeleton')));
    try {
      const data = await request('brain');
      brainData = {branches: data.branches || [], recent: data.recent || []};
      brainLoaded = true;
      const stats = data.stats || {};
      $('brain-branches-count').textContent = brainData.branches.length;
      $('brain-facts-count').textContent = stats.facts ?? brainData.branches.reduce((count, row) => count + row.facts, 0);
      $('brain-files-count').textContent = stats.files ?? 0;
      $('brain-chat-count').textContent = stats.chat ?? 0;
      if (selectedBranch !== null && !brainData.branches.some(item => item.id === selectedBranch)) resetDetail();
      renderTree();
      renderEvents();
      await Promise.all([loadLab(), loadGrowth()]);
    } catch (error) { message(error.message); }
    finally { brainLoading = false; refresh.classList.remove('spinning'); refresh.disabled = false; }
  }
  function resetDetail() {
    selectedBranch = null;
    $('brain-detail-title').textContent = 'Содержимое ветки';
    $('brain-detail-path').replaceChildren();
    $('brain-detail-count').hidden = true;
    $('brain-detail').replaceChildren(emptyState('Выберите ветку слева, чтобы увидеть знания и их источники.'));
  }
  function openBranch(id) {
    const node = brainData.branches.find(item => item.id === id);
    if (node) selectBranch(node, true);
    else message('Ветка не найдена. Нажмите «Обновить».');
  }
  async function selectBranch(branch, reveal) {
    selectedBranch = branch.id;
    const chain = ancestors(branch);
    chain.forEach(parent => expanded.add(parent.id));
    renderTree();
    $('brain-detail-title').textContent = branch.name;
    const path = $('brain-detail-path');
    path.replaceChildren();
    for (const parent of chain) {
      path.append(button(parent.name, () => selectBranch(parent)), element('span', '', '›'));
    }
    const detail = $('brain-detail');
    detail.replaceChildren(...Array.from({length: 3}, () => element('div', 'brain-skeleton tall')));
    $('brain-detail-count').hidden = true;
    const ticket = ++factsRequest;
    if (reveal || matchMedia('(max-width:1100px)').matches) detail.closest('.module-panel').scrollIntoView({behavior: 'smooth', block: 'start'});
    try {
      const data = await request('brain/facts?branch=' + encodeURIComponent(branch.id));
      if (ticket !== factsRequest) return;
      detail.replaceChildren();
      const count = $('brain-detail-count');
      count.textContent = data.facts.length >= 100 ? '100+ знаний' : knowledgeCount(data.facts.length);
      count.hidden = false;
      if (!data.facts.length) {
        const children = childrenOf(branch.id);
        detail.append(emptyState(children.length ? 'Прямых записей нет. Знания лежат в подразделах:' : 'В этой ветке пока нет записей.'));
        if (children.length) {
          const chips = element('div', 'brain-subbranches');
          children.forEach(child => chips.append(button(child.name, () => selectBranch(child), 'brain-chip')));
          detail.append(chips);
        }
      }
      for (const fact of data.facts) detail.append(knowledgeCard(fact));
    } catch (error) {
      if (ticket === factsRequest) detail.replaceChildren(emptyState(error.message));
    }
  }

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
  $('brain-filter').addEventListener('input', renderTree);
  $('brain-refresh').addEventListener('click', loadBrain);
  window.TenmiyoraModules = {
    show(view) {
      if (view === 'brain') loadBrain();
      if (view === 'disk') loadDisk();
    }
  };
  const initial = location.hash.replace('#', '');
  if (initial === 'brain' || initial === 'disk') window.TenmiyoraModules.show(initial);
})();