export function createConversationsPage({
  api, $, esc, number, date, ms, svg, avatarImage, userAvatar, empty, heading,
  keepDetails, pill, unfinished, toast, onOpenJob, sessionContext,
}) {
  const state = {
    items: [], selected: null, jobs: [], next: null, more: false, query: '',
    active: false, epoch: 0, searchEpoch: 0,
  };
  let searchTimer;

  async function fetchItems(append = false, query = state.query, epoch = state.epoch, searchEpoch = state.searchEpoch) {
    const offset = append ? state.items.length : 0;
    const result = await api(`/conversations?q=${encodeURIComponent(query)}&offset=${offset}`);
    if (!state.active || epoch !== state.epoch || searchEpoch !== state.searchEpoch || query !== state.query) return false;
    state.items = append ? [...state.items, ...result.items] : result.items;
    state.more = result.more;
    return true;
  }
  function list() {
    return state.items.map(item => `<button class="conversation-button ${state.selected === item.conversation ? 'selected' : ''}" data-action="conversation" data-id="${esc(item.conversation)}"><span class="conversation-avatar">${item.kind === 'group' ? svg('group') : userAvatar(item.target.user_id)}</span><span class="conversation-info"><span class="conversation-name">${esc(item.title)}</span><span class="conversation-preview">${esc(item.preview)}</span><span class="conversation-date">${date(item.updated)} · ${number(item.jobs)} 个任务</span></span></button>`).join('') || empty('没有找到匹配的会话');
  }
  function userBubble(message, supplement = false) {
    const attachments = message.attachments || [];
    return `<div class="chat-message chat-message-user" data-message-id="${esc(message.id)}"><span class="chat-avatar" aria-hidden="true">${userAvatar(message.target.user_id)}</span><div class="bubble-stack"><div class="bubble-author"><span>QQ ${esc(message.target.user_id)}</span>${supplement ? `<span>补充消息 · ${date(message.created)}</span>` : ''}</div><div class="chat-bubble user-bubble"><div class="message-text">${esc(message.text || '（附件消息）')}</div>${attachments.length ? `<div class="attachment-tags">${attachments.map(item => `<span class="pill">附件 · ${esc(item.name)}</span>`).join('')}</div>` : ''}</div></div></div>`;
  }
  function jobView(job) {
    const pending = unfinished.has(job.status);
    const text = job.result || (pending ? '正在处理，可展开查看实时响应和工具调用。' : '这一轮未保存最终正文，可查看 OpenCode 执行记录。');
    return `<article class="chat-turn" id="job-${esc(job.id)}" aria-label="任务 ${esc(job.id.slice(0, 8))} 的聊天记录"><div class="chat-turn-date">${date(job.created, true)}</div>${userBubble(job)}${(job.steers || []).map(item => userBubble(item, true)).join('')}<div class="chat-message chat-message-assistant"><span class="chat-avatar assistant-avatar" aria-hidden="true">${avatarImage('/assets/assistant-avatar.svg?v=public1')}</span><div class="bubble-stack"><div class="bubble-author">助手</div><div class="chat-bubble assistant-bubble"><div class="message-text ${job.result ? '' : 'muted'}">${esc(text)}</div>${job.error ? `<p class="error">${esc(job.error)}</p>` : ''}</div><div class="bubble-footer">${pill(job.status)}<span>执行计时 ${ms(job.elapsed * 1000)}</span><button class="text-button" data-action="job" data-id="${esc(job.id)}">执行详情 ${svg('open')}</button></div></div></div></article>`;
  }
  function feed() {
    const conversation = state.items.find(item => item.conversation === state.selected);
    return `<div class="feed-toolbar"><button class="text-button mobile-back" data-action="back-conversations">${svg('back')}返回会话列表</button><div class="feed-heading"><div><h2>${esc(conversation?.title || '会话记录')}</h2><p>你的消息在左，助手的回复在右</p></div><span class="pill">${number(state.jobs.length)} 个任务已加载</span></div>${sessionContext.render(conversation?.current_session_id)}</div><div class="chat-history" id="chat-history" tabindex="0" role="log" aria-label="聊天记录">${state.next ? `<button class="button small load-older" data-action="older-jobs">${svg('up')}加载更早记录</button>` : ''}${[...state.jobs].reverse().map(jobView).join('') || empty('这个会话暂无任务')}<div class="chat-end" id="chat-end" aria-hidden="true"></div></div><button class="button jump-latest" id="jump-latest" data-action="latest" hidden>${svg('latest')}最新消息</button>`;
  }
  function position() {
    const node = $('#chat-history');
    return node ? { top: node.scrollTop, height: node.scrollHeight, bottom: node.scrollHeight - node.scrollTop - node.clientHeight <= 64 } : null;
  }
  function updateLatest() {
    const p = position(); const button = $('#jump-latest');
    if (button) button.hidden = !p || p.bottom;
  }
  function restore(p, mode = 'preserve') {
    const node = $('#chat-history'); if (!node) return;
    if (mode === 'latest' || !p || (p.bottom && mode !== 'older')) node.scrollTop = node.scrollHeight;
    else node.scrollTop = p.top + (mode === 'older' ? node.scrollHeight - p.height : 0);
    updateLatest();
  }
  function update(mode = 'preserve') {
    const p = position();
    keepDetails($('#chat-feed'), feed()); restore(p, mode);
  }
  async function render() {
    state.active = true;
    const epoch = ++state.epoch;
    const searchEpoch = ++state.searchEpoch;
    await fetchItems(false, state.query, epoch, searchEpoch);
    if (!state.active || epoch !== state.epoch) return '';
    if (!state.selected && state.items.length && !matchMedia('(max-width:760px)').matches) state.selected = state.items[0].conversation;
    if (state.selected) {
      const selected = state.selected;
      const result = await api(`/jobs?conversation=${encodeURIComponent(selected)}`);
      if (!state.active || epoch !== state.epoch || selected !== state.selected) return null;
      if (state.jobs[0]?.conversation === state.selected) {
        const known = new Map(state.jobs.map(item => [item.id, item]));
        result.items.forEach(item => known.set(item.id, item));
        const cursor = state.next;
        state.jobs = [...known.values()].sort((a, b) => b.created - a.created || b.id.localeCompare(a.id));
        state.next = state.jobs.length > result.items.length ? cursor : result.next;
      } else { state.jobs = result.items; state.next = result.next; }
    }
    return heading('会话', '从聊天找到任务，无需消息 ID。') + `<div class="chat-layout ${state.selected ? 'has-selection' : ''}" id="chat-layout"><section class="conversation-panel"><div class="conversation-search"><input class="search" id="conversation-search" aria-label="搜索会话或聊天内容" placeholder="搜索 QQ、群号或聊天内容" value="${esc(state.query)}"></div><div class="conversation-list" id="conversation-list">${list()}</div><div id="conversation-more">${state.more ? '<button class="conversation-load" data-action="more-conversations">加载更多会话</button>' : ''}</div></section><section class="chat-feed" id="chat-feed">${state.selected ? feed() : empty('选择一个会话，查看聊天与执行记录')}</section></div>`;
  }
  async function select(id) {
    state.selected = id;
    const selected = state.selected;
    const epoch = state.epoch;
    const result = await api(`/jobs?conversation=${encodeURIComponent(selected)}`);
    if (!state.active || epoch !== state.epoch || selected !== state.selected || !$('#conversation-list')) return;
    state.jobs = result.items; state.next = result.next;
    $('#conversation-list').innerHTML = list(); $('#chat-layout').classList.add('has-selection'); update('latest');
    await sessionContext.refresh();
  }
  async function olderJobs() {
    const selected = state.selected, cursor = state.next, epoch = state.epoch;
    const result = await api(`/jobs?conversation=${encodeURIComponent(selected)}&before=${encodeURIComponent(cursor)}`);
    if (!state.active || epoch !== state.epoch || selected !== state.selected || cursor !== state.next) return;
    state.jobs.push(...result.items); state.next = result.next; update('older');
  }
  async function refresh() {
    if (!$('#conversation-search')) return;
    const query = state.query, epoch = state.epoch, searchEpoch = state.searchEpoch;
    const result = await api(`/conversations?q=${encodeURIComponent(query)}`);
    if (!state.active || epoch !== state.epoch || searchEpoch !== state.searchEpoch || query !== state.query || !$('#conversation-list')) return;
    const scroll = $('#conversation-list')?.scrollTop || 0;
    state.items = result.items; state.more = result.more;
    $('#conversation-list').innerHTML = list(); $('#conversation-list').scrollTop = scroll;
    if (state.selected) {
      const selected = state.selected;
      const jobs = await api(`/jobs?conversation=${encodeURIComponent(selected)}`);
      if (state.active && epoch === state.epoch && selected === state.selected && $('#chat-feed')) {
        const known = new Map(state.jobs.map(item => [item.id, item]));
        jobs.items.forEach(item => known.set(item.id, item));
        state.jobs = [...known.values()].sort((a, b) => b.created - a.created); update();
      }
    }
  }
  async function handleAction(action, button) {
    if (action === 'conversation') await select(button.dataset.id);
    else if (action === 'back-conversations') { state.selected = null; $('#chat-layout').classList.remove('has-selection'); }
    else if (action === 'more-conversations') {
      if (!await fetchItems(true) || !$('#conversation-list')) return true;
      $('#conversation-list').innerHTML = list();
      $('#conversation-more').innerHTML = state.more ? '<button class="conversation-load" data-action="more-conversations">加载更多会话</button>' : '';
    } else if (action === 'older-jobs') await olderJobs();
    else if (action === 'latest') restore(null, 'latest');
    else if (action === 'job') { await onOpenJob(button.dataset.id); }
    else return false;
    return true;
  }
  function handleInput(target) {
    if (target.id !== 'conversation-search') return false;
    state.query = target.value; clearTimeout(searchTimer);
    const epoch = state.epoch, searchEpoch = ++state.searchEpoch, query = state.query;
    searchTimer = setTimeout(async () => {
      try {
        await fetchItems(false, query, epoch, searchEpoch);
        if (state.active && epoch === state.epoch && searchEpoch === state.searchEpoch && query === state.query && $('#conversation-list')) {
          $('#conversation-list').innerHTML = list();
          $('#conversation-more').innerHTML = state.more ? '<button class="conversation-load" data-action="more-conversations">加载更多会话</button>' : '';
        }
      } catch (error) { toast(error.message); }
    }, 300);
    return true;
  }
  function leave() {
    state.active = false; state.epoch++; state.searchEpoch++;
    clearTimeout(searchTimer); searchTimer = null;
  }
  return { render, handleAction, handleInput, refresh, updateLatest, position, restore, leave };
}
