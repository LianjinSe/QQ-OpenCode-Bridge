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
    return `<div class="context-heading"><strong>上下文 <span class="context-percent">${percent}</span></strong>${actions}</div>${data.percentage != null ? `<progress class="context-meter" max="100" value="${Math.min(100, Math.max(0, data.percentage))}" aria-label="上下文占用 ${esc(percent)}"></progress>` : ''}<div class="context-summary"><span>${esc(usage)}</span>${data.compaction ? `<span class="pill ${data.compaction.status === 'failed' ? 'bad' : ''}" role="status">${esc(statusNames[data.compaction.status] || data.compaction.status)}</span>` : ''}</div><details class="context-explanation"><summary>最近一次调用估算${data.model ? ` · ${esc(data.model.id)}` : ''}</summary><p class="context-note">${data.used_tokens == null ? '当前上下文尚无有效用量记录；压缩后需等待新的模型调用再显示。' : `输入（含缓存）${number(data.input_tokens)}，输出（含思考）${number(data.output_tokens)} Token。${data.measured_at ? `记录于 ${date(data.measured_at / 1000)}。` : ''}尚未计入之后的新消息和工具结果。`}${changedModel ? ' 当前模型已更换，用量来自之前的模型，仅供参考。' : ''}这不是历史累计消耗，也不代表自动压缩阈值。</p></details>`;
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
