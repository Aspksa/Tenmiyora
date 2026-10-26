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

  async function loadBrain() {
    try {
      const data = await request('brain');
      const branches = data.branches || [];
      $('brain-branches-count').textContent = branches.length;
      $('brain-facts-count').textContent = branches.reduce((count, row) => count + row.facts, 0);
      $('brain-events-count').textContent = data.recent.length;
      const list = $('brain-tree');
      list.replaceChildren();
      const roots = branches.filter(item => item.parent === null);
      function addNode(node, depth) {
        const item = button(node.name, () => selectBranch(node), 'brain-branch' + (depth ? ' child' : ''));
        item.append(element('small', '', node.facts + ' записей'));
        item.classList.toggle('active', node.id === selectedBranch);
        list.append(item);
        branches.filter(child => child.parent === node.id).forEach(child => addNode(child, depth + 1));
      }
      roots.forEach(root => addNode(root, 0));
      if (!branches.length) list.append(element('p', 'module-muted', 'Пока нет знаний. Загрузите текстовый документ на Диск или поделитесь содержательной информацией в чате.'));
      const events = $('brain-events'); events.replaceChildren();
      if (!data.recent.length) events.append(element('p', 'module-muted', 'Рост памяти пока не начался.'));
      for (const event of data.recent) {
        const row = element('div', 'brain-event');
        row.append(element('span', '', event.action + ': ' + event.detail));
        row.append(element('time', '', date(event.time)));
        events.append(row);
      }
    } catch (error) { message(error.message); }
  }
  async function selectBranch(branch) {
    selectedBranch = branch.id;
    $('brain-detail-title').textContent = branch.name;
    try {
      const data = await request('brain/facts?branch=' + encodeURIComponent(branch.id));
      const detail = $('brain-detail'); detail.replaceChildren();
      if (!data.facts.length) detail.append(element('p', 'module-muted', 'В этой ветке пока нет прямых записей. Откройте её подразделы.'));
      for (const fact of data.facts) {
        const item = element('div', 'brain-fact');
        item.append(element('p', '', fact.excerpt));
        item.append(element('small', '', (fact.source_type === 'chat' ? 'Чат · ' : 'Файл · ') + fact.locator));
        detail.append(item);
      }
      await loadBrain();
    } catch (error) { message(error.message); }
  }
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