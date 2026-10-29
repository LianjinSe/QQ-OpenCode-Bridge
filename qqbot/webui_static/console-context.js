/* Context counts come from one measured response, independently of history pagination. */
export function createSessionContext({api, $, esc, number, date, dialog, toast}) {
  const records = new Map(), versions = new Map(), requestIds = new Map();
  const statusNames = {queued:'压缩排队中',running:'正在压缩',completed:'上次压缩已完成',failed:'上次压缩失败'};
  function content(id) {
    const data = records.get(id);
    const actions = `<div class="context-actions"><button class="text-button" data-action="session" data-id="${esc(id)}">完整会话</button><button class="button small" data-action="refresh-context" data-id="${esc(id)}">刷新</button>${data && !data.error ? `<button class="button small" data-action="compact-session" data-id="${esc(id)}" ${['queued','running'].includes(data.compaction?.status) ? 'disabled' : ''}>压缩上下文</button>` : ''}</div>`;
    if (!data || data.error) return `<div class="context-heading"><strong>上下文</strong>${actions}</div><p class="context-note" role="status">${esc(data?.error || '正在读取上下文用量…')}</p>`;
    const usage = data.used_tokens == null ? '等待新用量' : `${number(data.used_tokens)} / ${data.context_limit ? number(data.context_limit) : '上限未知'} Token`;
    const percent = data.percentage == null ? '' : `${number(data.percentage)}%`;
    const changedModel = data.usage_model && data.model && ['id','providerID'].some(key => data.usage_model[key] !== data.model[key]);
    return `<div class="context-heading"><strong>上下文 <span class="context-percent">${percent}</span></strong>${actions}</div>${data.title ? `<p class="context-session-title" title="${esc(data.title)}">${esc(data.title)}</p>` : ''}${data.percentage != null ? `<progress class="context-meter" max="100" value="${Math.min(100, Math.max(0, data.percentage))}" aria-label="上下文占用 ${esc(percent)}"></progress>` : ''}<div class="context-summary"><span>${esc(usage)}</span>${data.compaction ? `<span class="pill ${data.compaction.status === 'failed' ? 'bad' : ''}" role="status">${esc(statusNames[data.compaction.status] || data.compaction.status)}</span>` : ''}</div><details class="context-explanation"><summary>最近一次调用估算${data.model ? ` · ${esc(data.model.id)}` : ''}</summary><p class="context-note">${data.used_tokens == null ? '当前上下文尚无有效用量记录；压缩后需等待新的模型调用再显示。' : `输入（含缓存）${number(data.input_tokens)}，输出（含思考）${number(data.output_tokens)} Token。${data.measured_at ? `记录于 ${date(data.measured_at / 1000)}。` : ''}尚未计入之后的新消息和工具结果。`}${changedModel ? ' 当前模型已更换，用量来自之前的模型，仅供参考。' : ''}这不是历史累计消耗，也不代表自动压缩阈值。</p></details>`;
  }
  function render(id) {
    return id ? `<section class="session-context" data-context-id="${esc(id)}" aria-label="会话上下文">${content(id)}</section>` : '';
  }
  function paint(id) {
    document.querySelectorAll('#qqbot-console [data-context-id]').forEach(node => {
      if (node.dataset.contextId !== id) return;
      const opened = node.querySelector('details')?.open;
      node.innerHTML = content(id);
      if (opened && node.querySelector('details')) node.querySelector('details').open = true;
    });
  }
  async function load(id) {
    const version = (versions.get(id) || 0) + 1; versions.set(id, version);
    try {
      const data = await api(`/sessions/${encodeURIComponent(id)}/context`);
      if (versions.get(id) !== version) return;
      records.set(id, data);
      if (['completed','failed'].includes(data.compaction?.status) && data.compaction.id === requestIds.get(id)) requestIds.delete(id);
    } catch (error) {
      if (versions.get(id) !== version) return;
      records.set(id, {error:error.message});
    }
    paint(id);
  }
  async function refresh() {
    const ids = new Set([...document.querySelectorAll('#qqbot-console [data-context-id]')].map(node => node.dataset.contextId));
    await Promise.all([...ids].map(load));
  }
  async function handleAction(action, button) {
    const id = button.dataset.id;
    if (action === 'refresh-context') await load(id);
    else if (action === 'compact-session') {
      dialog(`<h2 id="action-title">压缩会话上下文？</h2><p>OpenCode 会调用模型生成摘要，可能产生 API 费用。摘要可能省略细节，原始历史记录仍然保留。<br><br>请在这个聊天的任务全部结束后操作；压缩只作用于所选会话。</p><div class="dialog-actions"><button class="button" data-action="close-action">取消</button><button class="primary" data-action="confirm-compact" data-id="${esc(id)}">确认压缩</button></div>`);
    } else if (action === 'confirm-compact') {
      button.disabled = true;
      if (!requestIds.has(id)) requestIds.set(id, `msg_${crypto.randomUUID().replaceAll('-', '')}`);
      const receipt = await api(`/sessions/${encodeURIComponent(id)}/compact`, {confirm:'compact', request_id:requestIds.get(id)});
      requestIds.set(id, receipt.id);
      $('#action-dialog').close(); toast('压缩请求已受理，正在等待 OpenCode 处理'); await load(id);
    } else return false;
    return true;
  }
  function clear() { records.clear(); versions.forEach((value, id) => versions.set(id, value + 1)); }
  return {render, refresh, handleAction, clear};
}

export function createSessionTools({api, $, esc, dialog, toast, onChanged, onAuthLost}) {
  let current = null, version = 0;
  const variantName = id => ({default:'默认档位',none:'不启用思考',minimal:'最低',low:'低',medium:'中',high:'高',xhigh:'很高',max:'最高'})[id] || id;
  function variantOptions(model, selected = 'default') {
    return [...new Set(['default', ...(model?.variants || [])])].map(id => `<option value="${esc(id)}" ${id === selected ? 'selected' : ''}>${esc(variantName(id))} · ${esc(id)}</option>`).join('');
  }
  async function open(id, mode) {
    const epoch = ++version;
    current = null;
    if (mode === 'export') {
      dialog(`<h2 id="action-title">导出会话</h2><p>正文导出包含用户和助手文字。完整 JSON 还包含脱敏的工具与思考记录，不包含附件原件。</p><form id="session-export-form" data-id="${esc(id)}"><label>导出内容<select name="choice"><option value="markdown:text">正文 · Markdown</option><option value="json:text">正文 · JSON</option><option value="json:full">完整记录 · 脱敏 JSON</option></select></label><p id="session-tools-error" class="error" role="alert"></p><div class="dialog-actions"><button class="button" type="button" data-action="close-action">取消</button><button class="primary" type="submit">下载</button></div></form>`);
      return;
    }
    dialog('<h2 id="action-title">读取会话设置</h2><p role="status">正在读取…</p><button class="button" data-action="close-action">取消</button>');
    const data = await api(`/sessions/${encodeURIComponent(id)}/settings`);
    if (epoch !== version || !$('#action-dialog').open) return;
    current = {id, data, mode};
    const actions = '<p id="session-tools-error" class="error" role="alert"></p><div class="dialog-actions"><button class="button" type="button" data-action="close-action">取消</button><button class="primary" type="submit">保存</button></div>';
    if (mode === 'model') {
      const selected = data.models.findIndex(m => m.id === data.model?.id && m.providerID === data.model?.providerID);
      const index = selected;
      dialog(`<h2 id="action-title">模型与思考档位</h2><p>设置对所选 OpenCode 会话的后续响应生效。思考档位来自供应商实际提供的选项。${data.scope === 'group_shared' ? '当前是群共享会话，主人的群聊私密独立会话需分别设置。' : ''}</p><form id="session-model-form" data-id="${esc(id)}"><label>模型<select name="model" id="session-model" required>${index < 0 ? '<option value="" selected>当前模型不在可用目录中，请选择模型</option>' : ''}${data.models.map((m, i) => `<option value="${i}" ${i === index ? 'selected' : ''}>${esc(m.providerID)} / ${esc(m.name || m.id)}</option>`).join('')}</select></label><label>思考档位<select name="variant" id="session-variant">${variantOptions(data.models[index], data.model?.variant || 'default')}</select></label>${actions}</form>`);
    } else if (mode === 'rename') {
      dialog(`<h2 id="action-title">重命名会话</h2><form id="session-properties-form" data-id="${esc(id)}"><label>名称<input name="title" value="${esc(data.title)}" required maxlength="120" autocomplete="off"></label>${actions}</form>`);
    } else {
      dialog(`<h2 id="action-title">${data.archived ? '恢复归档会话' : '归档会话'}？</h2><p>${esc(data.title)}。${data.current ? '请先切换到其他会话，再归档当前会话。' : data.archived ? '恢复后可在分支列表中继续选择这个会话。' : '归档会收起这条会话，历史记录保留，可随时恢复。'}</p><form id="session-properties-form" data-id="${esc(id)}"><input name="archived" type="hidden" value="${!data.archived}"><p id="session-tools-error" class="error" role="alert"></p><div class="dialog-actions"><button class="button" type="button" data-action="close-action">取消</button><button class="primary" type="submit" ${data.current && !data.archived ? 'disabled' : ''}>${data.archived ? '恢复' : '归档'}</button></div></form>`);
    }
  }
  async function handleAction(action, button) {
    const modes = {'session-model':'model','session-rename':'rename','session-archive':'archive','session-export':'export'};
    if (!modes[action]) return false;
    await open(button.dataset.id, modes[action]); return true;
  }
  function handleChange(target) {
    if (target.id !== 'session-model' || !current) return false;
    $('#session-variant').innerHTML = variantOptions(current.data.models[Number(target.value)]);
    return true;
  }
  async function handleSubmit(event) {
    const form = event.target;
    if (!['session-model-form','session-properties-form','session-export-form'].includes(form.id)) return;
    event.preventDefault(); const button = form.querySelector('[type=submit]'); button.disabled = true;
    try {
      const values = Object.fromEntries(new FormData(form)); const id = form.dataset.id;
      if (form.id === 'session-export-form') {
        const [format, scope] = values.choice.split(':');
        const response = await fetch(`/api/sessions/${encodeURIComponent(id)}/export?format=${format}&scope=${scope}`, {credentials:'same-origin',cache:'no-store'});
        if (!response.ok) { if (response.status === 401) onAuthLost(); const error = await response.json().catch(() => ({})); throw new Error(error.error || '导出未完成，请稍后重试'); }
        const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = document.createElement('a');
        link.href = url; link.download = `session-${scope}.${format === 'markdown' ? 'md' : 'json'}`; link.hidden = true;
        $('#action-content').append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 5000);
        $('#action-dialog').close(); toast('导出文件已准备下载'); return;
      }
      if (!current || current.id !== id) throw new Error('会话设置已过期，请重新打开');
      const {data} = current;
      if (form.id === 'session-model-form') {
        const model = data.models[Number(values.model)]; if (!model || values.model === '') throw new Error('请选择模型');
        await api(`/sessions/${encodeURIComponent(id)}/model`, {confirm:'model',expected_current:data.expected_current,expected_model:data.selection,model:{id:model.id,providerID:model.providerID,variant:values.variant}});
      } else {
        await api(`/sessions/${encodeURIComponent(id)}/properties`, {confirm:'properties',expected_current:data.expected_current,...('archived' in values ? {archived:values.archived === 'true'} : {title:values.title})});
      }
      $('#action-dialog').close(); toast('会话设置已保存'); await onChanged(id);
    } catch (error) { const node = $('#session-tools-error'); if (node) node.textContent = error.message; }
    finally { button.disabled = false; }
  }
  function clear() { current = null; version++; }
  $('#action-dialog').addEventListener('close', clear);
  return {handleAction, handleChange, handleSubmit, clear};
}
