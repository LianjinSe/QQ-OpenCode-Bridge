export function createKnowledgePage({
  api, $, esc, date, ms, svg, empty, heading, dialog, toast, navigate, clearDetail, onOpenJob,
}) {
  const state = {
    data: null, library: null, documents: [], query: '', result: null,
    pendingDocument: null, active: false, epoch: 0, searchEpoch: 0,
  };

  function stateName(version) {
    if (!version) return '尚未导入';
    if (version.state === 'processing') return ({ parsing: '正在解析', splitting: '正在分段', indexing: '正在建立索引' })[version.stage] || '处理中';
    return ({ queued: '等待处理', ready: '可用', failed: '导入失败', deleting: '清理中', deleted: '已清理' })[version.state] || version.state;
  }
  function libraryDialog(id = null) {
    const lib = state.data.libraries.find(item => item.id === id);
    dialog(`<h2 id="action-title">${lib ? '编辑资料库' : '新建资料库'}</h2><form id="knowledge-library-form" data-id="${esc(id || '')}"><label>名称<input name="name" required maxlength="80" value="${esc(lib?.name || '')}" placeholder="例如：项目资料"></label><label>用途说明<textarea name="description" rows="3" maxlength="500" placeholder="这份资料适合回答哪些问题">${esc(lib?.description || '')}</textarea></label><fieldset class="knowledge-groups"><legend>允许检索的群聊</legend><p class="form-hint">默认仅主人私聊可用。选中后，该群所有成员均可通过机器人检索。</p>${state.data.groups.map(group => `<label class="knowledge-group"><input type="checkbox" name="group" value="${group}" ${lib?.groups.includes(group) ? 'checked' : ''}>群 ${group}</label>`).join('') || '<p class="muted">尚未配置授权群聊。</p>'}</fieldset><p class="error" id="knowledge-form-error" role="alert"></p><div class="dialog-actions"><button class="button" type="button" data-action="close-action">取消</button><button class="primary" type="submit">保存</button></div></form>`);
  }
  function documentRows() {
    return state.documents.map(doc => {
      const target = doc.versions.find(version => version.id === doc.target_version);
      const active = doc.versions.find(version => version.id === doc.active_version);
      const waiting = target && ['queued', 'processing'].includes(target.state);
      return `<article class="knowledge-document"><div class="knowledge-document-title"><span class="status-symbol">${svg('attachment')}</span><div><h3>${esc(doc.filename)}</h3><p>${target ? `第 ${target.number} 版 · ${(target.bytes / 1024).toFixed(1)} KiB` : ''} · ${date(doc.updated)}</p></div><span class="pill ${target?.state === 'ready' ? 'good' : target?.state === 'failed' ? 'bad' : 'warm'}">${stateName(target)}</span></div>${active && active.id !== target?.id ? `<p class="form-hint">第 ${active.number} 版继续提供检索；新版本就绪后替换。</p>` : ''}${target?.error ? `<p class="error">${esc(target.error)}${waiting ? '，后台将重试。' : ''}</p>` : ''}<div class="knowledge-document-actions">${active ? `<button class="button small" data-action="knowledge-document" data-id="${doc.id}">${svg('view')}预览正文</button><a class="button small" href="/api/knowledge/documents/${doc.id}/download" download>${svg('attachment')}原文件</a>` : ''}${target?.state === 'failed' ? `<button class="button small" data-action="knowledge-retry" data-id="${doc.id}">${svg('refresh')}重试</button>` : ''}<button class="text-button" data-action="knowledge-delete" data-id="${doc.id}">${svg('close')}删除</button></div></article>`;
    }).join('') || empty('上传第一份文档，让她有资料可查。', 'knowledge');
  }
  function resultsView(result) {
    if (!result) return '<p class="intro-note">试着输入你会在 QQ 中问的问题，查看能否找到对应原文。</p>';
    const modes = result.mode.startsWith('keyword_only') ? '关键词检索（语义服务暂不可用）' : result.mode === 'empty' ? '尚无可用文档' : result.mode.includes('rerank_unavailable') ? '混合检索，重排暂不可用' : result.mode.includes('rerank') ? '混合检索与重排' : '混合检索';
    return `<p class="form-hint">${modes} · ${ms(result.elapsed_ms)} · ${result.items.length} 个片段</p>${result.items.map((item, index) => `<article class="knowledge-hit"><div class="knowledge-hit-title"><span class="pill">${index + 1}</span><button class="text-button" data-action="knowledge-document" data-id="${item.document_id}">${esc(item.citation)} ${svg('open')}</button></div><div class="knowledge-excerpt">${esc(item.text)}</div></article>`).join('') || empty('没有找到相关片段。可以换一种问法，或检查文档是否已可用。', 'knowledge')}`;
  }
  async function render() {
    state.active = true;
    const epoch = ++state.epoch;
    state.searchEpoch++;
    const data = await api('/knowledge');
    if (!state.active || epoch !== state.epoch) return '';
    state.data = data;
    if (!data.enabled) return heading('资料与知识', '把值得反复查阅的资料，放在一个地方。') + '<div class="notice">知识库尚未启用，请按部署说明配置 KNOWLEDGE_ENABLED。</div>';
    if (state.pendingDocument) {
      const page = await api(`/knowledge/documents/${state.pendingDocument}`);
      if (!state.active || epoch !== state.epoch) return '';
      state.library = page.document.library_id;
    }
    if (!data.libraries.some(item => item.id === state.library)) state.library = data.libraries[0]?.id || null;
    const library = data.libraries.find(item => item.id === state.library);
    const documents = library ? (await api(`/knowledge/libraries/${library.id}`)).documents : [];
    if (!state.active || epoch !== state.epoch) return '';
    state.documents = documents;
    const history = data.history.map(row => `<details class="run-detail"><summary>${esc(row.query)} <small>${date(row.created)} · ${ms(row.elapsed_ms)}</small></summary><div class="run-detail-body">${row.job_id ? `<button class="text-button" data-action="job" data-id="${esc(row.job_id)}">查看对应聊天任务 ${svg('open')}</button>` : '<p class="muted">管理台检索测试</p>'}${row.sources.map(source => `<p><button class="text-button" data-action="knowledge-document" data-id="${source.document_id}">${esc(source.filename)} · 第 ${source.version} 版</button></p>`).join('') || '<p class="muted">没有当前可读取的来源。</p>'}</div></details>`).join('');
    return heading('资料与知识', '读过的资料有出处，用过的知识可追溯。', `<button class="primary" data-action="knowledge-new">${svg('knowledge')}新建资料库</button>`) + `${data.error ? `<div class="notice">${esc(data.error)}</div>` : ''}<div class="knowledge-layout"><aside class="knowledge-libraries"><div class="section-caption">资料库 <span>${data.libraries.length}</span></div>${data.libraries.map(item => `<button class="knowledge-library ${library?.id === item.id ? 'selected' : ''}" data-action="knowledge-library" data-id="${item.id}"><span>${svg('knowledge')}<strong>${esc(item.name)}</strong></span><p>${esc(item.description || '尚未添加用途说明')}</p><small>${item.documents} 份文档 · ${item.groups.length ? `${item.groups.length} 个群聊可用` : '仅主人私聊'}</small></button>`).join('') || '<p class="intro-note">先新建一个资料库，例如项目资料或学习笔记。</p>'}</aside><div class="knowledge-main">${library ? `<section class="panel"><div class="panel-heading"><div><h3>${esc(library.name)}</h3><p class="form-hint">${library.groups.length ? `主人私聊及群 ${library.groups.join('、')} 可检索` : '仅主人私聊可检索'}</p></div><button class="icon-button" data-action="knowledge-edit" data-id="${library.id}" aria-label="编辑资料库" title="编辑资料库">${svg('system')}</button></div><div class="panel-body"><form id="knowledge-upload-form" class="knowledge-upload"><label class="knowledge-file-picker" for="knowledge-files">${svg('attachment')}选择文档<input id="knowledge-files" class="sr-only" name="files" type="file" accept=".md,.markdown,.txt,.pdf" multiple required></label><span id="knowledge-file-selection" class="form-hint" aria-live="polite">尚未选择文档，可一次选择多份</span><p class="form-hint">Markdown、TXT、文字型 PDF；每份不超过 10 MiB。同名上传会建立新版本，当前版本保持可用。</p><button type="submit" class="button">${svg('next')}开始导入</button><span id="knowledge-upload-status" class="form-hint" role="status"></span></form><div id="knowledge-documents">${documentRows()}</div><div class="knowledge-library-footer"><button class="text-button" data-action="knowledge-delete-library" data-id="${library.id}">${svg('close')}删除这个资料库</button></div></div></section><section class="panel"><div class="panel-heading"><h3>检索测试</h3><small>只查资料，不生成回答</small></div><div class="panel-body"><form id="knowledge-search-form" class="knowledge-search"><label class="sr-only" for="knowledge-query">检索问题</label><input id="knowledge-query" name="query" class="search" required maxlength="500" placeholder="例如：更新服务前需要做什么？" value="${esc(state.query)}" enterkeyhint="search"><button type="submit" class="primary">${svg('view')}检索</button></form><div id="knowledge-search-results" aria-live="polite">${resultsView(state.result)}</div></div></section>` : `<section class="panel"><div class="panel-body">${empty('资料、检索与引用，从第一份文档开始。', 'knowledge')}<button class="primary" data-action="knowledge-new">新建资料库</button></div></section>`}<section class="panel"><div class="panel-heading"><h3>最近的资料检索</h3><small>保留 7 天，最多显示 20 次</small></div><div class="panel-body">${history || '<p class="intro-note">她在 QQ 中查过的资料和这里的检索测试，会显示在这里。</p>'}</div></section></div></div>`;
  }
  async function openDocument(id, offset = 0) {
    clearDetail();
    const epoch = state.epoch;
    const page = await api(`/knowledge/documents/${encodeURIComponent(id)}?offset=${offset}`);
    if (!state.active || epoch !== state.epoch || !$('#detail-content')) return;
    $('#detail-eyebrow').textContent = 'KNOWLEDGE SOURCE'; $('#detail-title').textContent = page.document.filename;
    const chunks = page.chunks.map(chunk => `<article class="knowledge-hit"><p class="form-hint">片段 ${chunk.position + 1}${chunk.page ? ` · 第 ${chunk.page} 页` : chunk.heading ? ` · ${esc(chunk.heading)}` : ''}</p><div class="knowledge-excerpt">${esc(chunk.text)}</div></article>`).join('');
    if (!offset) $('#detail-content').innerHTML = `<p class="detail-note">当前可用版本的解析正文。文档内容作为资料展示，引用以原文为准。</p><div id="knowledge-preview-chunks">${chunks || empty('文档仍在处理，尚无可预览的正文。', 'knowledge')}</div><div id="knowledge-preview-more"></div>`;
    else $('#knowledge-preview-chunks').insertAdjacentHTML('beforeend', chunks);
    $('#knowledge-preview-more').innerHTML = page.more ? `<button class="button" data-action="knowledge-more" data-id="${id}" data-offset="${offset + 50}">继续读取 ${svg('next')}</button>` : '';
    if (!$('#detail-dialog').open) $('#detail-dialog').showModal();
  }
  async function handleAction(action, button) {
    const id = button.dataset.id;
    if (action === 'knowledge-new') libraryDialog();
    else if (action === 'knowledge-edit') libraryDialog(id);
    else if (action === 'knowledge-library') { state.library = id; state.result = null; state.searchEpoch++; await navigate('knowledge', true); }
    else if (action === 'knowledge-document') await openDocument(id);
    else if (action === 'knowledge-more') await openDocument(id, Number(button.dataset.offset));
    else if (action === 'knowledge-retry') { button.disabled = true; await api(`/knowledge/documents/${id}/retry`, {}); await navigate('knowledge', true); }
    else if (action === 'knowledge-delete' || action === 'knowledge-delete-library') {
      const library = action.endsWith('library');
      dialog(`<h2 id="action-title">${library ? '删除整个资料库？' : '删除这份文档？'}</h2><p>将立即停止检索${library ? '库内所有文档' : '这份文档'}，并在后台清理原文件和向量索引。已有聊天回复仍会保留。</p><div class="dialog-actions"><button class="button" data-action="close-action">取消</button><button class="danger" data-action="knowledge-confirm-delete" data-kind="${library ? 'libraries' : 'documents'}" data-id="${id}">确认删除</button></div>`);
    } else if (action === 'knowledge-confirm-delete') {
      button.disabled = true; await api(`/knowledge/${button.dataset.kind}/${id}/delete`, { confirm: 'delete' });
      $('#action-dialog').close(); state.result = null; await navigate('knowledge', true); toast('已停止检索，后台正在清理原文件和索引');
    } else if (action === 'job') { await onOpenJob(id); return true; }
    else return false;
    return true;
  }
  async function handleSubmit(event) {
    const form = event.target;
    if (!['knowledge-library-form', 'knowledge-upload-form', 'knowledge-search-form'].includes(form.id)) return false;
    event.preventDefault(); const button = form.querySelector('[type=submit]'); button.disabled = true;
    const epoch = state.epoch;
    try {
      const values = new FormData(form);
      if (form.id === 'knowledge-library-form') {
        const result = await api(`/knowledge/libraries${form.dataset.id ? '/' + form.dataset.id : ''}`, { name: values.get('name'), description: values.get('description'), groups: values.getAll('group').map(Number) });
        if (!state.active || epoch !== state.epoch) return true;
        state.library = result.id; $('#action-dialog').close(); await navigate('knowledge', true);
      } else if (form.id === 'knowledge-upload-form') {
        const files = [...form.elements.files.files], library = state.library;
        for (let index = 0; index < files.length; index++) {
          $('#knowledge-upload-status').textContent = `正在上传 ${index + 1}/${files.length}：${files[index].name}`;
          if (files[index].size > 10 * 1024 * 1024) throw new Error('单份文档不能超过 10 MiB');
          const body = new FormData(); body.append('file', files[index]);
          await api(`/knowledge/libraries/${library}/documents`, body);
          if (!state.active || epoch !== state.epoch) return true;
        }
        await navigate('knowledge', true); toast('文档已保存，正在后台解析和建立索引');
      } else {
        state.query = values.get('query');
        const query = state.query, library = state.library, searchEpoch = ++state.searchEpoch;
        $('#knowledge-search-results').innerHTML = '<p class="intro-note" role="status">正在查找相关原文…</p>';
        const result = await api('/knowledge/search', { query, library_id: library });
        if (!state.active || epoch !== state.epoch || searchEpoch !== state.searchEpoch || query !== state.query || library !== state.library) return true;
        state.result = result;
        if ($('#knowledge-search-results')) $('#knowledge-search-results').innerHTML = resultsView(state.result);
      }
    } catch (error) {
      const node = $('#knowledge-form-error');
      if (node && form.id === 'knowledge-library-form') node.textContent = error.message;
      else toast(error.message);
    } finally { button.disabled = false; }
    return true;
  }
  function handleChange(target) {
    if (target.id !== 'knowledge-files') return false;
    $('#knowledge-file-selection').textContent = [...target.files].map(file => file.name).join('、') || '尚未选择文档，可一次选择多份';
    return true;
  }
  async function refresh() {
    if (!state.documents.some(doc => doc.versions.some(version => ['queued', 'processing'].includes(version.state)))) return;
    const selected = state.library, epoch = state.epoch;
    const result = await api(`/knowledge/libraries/${selected}`);
    if (state.active && epoch === state.epoch && $('#knowledge-documents') && selected === state.library) {
      state.documents = result.documents; $('#knowledge-documents').innerHTML = documentRows();
    }
  }
  async function openPendingDocument() {
    const id = state.pendingDocument; state.pendingDocument = null;
    if (id) await openDocument(id);
  }
  function setPendingDocument(id) { state.pendingDocument = id; }
  function leave() { state.active = false; state.epoch++; state.searchEpoch++; }
  return { render, handleAction, handleSubmit, handleChange, refresh, openPendingDocument, setPendingDocument, leave };
}
