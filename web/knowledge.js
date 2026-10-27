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
      await Promise.all([loadLab(), loadGrowth(), loadActivity()]);
      mapBorn = newBranches(brainData.branches.map(row => row.id));
      renderMap();
    } catch (error) { message(error.message); }
    finally { brainLoading = false; refresh.classList.remove('spinning'); refresh.disabled = false; }
  }
  // Живая карта знаний: ядро, ветки по кругу, знания-листья, потоки и рост.
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const MAP = {width: 1000, height: 640, rx: 1.5};
  let mapNodes = new Map(), mapFresh = {}, mapPlayed = false, openNodeId = null, mapTotal = 0, growthRun = 0;
  let mapActivity = {synapses: [], alive: {}}, mapSynapses = [], mapBorn = new Set(), pulseSeen = null, sleepMode = null;
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
    const own = Date.parse(mapActivity.alive?.[item.node.id] || '') || 0;
    return Math.max(own, ...item.children.map(lastAlive));
  }
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
      const fresh = mapFresh[item.node.id] || 0, born = mapBorn.has(item.node.id);
      // Давно не пополнялась и не понадобилась — ветка тускнеет; вопрос о ней снова её зажжёт.
      const alive = lastAlive(item), idle = alive ? (now - alive) / DAY : 0;
      item.idleDays = Math.floor(idle);
      const rest = fresh || born ? '' : idle > 45 ? ' dormant' : idle > 14 ? ' resting' : '';
      const path = svg('path', {d: linkPath(item.parent, item), id: 'map-link-' + index}, 'map-link depth-' + item.depth + (fresh ? ' fresh' : '') + (born ? ' born' : '') + rest);
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
        'map-node depth-' + item.depth + (fresh ? ' fresh' : '') + (item.depth > 1 ? ' small' : '') + (born ? ' born' : '') + rest);
      group.style.setProperty('--o', item.order);
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
      if (fresh || born) {
        const badge = svg('text', {x: 0, y: item.size + (item.depth === 1 ? 16 : 13), 'text-anchor': 'middle'}, 'map-fresh');
        badge.textContent = born ? 'новая' : '+' + fresh;
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
    // Синапсы: дуги между темами с общими источниками или вместе нужными в ответах.
    (mapActivity.synapses || []).forEach((link, index) => {
      const a = mapNodes.get(link.a)?.item, b = mapNodes.get(link.b)?.item;
      if (!a || !b) return;
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      const qx = mx + (MAP.width / 2 - mx) * .45, qy = my + (MAP.height / 2 - my) * .45;
      const path = svg('path', {d: `M${a.x.toFixed(1)},${a.y.toFixed(1)} Q${qx.toFixed(1)},${qy.toFixed(1)} ${b.x.toFixed(1)},${b.y.toFixed(1)}`, id: 'map-syn-' + index},
        'map-synapse' + (link.used ? ' used' : ''));
      path.style.setProperty('--w', Math.min(3, .6 + Math.log2(1 + link.weight) * .45).toFixed(2));
      synapses.append(path);
      if (link.used && !calm()) {
        const spark = svg('circle', {r: 1.6}, 'map-syn-spark');
        const motion = svg('animateMotion', {dur: (6 + index % 5) + 's', begin: (index * .9).toFixed(1) + 's', repeatCount: 'indefinite', keyPoints: index % 2 ? '1;0' : '0;1', keyTimes: '0;1', calcMode: 'linear'});
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
    core.append(svg('circle', {r: 52}, 'map-core-ring'), svg('circle', {r: 52}, 'map-core-ring late'), svg('circle', {r: 34, fill: 'url(#map-core)', filter: 'url(#map-glow)'}, 'map-core-ball'));
    const coreCount = svg('text', {y: 6}, 'map-core-count');
    coreCount.textContent = total;
    const coreLabel = svg('text', {y: 52 + 20}, 'map-core-label');
    coreLabel.textContent = placed.length ? knowledgeCount(total).replace(/^\d+ /, '') : 'ждёт первых знаний';
    core.append(coreCount, coreLabel);
    root.append(core);
    box.append(root);
    root.style.setProperty('--count', placed.length || 1);
    if (!placed.length) box.append(element('p', 'brain-map-empty', 'Загрузите документ на Диск или расскажите что-нибудь в чате — здесь вырастут первые ветки.'));
    updateSleep();
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
    for (const link of mapSynapses) {
      if (link.a === item.node.id || link.b === item.node.id) link.path.classList.toggle('lit', on);
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
    const asleep = sleepMode ?? (hour >= 23 || hour < 7);
    box.classList.toggle('sleeping', asleep);
    let badge = box.querySelector('.brain-map-sleep');
    if (asleep && !badge) {
      badge = element('p', 'brain-map-sleep', 'Мозг спит и перебирает знания');
      box.append(badge);
    }
    if (!asleep) badge?.remove();
    const toggle = $('brain-map-sleep');
    toggle.setAttribute('aria-pressed', String(asleep));
  }
  setInterval(updateSleep, 60000);
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
    card.append(head, stats);
    if (item.idleDays > 14 && !fresh) card.append(element('p', 'map-card-rest',
      'Не пополнялась и не была нужна ' + item.idleDays + ' ' + plural(item.idleDays, 'день', 'дня', 'дней') + '. Спросите о ней в чате, и ветка снова загорится.'));
    const linked = mapSynapses.filter(link => link.a === item.node.id || link.b === item.node.id)
      .map(link => mapNodes.get(link.a === item.node.id ? link.b : link.a)?.item).filter(Boolean);
    if (linked.length) {
      const row = element('div', 'brain-subbranches map-card-links');
      row.append(element('span', 'map-card-links-title', 'Связана с:'));
      linked.slice(0, 6).forEach(other => row.append(button(other.node.name, () => openMapCard(other), 'brain-chip')));
      card.append(row);
    }
    card.append(list);
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
  $('brain-map-sleep').addEventListener('click', () => { sleepMode = !$('brain-map').classList.contains('sleeping'); updateSleep(); });
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
      pollPulses();
    } catch (error) {
      if (ticket === searchRequest) panel.replaceChildren(emptyState(error.message, 'search'));
    }
  }
  $('brain-search-form').addEventListener('submit', searchBrain);
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