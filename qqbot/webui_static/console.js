/* The console renders only escaped text. Model output never becomes executable HTML. */
'use strict';
import { createConversationsPage } from './console-conversations.js';
import { createKnowledgePage } from './console-knowledge.js';
const state = {
  auth: null, view: 'overview', overview: null, memoryQuery: '', memoryKind: '',
  memorySubject: '', memoryOffset: 0, memoryTotal: 0, memories: [], queueHistory: false,
  queueBefore: null, queueItems: [], queueNext: null, detailJob: null, detailSession: null,
  detailData: null, detailTab: 'run', detailVersion: 0, viewVersion: 0, refreshing: false,
  restarting: null, sessionIndex: null, sessionQuery: '', sidebarCollapsed: loadSidebarPreference(),
};
const uiRoot = document.getElementById('qqbot-console');
const $ = (selector, root = uiRoot) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = value => new Intl.NumberFormat('zh-CN').format(value || 0);
const date = (value, full = false) => value ? new Date(value * 1000).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',...(full ? {year:'numeric',second:'2-digit'} : {})}) : '未记录';
const ms = value => value == null ? '未记录' : value < 1000 ? `${Math.round(value)} ms` : value < 60000 ? `${(value / 1000).toFixed(1)} s` : `${Math.floor(value / 60000)} 分 ${Math.round(value % 60000 / 1000)} 秒`;
const json = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
const names = {overview:'概览',conversations:'会话',sessions:'会话映射',queue:'任务队列',memories:'记忆库',knowledge:'知识库',system:'系统管理'};
// Lucide icons (ISC); source and licence are bundled with the console.
const icons = {
  knowledge: '<path d="M12 7v14M3 3h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5v16h-5a4 4 0 0 0-4 2 4 4 0 0 0-4-2H3z"/>',
  "overview": "<rect width=\"7\" height=\"9\" x=\"3\" y=\"3\" rx=\"1\" />\n  <rect width=\"7\" height=\"5\" x=\"14\" y=\"3\" rx=\"1\" />\n  <rect width=\"7\" height=\"9\" x=\"14\" y=\"12\" rx=\"1\" />\n  <rect width=\"7\" height=\"5\" x=\"3\" y=\"16\" rx=\"1\" />",
  "conversations": "<path d=\"M16 10a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 14.286V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z\" />\n  <path d=\"M20 9a2 2 0 0 1 2 2v10.286a.71.71 0 0 1-1.212.502l-2.202-2.202A2 2 0 0 0 17.172 19H10a2 2 0 0 1-2-2v-1\" />",
  "queue": "<path d=\"M13 5h8\" />\n  <path d=\"M13 12h8\" />\n  <path d=\"M13 19h8\" />\n  <path d=\"m3 17 2 2 4-4\" />\n  <rect x=\"3\" y=\"4\" width=\"6\" height=\"6\" rx=\"1\" />",
  "sessions": "<rect width=\"8\" height=\"8\" x=\"3\" y=\"3\" rx=\"2\" />\n  <path d=\"M7 11v4a2 2 0 0 0 2 2h4\" />\n  <rect width=\"8\" height=\"8\" x=\"13\" y=\"13\" rx=\"2\" />",
  "memories": "<path d=\"M12 18V5\" />\n  <path d=\"M15 13a4.17 4.17 0 01-3-4 4.17 4.17 0 01-3 4\" />\n  <path d=\"M17.707 6.294A3 3 0 1012 5a3 3 0 10-5.707 1.294\" />\n  <path d=\"M17.996 5.125a4 4 0 012.526 5.77\" />\n  <path d=\"M18 18a4 4 0 002-7.465\" />\n  <path d=\"M19.967 17.482a4 4 0 11-7.967.517 4 4 0 11-7.967-.517\" />\n  <path d=\"M6 18a4 4 0 01-2-7.465\" />\n  <path d=\"M6.004 5.125a4 4 0 00-2.526 5.77\" />",
  "system": "<path d=\"M14 17H5\" />\n  <path d=\"M19 7h-9\" />\n  <circle cx=\"17\" cy=\"17\" r=\"3\" />\n  <circle cx=\"7\" cy=\"7\" r=\"3\" />",
  "menu": "<path d=\"M4 5h16\" />\n  <path d=\"M4 12h16\" />\n  <path d=\"M4 19h16\" />",
  "close": "<path d=\"M18 6 6 18\" />\n  <path d=\"m6 6 12 12\" />",
  "collapse": "<rect width=\"18\" height=\"18\" x=\"3\" y=\"3\" rx=\"2\" />\n  <path d=\"M9 3v18\" />\n  <path d=\"m16 15-3-3 3-3\" />",
  "expand": "<rect width=\"18\" height=\"18\" x=\"3\" y=\"3\" rx=\"2\" />\n  <path d=\"M9 3v18\" />\n  <path d=\"m14 9 3 3-3 3\" />",
  "refresh": "<path d=\"M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8\" />\n  <path d=\"M21 3v5h-5\" />\n  <path d=\"M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16\" />\n  <path d=\"M8 16H3v5\" />",
  "open": "<path d=\"M7 7h10v10\" />\n  <path d=\"M7 17 17 7\" />",
  "back": "<path d=\"m12 19-7-7 7-7\" />\n  <path d=\"M19 12H5\" />",
  "up": "<path d=\"m5 12 7-7 7 7\" />\n  <path d=\"M12 19V5\" />",
  "latest": "<path d=\"m7 6 5 5 5-5\" />\n  <path d=\"m7 13 5 5 5-5\" />",
  "chevron": "<path d=\"m9 18 6-6-6-6\" />",
  "logout": "<path d=\"m16 17 5-5-5-5\" />\n  <path d=\"M21 12H9\" />\n  <path d=\"M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4\" />",
  "user": "<circle cx=\"12\" cy=\"8\" r=\"5\" />\n  <path d=\"M20 21a8 8 0 0 0-16 0\" />",
  "group": "<path d=\"M18 21a8 8 0 0 0-16 0\" />\n  <circle cx=\"10\" cy=\"8\" r=\"5\" />\n  <path d=\"M22 20c0-3.37-2-6.5-4-8a5 5 0 0 0-.45-8.3\" />",
  "model": "<path d=\"m10 9-3 3 3 3\" />\n  <path d=\"m14 15 3-3-3-3\" />\n  <rect x=\"3\" y=\"3\" width=\"18\" height=\"18\" rx=\"2\" />",
  "database": "<ellipse cx=\"12\" cy=\"5\" rx=\"9\" ry=\"3\" />\n  <path d=\"M3 5V19A9 3 0 0 0 21 19V5\" />\n  <path d=\"M3 12A9 3 0 0 0 21 12\" />",
  "server": "<rect width=\"20\" height=\"8\" x=\"2\" y=\"2\" rx=\"2\" ry=\"2\" />\n  <rect width=\"20\" height=\"8\" x=\"2\" y=\"14\" rx=\"2\" ry=\"2\" />\n  <line x1=\"6\" x2=\"6.01\" y1=\"6\" y2=\"6\" />\n  <line x1=\"6\" x2=\"6.01\" y1=\"18\" y2=\"18\" />",
  "check": "<circle cx=\"12\" cy=\"12\" r=\"10\" />\n  <path d=\"m16 9-5.5 5.5L8 12\" />",
  "alert": "<circle cx=\"12\" cy=\"12\" r=\"10\" />\n  <line x1=\"12\" x2=\"12\" y1=\"8\" y2=\"12\" />\n  <line x1=\"12\" x2=\"12.01\" y1=\"16\" y2=\"16\" />",
  "attachment": "<path d=\"m16 6-8.414 8.586a2 2 0 0 0 2.829 2.829l8.414-8.586a4 4 0 1 0-5.657-5.657l-8.379 8.551a6 6 0 1 0 8.485 8.485l8.379-8.551\" />",
  "clock": "<circle cx=\"12\" cy=\"12\" r=\"10\" />\n  <path d=\"M12 6v6h4\" />",
  "view": "<path d=\"M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0\" />\n  <circle cx=\"12\" cy=\"12\" r=\"3\" />",
  "signal": "<path d=\"M16.247 7.761a6 6 0 0 1 0 8.478\" />\n  <path d=\"M19.075 4.933a10 10 0 0 1 0 14.134\" />\n  <path d=\"M4.925 19.067a10 10 0 0 1 0-14.134\" />\n  <path d=\"M7.753 16.239a6 6 0 0 1 0-8.478\" />\n  <circle cx=\"12\" cy=\"12\" r=\"2\" />",
  "next": "<path d=\"M5 12h14\" />\n  <path d=\"m12 5 7 7-7 7\" />"
};
const svg = key => `<svg class="ui-icon" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${icons[key] || ''}</svg>`;
const USER_AVATAR = '/assets/favicon.svg?v=69cf9a0949';
const ASSISTANT_AVATAR = '/assets/assistant-avatar.svg?v=public1';
function fillIcons(root = uiRoot) { root.querySelectorAll('[data-icon]').forEach(node => { node.innerHTML = svg(node.dataset.icon); }); }
function avatarImage(source) { return `<img class="avatar-image" src="${source}" alt="" width="36" height="36">`; }
function userAvatar(userId) { return Number(userId) === Number(state.auth?.admin_user_id) ? avatarImage(USER_AVATAR) : svg('user'); }
function loadSidebarPreference() { try { return localStorage.getItem('qqbot-sidebar-collapsed') === '1'; } catch { return false; } }
function setMenu(open) {
  const visible = open && matchMedia('(max-width:760px)').matches;
  $('#sidebar').classList.toggle('open',visible); $('#nav-scrim').hidden = !visible;
  uiRoot.querySelectorAll('[data-action="menu"]').forEach(button => button.setAttribute('aria-expanded',String(visible)));
}
function renderSidebarState() {
  const mobile = matchMedia('(max-width:760px)').matches;
  uiRoot.classList.toggle('sidebar-collapsed',state.sidebarCollapsed);
  const button = $('#sidebar-toggle');
  const icon = mobile ? 'close' : state.sidebarCollapsed ? 'expand' : 'collapse';
  if (button.dataset.currentIcon !== icon) { button.innerHTML = svg(icon); button.dataset.currentIcon = icon; }
  const label = mobile ? '关闭导航' : state.sidebarCollapsed ? '展开导航' : '缩窄导航';
  button.setAttribute('aria-label',label); button.title = label;
  button.setAttribute('aria-expanded',String(mobile ? $('#sidebar').classList.contains('open') : !state.sidebarCollapsed));
  uiRoot.querySelectorAll('[data-action=menu]').forEach(item => item.setAttribute('aria-expanded',String($('#sidebar').classList.contains('open'))));
}
function toggleSidebar() {
  if (matchMedia('(max-width:760px)').matches) { setMenu(false); return; }
  const position = conversations.position();
  state.sidebarCollapsed = !state.sidebarCollapsed;
  try { localStorage.setItem('qqbot-sidebar-collapsed',state.sidebarCollapsed ? '1' : '0'); } catch {}
  renderSidebarState();
  conversations.restore(position);
}
function pageTools() {
  return `<div class="page-tools"><button class="icon-button mobile-menu" data-action="menu" aria-label="展开导航" aria-controls="sidebar" aria-expanded="false" title="导航">${svg('menu')}</button><button class="icon-button" data-action="refresh" aria-label="刷新页面" title="刷新">${svg('refresh')}</button><button class="avatar" data-action="account" aria-label="${esc(state.auth?.username || '')}，账号设置" title="账号设置">${avatarImage(USER_AVATAR)}</button></div>`;
}
const statusNames = {queued:'排队中',preparing:'准备中',submitting:'提交中',running:'执行中',waiting:'等待授权／回答',cancelling:'取消中',cancelled:'已取消',reply_ready:'等待交付',delivering:'交付中',done:'已完成',failed:'执行失败',send_uncertain:'发送未确认',send_failed:'发送失败',steering:'插话待提交',steered:'插话已提交',ready:'待发送',sending:'发送中',sent:'已发送',uncertain:'结果未确认',blocked:'已阻止',uploading:'上传中',completed:'已完成',error:'失败',pending:'等待中',answered:'已处理',expired:'已过期',active:'生效中'};
const unfinished = new Set(['queued','preparing','submitting','running','waiting','cancelling','reply_ready','delivering']);
const pill = status => `<span class="pill ${['done','sent','completed','active'].includes(status) ? 'good' : ['failed','send_failed','send_uncertain','uncertain','error'].includes(status) ? 'bad' : ['running','submitting','preparing','delivering'].includes(status) ? 'blue' : 'warm'}">${esc(statusNames[status] || status)}</span>`;
const conversations = createConversationsPage({api, $, esc, number, date, ms, svg, avatarImage, userAvatar, empty, heading, keepDetails, pill, unfinished, toast, onOpenJob: id => openJob(id)});

let toastTimer, searchTimer;
function toast(text) { $('#toast').textContent = text; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 5000); }
function connected(ok) { const node = $('#connection'); node.classList.toggle('offline', !ok); node.innerHTML = `<span class="connection-label">${ok ? '管理台已连接' : '正在重新连接'}</span>`; }
async function api(path, body) {
  const response = await fetch(`/api${path}`, {credentials:'same-origin',cache:'no-store', ...(body === undefined ? {} : {method:'POST',headers:{...(body instanceof FormData ? {} : {'Content-Type':'application/json'}),'X-CSRF-Token':state.auth?.csrf || ''},body:body instanceof FormData ? body : JSON.stringify(body)})});
  let result;
  try { result = await response.json(); } catch { throw new Error('服务正在恢复，请稍后重试'); }
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login') showLogin();
    throw new Error(result.error || `请求未完成（${response.status}）`);
  }
  connected(true);
  return result;
}
function showLogin() {
  conversations.leave(); knowledge.leave();
  state.auth = null; state.viewVersion++; state.detailVersion++;
  $('#loading').hidden = true; $('#app').hidden = true; $('#login').hidden = false;
  $('#main').replaceChildren(); $('#detail-content').replaceChildren();
  for (const node of uiRoot.querySelectorAll('dialog[open]')) node.close();
  state.detailJob = state.detailSession = state.detailData = null;
  $('#login-form').elements.password.value = '';
  window.scrollTo(0,0);
}
function authReady(auth) {
  state.auth = auth;
  $('#loading').hidden = true; $('#login').hidden = true; $('#app').hidden = false;
  $('#initial-banner').hidden = !auth.initial_password;
  $('#account-avatar').setAttribute('aria-label', `${auth.username}，账号设置`);
  $('#navigation').dataset.view = '';
  renderNav();
}
function renderNav() {
  if ($('#navigation').dataset.view !== state.view) { $('#navigation').innerHTML = Object.entries(names).filter(([key]) => key !== 'knowledge' || state.auth?.knowledge_enabled === true).map(([key,label]) => `<button class="nav-button ${state.view === key ? 'active' : ''}" data-action="navigate" data-view="${key}" aria-label="${label}" title="${label}" ${state.view === key ? 'aria-current="page"' : ''}>${svg(key)}<span class="nav-text">${label}</span></button>`).join(''); $('#navigation').dataset.view = state.view; }
  $('#page-name').textContent = names[state.view];
  $('#overview-topbar').hidden = state.view !== 'overview';
  $('#workspace').dataset.page = state.view;
  renderSidebarState();
}
function heading(title, subtitle, action = '') {
  const tools = state.view === 'overview' ? `<span class="date">${new Date().toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'long',day:'numeric',weekday:'long'})}</span>` : pageTools();
  return `<div class="page-heading"><div class="heading-copy"><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="heading-actions">${tools}${action ? `<div class="heading-extra">${action}</div>` : ''}</div></div>`;
}
function empty(text, icon = 'conversations') { return `<div class="empty">${svg(icon)}${esc(text)}</div>`; }
function keepDetails(node, html) {
  const opened = new Set([...node.querySelectorAll('details[open][data-key]')].map(el => el.dataset.key));
  const top = node.scrollTop;
  node.innerHTML = html;
  node.querySelectorAll('details[data-key]').forEach(el => { el.open = opened.has(el.dataset.key); });
  node.scrollTop = top;
}
function targetLabel(job) { return job.target.group_id ? `群 ${job.target.group_id} · QQ ${job.target.user_id}` : `私聊 ${job.target.user_id}`; }
function taskRows(items, cancel = false) {
  return items.map(job => `<tr><td class="task-primary"><button class="text-button task-text" data-action="job" data-id="${esc(job.id)}">${esc(job.text.slice(0, 65) || '附件任务')}</button><div class="task-sub">${esc(targetLabel(job))}</div></td><td class="task-status">${pill(job.status)}</td><td class="muted nowrap task-date">${date(job.created)}</td><td class="task-actions"><div class="inline-actions"><button class="text-button icon-link" data-action="job" data-id="${esc(job.id)}" title="查看执行详情" aria-label="查看执行详情">${svg('view')}<span class="button-label">查看</span></button>${cancel && unfinished.has(job.status) ? `<button class="text-button icon-link" data-action="cancel" data-id="${esc(job.id)}" title="取消任务" aria-label="取消任务">${svg('close')}<span class="button-label">取消</span></button>` : ''}</div></td></tr>`).join('');
}
function taskTable(items, cancel = false) { return items.length ? `<div class="table-scroll"><table class="task-table task-list-table"><thead><tr><th>任务与来源</th><th>状态</th><th>接收时间</th><th>操作</th></tr></thead><tbody>${taskRows(items,cancel)}</tbody></table></div>` : empty(cancel ? '目前没有待处理的任务' : '还没有任务记录', 'queue'); }
function connections(overview) {
  const knowledge = overview.knowledge || {enabled:state.auth?.knowledge_enabled === true,ready:false,error:false};
  const rows = [
    ['QQ / NapCat','消息收发连接','conversations',overview.napcat_online,'未连接'],
    ['OpenCode','任务执行引擎','model',overview.opencode_online,'未连接'],
    ['个人记忆','Mem0 / pgvector','database',overview.memory.ready,overview.memory.enabled ? '待就绪' : '未启用'],
    ['知识库','LlamaIndex / pgvector','knowledge',knowledge.ready,knowledge.enabled ? (knowledge.error ? '暂不可用' : '待就绪') : '未启用']
  ];
  return rows.map(([title,note,symbol,online,offline]) => `<div class="status-row"><div class="status-symbol">${svg(symbol)}</div><div><h3>${title}</h3><p>${note}</p></div><span class="pill ${online ? 'good' : 'warm'}">${online ? '已连接' : offline}</span></div>`).join('');
}

async function loadOverview() { state.overview = await api('/overview'); return state.overview; }
async function overviewPage() {
  const [overview,recent] = await Promise.all([loadOverview(),api('/jobs')]);
  const abnormal = (overview.outbox.uncertain || 0) + (overview.outbox.failed || 0);
  const stats = [['conversations','会话总数',overview.conversations,'私聊与群聊，分别管理'],['queue','待处理任务',overview.unfinished,`等待授权／回答 ${overview.pending_interactions} 项`],['memories','有效记忆',overview.memory.entries,`归档对话 ${number(overview.memory.archive)} 条`],['alert','发送异常',abnormal,'失败或等待确认的发送记录']];
  return heading(`欢迎回来，${state.auth.username}`, '对话的进展、任务的状态，还有那些被认真记住的事。') + `<div class="stats-grid">${stats.map(([icon,label,value,note]) => `<div class="stat-card"><div class="stat-head"><span class="stat-label">${label}</span><div class="stat-icon">${svg(icon)}</div></div><strong class="stat-value">${number(value)}</strong><p class="stat-note">${note}</p></div>`).join('')}</div><div class="grid-two"><section class="panel"><div class="panel-heading"><h3>最近的任务</h3><button class="text-button" data-action="navigate" data-view="conversations">查看全部 ${svg('next')}</button></div>${taskTable(recent.items.slice(0,8))}</section><div><section class="panel"><div class="panel-heading"><h3>连接状态</h3><span class="pill good">桥接运行中</span></div><div class="panel-body">${connections(overview)}</div></section><section class="panel"><div class="panel-heading"><h3>运行概况</h3></div><div class="settings-list"><div class="setting-row"><span>本次运行时长</span><span>${ms(overview.uptime_seconds * 1000)}</span></div><div class="setting-row"><span>记忆后台待处理</span><span>${number(overview.memory.work)} 项</span></div><div class="setting-row"><span>发送队列待处理</span><span>${number((overview.outbox.ready || 0) + (overview.outbox.sending || 0) + (overview.outbox.uploading || 0))} 项</span></div></div></section><p class="intro-note">页面每 5 秒更新。时间统一显示为北京时间。<br>点击任意任务，查看原始响应与执行过程。</p></div></div>`;
}
async function queuePage() {
  const result = await api(`/jobs?unfinished=${state.queueHistory ? '0' : '1'}`);
  state.queueItems = result.items; state.queueNext = result.next;
  return heading('任务队列', '查看执行、等待和交付状态，管理正在进行的任务。', `<button class="button" data-action="queue-mode">${state.queueHistory ? '查看待处理' : '查看全部历史'}</button>`) + `<section class="panel"><div class="panel-heading"><h3>${state.queueHistory ? '全部任务' : '待处理任务'}</h3><small>普通执行任务保持串行</small></div><div id="queue-table">${taskTable(state.queueItems,true)}</div></section><div id="queue-more">${state.queueNext ? '<button class="button load-older" data-action="older-queue">加载更多</button>' : ''}</div>`;
}
const kindNames = {profile:'个人资料',experience:'经历',state:'短期状态',knowledge:'方法与知识',explicit:'明确记住',diary:'日记'};
const subjectNames = {user:'主人',assistant:'助手',shared:'共同经历'};
function memoryCard(item) {
  return `<article class="memory-card"><header><span class="pill good">${esc(subjectNames[item.subject] || item.subject)}</span><span class="pill">${esc(kindNames[item.kind] || item.kind)}</span><span class="pill ${item.scope === 'private' ? 'warm' : 'blue'}">${item.scope === 'private' ? '私聊范围' : '群聊范围'}</span>${item.pinned ? '<span class="pill">已保护</span>' : ''}${item.expired ? '<span class="pill warm">历史状态 · 已过期</span>' : ''}${item.state === 'pending' ? pill('pending') : ''}</header><p class="memory-content">${esc(item.content)}</p><div class="memory-meta"><span>${date(item.created)}</span><span>${item.fact_key ? esc(item.fact_key) : ''}</span></div>${item.expires ? `<p class="form-hint">状态有效期至 ${date(item.expires,true)}</p>` : ''}<details class="memory-source" data-key="memory-${esc(item.id)}"><summary>来源与证据 · ${item.sources.length} 个来源</summary>${item.source_excerpts.map(source => `<div class="source-excerpt"><small>${date(source.created,true)} · ${source.scope === 'private' ? '私聊' : `群 ${esc(source.group_id)}`}</small>用户原话：${esc(source.user_text)}${source.assistant_text ? `\n\n助手回复：${esc(source.assistant_text)}` : ''}</div>`).join('') || '<p class="form-hint">没有可展示的原话，来源可能为角色资料、工具证据或已被遗忘。</p>'}<p class="technical-id">${esc(item.id)}</p></details></article>`;
}
async function fetchMemories(append = false) {
  const offset = append ? state.memories.length : 0;
  const params = new URLSearchParams({q:state.memoryQuery,kind:state.memoryKind,subject:state.memorySubject,offset:String(offset)});
  const result = await api(`/memories?${params}`);
  state.memories = append ? [...state.memories,...result.items] : result.items; state.memoryTotal = result.total;
  return result.enabled;
}
function memoryResults() { return state.memories.length ? `<div class="memory-grid">${state.memories.map(memoryCard).join('')}</div>` : empty('没有匹配的记忆', 'memories'); }
function memoryMore() { return state.memories.length < state.memoryTotal ? '<button class="button load-older" data-action="more-memories">加载更多记忆</button>' : ''; }
async function memoriesPage() {
  const enabled = await fetchMemories();
  return heading('记忆库', '个人资料、助手的信息、共同经历与日记，按来源和范围查看。') + `${!enabled ? '<div class="notice">当前未启用个人记忆。</div>' : ''}<div class="toolbar"><input class="search" id="memory-search" aria-label="搜索记忆" placeholder="搜索被记住的内容…" value="${esc(state.memoryQuery)}"><select id="memory-subject" aria-label="记忆主体"><option value="">全部主体</option>${Object.entries(subjectNames).map(([key,value]) => `<option value="${key}" ${state.memorySubject === key ? 'selected' : ''}>${value}</option>`).join('')}</select><select id="memory-kind" aria-label="记忆类型"><option value="">全部类型</option>${Object.entries(kindNames).map(([key,value]) => `<option value="${key}" ${state.memoryKind === key ? 'selected' : ''}>${value}</option>`).join('')}</select><span class="count-note" id="memory-count">共 ${number(state.memoryTotal)} 条</span></div><div id="memory-results">${memoryResults()}</div><div id="memory-more">${memoryMore()}</div><p class="intro-note">仅显示当前账号的有效或待保存记忆。已遗忘内容不在此展示；过期的短期状态单独标注。</p>`;
}
function auditName(action) { return ({login:'登录管理台',password_changed:'修改账号密码',restart_requested:'请求重启桥接',cancel_requested:'请求取消任务',mapping_switched:'切换会话映射'})[action] || action; }
function sessionRows() {
  const query = state.sessionQuery.toLowerCase();
  const items = state.sessionIndex.items.filter(item => `${item.title} ${item.id} ${item.conversation}`.toLowerCase().includes(query));
  return items.length ? `<div class="table-scroll"><table class="task-table"><thead><tr><th>OpenCode 会话</th><th>聊天来源</th><th>标记</th><th>操作</th></tr></thead><tbody>${items.map(item => `<tr><td><button class="text-button task-text" data-action="session" data-id="${esc(item.id)}">${esc(item.title)}</button><div class="technical-id">${esc(item.id)}</div><div class="task-sub">${number(item.tasks)} 个桥接任务 · ${date(item.updated)}</div></td><td class="muted">${esc(item.conversation)}</td><td><div class="tags">${item.current ? '<span class="pill good">当前映射</span>' : '<span class="pill">历史会话</span>'}${item.isolated ? '<span class="pill warm">主人群聊独立</span>' : ''}${item.archived ? '<span class="pill">已归档</span>' : ''}</div></td><td><button class="text-button" data-action="session" data-id="${esc(item.id)}">查看记录 ${svg('open')}</button></td></tr>`).join('')}</tbody></table></div>` : empty('没有匹配的历史会话','sessions');
}
async function sessionsPage() {
  const index = await api('/sessions'); state.sessionIndex = index;
  return heading('会话映射', '查看全部桥接会话，包括已切换、已归档和主人群聊独立会话。') + `${index.warning ? `<div class="notice">${esc(index.warning)}</div>` : ''}<section class="panel"><div class="panel-heading"><h3 class="inline-heading">QQ 聊天 ${svg('next')} 当前 OpenCode 会话</h3><small>切换保留所有原始历史</small></div><div class="table-scroll"><table class="task-table"><thead><tr><th>聊天</th><th>当前映射</th><th>操作</th></tr></thead><tbody>${index.mappings.map(item => `<tr><td>${esc(item.title)}<div class="task-sub">${esc(item.conversation)}</div></td><td>${item.session_id ? `<button class="text-button technical-id" data-action="session" data-id="${esc(item.session_id)}">${esc(item.session_id)}</button>` : '<span class="muted">下次任务创建新会话</span>'}</td><td><button class="button small" data-action="mapping" data-id="${esc(item.conversation)}">切换映射</button></td></tr>`).join('')}</tbody></table></div></section><div class="toolbar"><input class="search" id="session-search" aria-label="搜索历史会话" placeholder="搜索会话名称、QQ、群号或 Session ID" value="${esc(state.sessionQuery)}"><span class="count-note">${number(index.items.length)} 个会话${index.complete ? '' : '（当前已加载）'}</span></div><section class="panel"><div class="panel-heading"><h3>全部历史会话</h3><small>OpenCode 原始记录按需读取</small></div><div id="session-rows">${sessionRows()}</div></section>`;
}
async function mappingDialog(conversation) {
  state.sessionIndex = await api('/sessions');
  const mapping = state.sessionIndex.mappings.find(item => item.conversation === conversation);
  const candidates = state.sessionIndex.items.filter(item => item.conversation === conversation && item.eligible);
  if (!mapping || !candidates.length) { toast('这个聊天没有可切换的历史会话'); return; }
  dialog(`<h2 id="action-title">切换会话映射</h2><p>${esc(mapping.title)}。后续新任务将接续所选会话的历史。当前有未完成任务时无法切换；主人群聊独立会话不用于群共享。</p><form id="mapping-form" data-conversation="${esc(conversation)}" data-expected="${esc(mapping.session_id || '')}"><label>目标 OpenCode 会话<select name="session_id" class="search" required>${candidates.map(item => `<option value="${esc(item.id)}" ${item.id === mapping.session_id ? 'selected' : ''}>${esc(item.title)} · ${item.id.slice(-10)}${item.current ? '（当前）' : ''}</option>`).join('')}</select></label><div class="error" id="mapping-error" role="alert"></div><div class="dialog-actions"><button type="button" class="button" data-action="close-action">取消</button><button type="submit" class="primary">确认切换</button></div></form>`);
}
async function systemPage() {
  const [system,overview] = await Promise.all([api('/system'),loadOverview()]);
  const configLabels = {public_url:'访问地址',model:'聊天模型',memory_enabled:'个人记忆',memory_model:'记忆校验模型',embedding_model:'Embedding 模型',rerank_model:'重排模型',max_queued_per_context:'每会话队列上限',execution_timeout:'执行超时（秒）'};
  return heading('系统管理', '查看服务与配置，管理账号和桥接进程。') + `<div class="settings-grid"><div><section class="panel"><div class="panel-heading"><h3>桥接服务</h3><span class="pill good">运行中</span></div><div class="service-card"><span class="service-icon">${svg('system')}</span><div class="service-info"><h3>qqbot.service</h3><p>本次运行 ${ms(overview.uptime_seconds * 1000)}</p></div><button class="danger" data-action="restart">重启服务</button></div><p class="service-description">重启后继续核对持久化任务和发送状态，保留会话映射与记忆。当前 ${number(overview.unfinished)} 个任务待处理。</p>${overview.restart_pending ? '<div class="restart-state">已提交重启请求，正在等待服务恢复…</div>' : ''}${overview.restart_error ? `<div class="restart-state">${esc(overview.restart_error)}</div>` : ''}</section><section class="panel"><div class="panel-heading"><h3>当前配置</h3><small>运行中生效值</small></div><div class="settings-list">${Object.entries(system.config).map(([key,value]) => `<div class="setting-row"><span>${esc(configLabels[key] || key)}</span><span>${esc(typeof value === 'boolean' ? (value ? '已启用' : '未启用') : value || '未配置')}</span></div>`).join('')}</div></section></div><div><section class="panel"><div class="panel-heading"><h3>连接状态</h3></div><div class="panel-body">${connections(overview)}</div></section><section class="panel"><div class="panel-heading"><h3>管理账号</h3><button class="text-button" data-action="account">管理 ${svg('next')}</button></div><div class="panel-body"><h3>${esc(state.auth.username)}</h3><p class="intro-note">独立账号密码登录，当前浏览器会话保留 7 天。修改密码会使其他登录失效。</p><button class="button small" data-action="logout">退出当前登录</button></div></section><section class="panel"><div class="panel-heading"><h3>最近的管理操作</h3></div><ul class="audit-list">${system.audit.slice(0,8).map(item => `<li><span>${esc(auditName(item.action))}</span><small>${date(item.created)}</small></li>`).join('') || '<li class="muted">暂无操作记录</li>'}</ul></section></div></div>`;
}
const knowledge = createKnowledgePage({api, $, esc, date, ms, svg, empty, heading, dialog, toast, navigate: (view, quiet) => navigate(view, quiet), clearDetail: () => { state.detailJob = state.detailSession = null; }, onOpenJob: id => openJob(id)});

async function navigate(view, quiet = false) {
  if (view.startsWith('knowledge?')) { knowledge.setPendingDocument(new URLSearchParams(view.split('?')[1]).get('document')); view = 'knowledge'; }

  if (view === 'knowledge' && state.auth?.knowledge_enabled !== true) { view = 'overview'; toast('知识库尚未启用'); }
  if (!names[view]) view = 'overview';
  const changed = state.view !== view;
  if (changed && state.view === 'conversations') conversations.leave();
  if (changed && state.view === 'knowledge') knowledge.leave();
  state.view = view; const version = ++state.viewVersion;
  const historyPosition = view === 'conversations' ? conversations.position() : null;
  renderNav(); if (!quiet || changed) setMenu(false);
  if (!quiet) window.scrollTo(0,0);
  history.replaceState(null,'',`#/${view}`);
  if (!quiet) $('#main').innerHTML = '<div class="empty">正在读取记录…</div>';
  try {
    const html = await ({overview:overviewPage,conversations:conversations.render,sessions:sessionsPage,queue:queuePage,memories:memoriesPage,knowledge:knowledge.render,system:systemPage})[view]();
    if (html !== null && state.auth && version === state.viewVersion) { keepDetails($('#main'),html); renderSidebarState(); if (view === 'conversations') conversations.restore(historyPosition,quiet ? 'preserve' : 'latest'); if (view === 'knowledge') await knowledge.openPendingDocument(); }
  } catch (error) {
    if (state.auth && version === state.viewVersion) $('#main').innerHTML = `<div class="notice">${esc(error.message)} <button class="text-button" data-action="refresh">重试</button></div>`;
    connected(false);
  }
}
function renderParts(message) {
  return (message.content || []).map((part,index) => {
    const key = `${message.id}-${part.id || index}`;
    if (part.type === 'text') return `<div class="run-text">${esc(part.text)}</div>`;
    if (part.type === 'reasoning') return `<details class="run-detail" data-key="${esc(key)}"><summary>思考记录 <span class="pill">${ms(part.duration_ms)}</span></summary><div class="run-detail-body"><pre>${esc(part.text)}</pre></div></details>`;
    if (part.type === 'tool') return `<details class="run-detail" data-key="${esc(key)}"><summary>${pill(part.status || 'pending')}<strong>${esc(part.name || 'tool')}</strong> · ${ms(part.duration_ms)}</summary><div class="run-detail-body"><h4>输入</h4><pre>${esc(json(part.input || {}))}</pre><h4>输出</h4>${part.output?.length ? part.output.map(item => `<pre>${esc(item.type === 'text' ? item.text : json(item))}</pre>`).join('') : '<pre class="muted">尚无输出记录</pre>'}${part.error ? `<h4>错误</h4><pre class="error">${esc(json(part.error))}</pre>` : ''}</div></details>`;
    return `<p class="model-tag">${esc(part.type)} · ${esc(part.name || part.path || part.text || '')}</p>`;
  }).join('');
}
function runMessage(message) {
  if (['idle','agent-switched','model-switched','location-switched'].includes(message.type)) return '';
  const label = ({user:'用户提交',assistant:'OpenCode 响应',system:'系统记录',synthetic:'上下文补充',compaction:'上下文压缩',skill:'技能',shell:'Shell'})[message.type] || message.type;
  const raw = message.text || message.summary || message.description || message.command || message.output;
  const text = raw ? `<div class="run-text">${esc(typeof raw === 'string' ? raw : json(raw))}</div>` : '';
  const content = text + renderParts(message) + (message.files?.length ? `<div class="attachment-tags">${message.files.map(file => `<span class="pill">附件 · ${esc(file.name || file.filename || file.path || file.type || 'file')}</span>`).join('')}</div>` : '');
  const model = message.model ? (typeof message.model === 'string' ? message.model : [message.model.providerID,message.model.modelID || message.model.id].filter(Boolean).join('/')) : '';
  if (!content && !message.error) return '';
  if (['user','system','synthetic'].includes(message.type)) return `<details class="run-detail" data-key="msg-${esc(message.id)}"><summary>${esc(label)} · ${message.time?.created ? date(message.time.created / 1000) : ''}</summary><div class="run-detail-body">${content}</div></details>`;
  return `<article class="run-message"><header class="run-message-header"><span>${esc(label)}</span><span>${message.time?.created ? date(message.time.created / 1000) : ''}</span></header>${content}${message.error ? `<pre class="run-text error">${esc(json(message.error))}</pre>` : ''}${model ? `<p class="model-tag">${esc(model)}</p>` : ''}</article>`;
}
function detailMetrics(stats, label) {
  if (!stats) return '';
  return `<div class="detail-metrics">${[['工具调用',number(stats.tools)],['思考耗时',ms(stats.reasoning_ms)],['响应轮次耗时',ms(stats.model_ms)],['输出 Token',number(stats.output_tokens)]].map(([key,value]) => `<div class="detail-metric"><span>${key}</span><strong>${value}</strong></div>`).join('')}</div><p class="detail-note">${esc(label)}，共 ${number(stats.model_calls)} 次响应。输入 ${number(stats.input_tokens)} · 思考 ${number(stats.reasoning_tokens)} · 缓存读取 ${number(stats.cache_read_tokens)} Token。${stats.reasoning_missing ? `另有 ${stats.reasoning_missing} 段思考缺少完整时间戳，显示耗时为已记录部分。` : '思考耗时按 reasoning 记录时间戳汇总；响应轮次耗时包含该轮工具执行。'}子会话可从完整会话入口单独查看。</p>${Object.keys(stats.tool_names).length ? `<div class="tags">${Object.entries(stats.tool_names).map(([key,value]) => `<span class="pill">${esc(key)} × ${value}</span>`).join('')}</div>` : ''}`;
}
function renderJobDetail(detail) {
  const canCancel = unfinished.has(detail.status);
  let html = `<div class="detail-toolbar">${pill(detail.status)}${detail.session_id ? `<button class="button small" data-action="session" data-id="${esc(detail.session_id)}">完整会话与子任务</button>` : ''}<button class="button small" data-action="refresh-detail">刷新记录</button>${canCancel ? `<button class="danger small" data-action="cancel" data-id="${esc(detail.id)}">取消任务</button>` : ''}</div>${detail.remote_error ? `<div class="notice">${esc(detail.remote_error)}</div>` : ''}${detailMetrics(detail.metrics,'本轮主会话统计')}<div class="detail-section"><div class="message-label">用户原话 · QQ ${esc(detail.target.user_id)}</div><div class="run-text">${esc(detail.text)}</div>${detail.steers?.length ? detail.steers.map(s => `<div class="source-excerpt"><small>补充消息 · ${date(s.created)}</small>${esc(s.text)}</div>`).join('') : ''}</div>`;
  html += `<div class="detail-toolbar"><button class="button small" data-action="detail-tab" data-tab="run" ${state.detailTab === 'run' ? 'disabled' : ''}>执行记录</button><button class="button small" data-action="detail-tab" data-tab="delivery" ${state.detailTab === 'delivery' ? 'disabled' : ''}>交付与诊断</button><button class="button small" data-action="detail-tab" data-tab="input" ${state.detailTab === 'input' ? 'disabled' : ''}>冻结提交</button></div>`;
  if (state.detailTab === 'run') html += `<section class="detail-section">${detail.messages?.map(runMessage).join('') || empty('暂无可读取的 OpenCode 消息')}</section>${detail.result ? `<details class="run-detail" data-key="result"><summary>桥接保存的最终回复</summary><div class="run-detail-body"><pre>${esc(detail.result)}</pre></div></details>` : ''}`;
  else if (state.detailTab === 'input') html += `<div class="run-message"><p class="technical-id">Session ${esc(detail.session_id || '尚未创建')}<br>Prompt ${esc(detail.prompt_id)}</p><pre class="run-text">${esc(detail.submitted_text || '尚未冻结提交文本')}</pre></div>`;
  else html += `<section class="detail-section"><h3 class="detail-section-title">等待授权／回答</h3>${detail.interactions?.map(item => `<details class="run-detail" data-key="interaction-${esc(item.code)}"><summary>${esc(item.kind === 'permission' ? '操作授权' : '问题回答')} [${esc(item.code)}] ${pill(item.state)}</summary><div class="run-detail-body"><pre>${esc(json(JSON.parse(item.payload)))}</pre></div></details>`).join('') || '<p class="muted run-text">没有交互记录。</p>'}</section><section class="detail-section"><h3 class="detail-section-title">消息交付</h3>${detail.deliveries.map(item => `<details class="run-detail" data-key="delivery-${item.id}"><summary>${esc(({text:'文字',image:'图片',video:'视频',audio:'音频',file:'文件',poke:'完成戳一戳'})[item.kind] || item.kind)} · ${date(item.created)} ${pill(item.status)}</summary><div class="run-detail-body"><pre>${esc(item.text || '（非文本内容）')}</pre><p class="technical-id">QQ 消息 ${esc(item.message_id || '未确认')}</p></div></details>`).join('') || '<p class="muted run-text">没有发送记录。</p>'}</section><section class="detail-section"><h3 class="detail-section-title">处理轨迹</h3><ol class="trace-list">${detail.events.map(item => `<li>${esc(item.stage)} / ${esc(item.reason)}<small>${date(item.created,true)} · 消息 ${esc(item.event_id || '')}</small></li>`).join('') || '<li>记录可能已超过保留期。</li>'}</ol></section>`;
  if (detail.error) html += `<div class="notice">${esc(detail.error)}</div>`;
  html += `<p class="technical-id">任务 ${esc(detail.id)}<br>接收于 ${date(detail.created,true)} · 执行计时 ${ms(detail.elapsed * 1000)}</p>`;
  keepDetails($('#detail-content'),html);
}
async function openJob(id, refresh = false) {
  state.detailJob = id; state.detailSession = null;
  if (!refresh) { state.detailTab = 'run'; state.detailData = null; $('#detail-content').innerHTML = '<div class="empty">正在读取 OpenCode 记录…</div>'; }
  const version = ++state.detailVersion;
  $('#detail-title').textContent = '执行详情'; $('#detail-eyebrow').textContent = 'EXECUTION DETAIL';
  if (!$('#detail-dialog').open) $('#detail-dialog').showModal();
  try {
    const detail = await api(`/jobs/${encodeURIComponent(id)}`);
    if (!state.auth || version !== state.detailVersion) return;
    state.detailData = detail; renderJobDetail(detail);
  } catch (error) { if (version === state.detailVersion && state.auth) $('#detail-content').innerHTML = `<div class="notice">${esc(error.message)}</div><button class="button" data-action="refresh-detail">重试</button>`; }
}
async function openSession(id, cursor = null) {
  const version = ++state.detailVersion;
  state.detailSession = id;
  $('#detail-title').textContent = 'OpenCode 完整会话'; $('#detail-eyebrow').textContent = 'SESSION HISTORY';
  if (!$('#detail-dialog').open) $('#detail-dialog').showModal();
  if (!cursor) $('#detail-content').innerHTML = '<div class="empty">正在读取会话…</div>';
  try {
    const result = await api(`/sessions/${encodeURIComponent(id)}${cursor ? '?cursor=' + encodeURIComponent(cursor) : ''}`);
    if (!state.auth || version !== state.detailVersion) return;
    const content = result.messages.map(runMessage).join('');
    if (cursor) {
      $('#session-messages').insertAdjacentHTML('afterbegin',content);
      $('#session-more').innerHTML = result.next ? `<button class="button small load-older" data-action="older-session" data-cursor="${esc(result.next)}">${svg('up')}加载更早消息</button>` : '';
      $('#session-page-note').textContent = '已追加更早消息；上方统计对应首次加载的最近一页。';
    } else $('#detail-content').innerHTML = `<div class="detail-toolbar">${state.detailJob ? `<button class="button small" data-action="back-job">${svg('back')}返回任务</button>` : ''}<span class="technical-id">${esc(id)}</span></div><h3>${esc(result.title)}</h3><p class="detail-note">历史会话按原始内容分页读取；包括系统记录、工具输入输出及模型返回的思考记录。</p>${detailMetrics(result.metrics,result.metrics_scope)}<p class="detail-note" id="session-page-note">本页 ${result.messages.length} 条记录，按时间顺序展示。</p>${result.children.length ? `<h3 class="detail-section-title">子会话</h3><div class="session-children">${result.children.map(child => `<button class="button small" data-action="session" data-id="${esc(child.id)}">${esc(child.title || child.id)} ${svg('open')}</button>`).join('')}</div>` : ''}<div id="session-more">${result.next ? `<button class="button small load-older" data-action="older-session" data-cursor="${esc(result.next)}">${svg('up')}加载更早消息</button>` : ''}</div><section id="session-messages">${content || empty('这个会话还没有消息')}</section>`;
  } catch (error) { if (state.auth && version === state.detailVersion) $('#detail-content').innerHTML = `<div class="notice">${esc(error.message)}</div>${state.detailJob ? '<button class="button" data-action="back-job">返回任务</button>' : ''}`; }
}
function dialog(html) { $('#action-content').innerHTML = html; if (!$('#action-dialog').open) $('#action-dialog').showModal(); }
function accountDialog() {
  dialog(`<h2 id="action-title">管理账号</h2><p>修改账号或密码后，其他浏览器的登录会失效。</p><form id="account-form"><label>账号<input name="username" value="${esc(state.auth.username)}" autocomplete="username" required maxlength="64"></label><label>当前密码<input name="current_password" type="password" autocomplete="current-password" required maxlength="256"></label><label>新密码<input name="password" type="password" autocomplete="new-password" required minlength="12" maxlength="256"></label><label>再次输入新密码<input name="repeat" type="password" autocomplete="new-password" required minlength="12" maxlength="256"></label><p class="form-hint">使用至少 12 个字符。</p><div class="error" id="account-error" role="alert"></div><div class="dialog-actions"><button type="button" class="button" data-action="close-action">取消</button><button type="submit" class="primary">保存账号</button></div></form>`);
}
async function confirmRestart() {
  const overview = await loadOverview();
  dialog(`<h2 id="action-title">重启桥接服务？</h2><p>当前有 ${number(overview.unfinished)} 个任务待处理，${number(overview.pending_interactions)} 项等待授权或回答。<br><br>将重启 qqbot.service。任务、会话和记忆保留，服务启动后继续核对执行与交付状态。</p><div class="dialog-actions"><button class="button" data-action="close-action">暂不重启</button><button class="danger" data-action="confirm-restart">确认重启</button></div>`);
}
async function pollRestart() {
  const start = Date.now(); const previous = state.restarting;
  dialog('<h2 id="action-title">正在重启</h2><p id="restart-progress" role="status">重启请求已提交，正在等待管理台重新连接…</p>');
  while (state.restarting && Date.now() - start < 90000) {
    await new Promise(resolve => setTimeout(resolve,1800));
    try {
      const auth = await api('/auth/status');
      if (auth.boot_id !== previous) {
        state.restarting = null;
        if (auth.authenticated) { authReady(auth); $('#action-dialog').close(); await navigate('system'); toast('桥接已重新启动，管理台已连接'); }
        else { showLogin(); toast('服务已重新启动，请重新登录'); }
        return;
      }
      const overview = await api('/overview');
      if (overview.restart_error) { state.restarting = null; dialog(`<h2 id="action-title">重启未完成</h2><p>${esc(overview.restart_error)}</p><div class="dialog-actions"><button class="button" data-action="close-action">关闭</button></div>`); return; }
    } catch { connected(false); }
  }
  state.restarting = null;
  dialog('<h2 id="action-title">尚未确认重启结果</h2><p>暂时没有收到新的服务启动标识。你可以稍后刷新页面重新检查。</p><div class="dialog-actions"><button class="button" data-action="close-action">关闭</button><button class="primary" data-action="reload">重新连接</button></div>');
}
async function refresh() {
  if (!state.auth || state.refreshing || state.restarting || document.hidden || $('#sidebar').classList.contains('open') || $('#action-dialog').open) return;
  state.refreshing = true;
  try {
    if (state.view === 'conversations' && $('#conversation-search')) await conversations.refresh(); else if (state.view === 'knowledge') await knowledge.refresh(); else if (!['memories','sessions','knowledge'].includes(state.view) && !(state.view === 'queue' && state.queueHistory)) await navigate(state.view,true);
    if (state.detailJob && !state.detailSession && state.detailData && unfinished.has(state.detailData.status)) await openJob(state.detailJob,true);
  } catch { connected(false); }
  finally { state.refreshing = false; }
}
uiRoot.addEventListener('click',async event => {
  const button = event.target.closest('[data-action]'); if (!button) return;
  const action = button.dataset.action;
  try {
    if (await conversations.handleAction(action, button)) return;
    if (await knowledge.handleAction(action, button)) return;
    else if (action === 'navigate') { await navigate(button.dataset.view); }
    else if (action === 'refresh') { await navigate(state.view,true); }
    else if (action === 'menu') setMenu(!$('#sidebar').classList.contains('open'));
    else if (action === 'close-menu') setMenu(false);
    else if (action === 'toggle-sidebar') toggleSidebar();
    else if (action === 'account') accountDialog();
    else if (action === 'mapping') await mappingDialog(button.dataset.id);
    else if (action === 'logout') { await api('/auth/logout',{}); showLogin(); }
 else if (action === 'queue-mode') { state.queueHistory = !state.queueHistory; await navigate('queue',true); }
    else if (action === 'older-queue') {
      const result = await api(`/jobs?unfinished=${state.queueHistory ? '0' : '1'}&before=${encodeURIComponent(state.queueNext)}`);
      state.queueItems.push(...result.items); state.queueNext = result.next;
      $('#queue-table').innerHTML = taskTable(state.queueItems,true); $('#queue-more').innerHTML = state.queueNext ? '<button class="button load-older" data-action="older-queue">加载更多</button>' : '';
    } else if (action === 'close-detail') { $('#detail-dialog').close(); state.detailVersion++; state.detailJob = state.detailSession = null; }
    else if (action === 'refresh-detail' || action === 'back-job') await openJob(state.detailJob,true);
    else if (action === 'detail-tab') { state.detailTab = button.dataset.tab; renderJobDetail(state.detailData); }
    else if (action === 'session') await openSession(button.dataset.id);
    else if (action === 'older-session') await openSession(state.detailSession,button.dataset.cursor);
    else if (action === 'more-memories') { await fetchMemories(true); keepDetails($('#memory-results'),memoryResults()); $('#memory-more').innerHTML = memoryMore(); }
    else if (action === 'restart') await confirmRestart();
    else if (action === 'confirm-restart') { button.disabled = true; const result = await api('/system/restart',{confirm:'restart'}); state.restarting = result.boot_id; await pollRestart(); }
    else if (action === 'cancel') dialog(`<h2 id="action-title">取消这个任务？</h2><p>会请求停止原任务及其插话。已经发出的消息会保留。</p><div class="dialog-actions"><button class="button" data-action="close-action">返回</button><button class="danger" data-action="confirm-cancel" data-id="${esc(button.dataset.id)}">确认取消</button></div>`);
    else if (action === 'confirm-cancel') { button.disabled = true; await api(`/jobs/${encodeURIComponent(button.dataset.id)}/cancel`,{}); $('#action-dialog').close(); toast('已请求取消，正在核对任务状态'); if (state.detailJob === button.dataset.id) await openJob(state.detailJob,true); else await navigate(state.view,true); }
    else if (action === 'close-action') $('#action-dialog').close();
    else if (action === 'reload') location.reload();
  } catch (error) { toast(error.message); button.disabled = false; }
});
$('#detail-dialog').addEventListener('close',() => { state.detailVersion++; state.detailJob = state.detailSession = null; });
uiRoot.addEventListener('input',event => {
  if (conversations.handleInput(event.target)) return;
else if (event.target.id === 'memory-search') { state.memoryQuery = event.target.value; scheduleMemorySearch(); }
  else if (event.target.id === 'session-search') { state.sessionQuery = event.target.value; $('#session-rows').innerHTML = sessionRows(); }
});
function scheduleMemorySearch() {
  clearTimeout(searchTimer); searchTimer = setTimeout(async () => {
    try { await fetchMemories(); if ($('#memory-results')) { keepDetails($('#memory-results'),memoryResults()); $('#memory-more').innerHTML = memoryMore(); $('#memory-count').textContent = `共 ${number(state.memoryTotal)} 条`; } } catch(error) { toast(error.message); }
  },300);
}
uiRoot.addEventListener('change',event => { if (knowledge.handleChange(event.target)) return; if (event.target.id === 'memory-kind') { state.memoryKind = event.target.value; scheduleMemorySearch(); } else if (event.target.id === 'memory-subject') { state.memorySubject = event.target.value; scheduleMemorySearch(); } });
uiRoot.addEventListener('submit', event => { void knowledge.handleSubmit(event); });
uiRoot.addEventListener('submit',async event => {
  if (!['login-form','account-form','mapping-form'].includes(event.target.id)) return;
  event.preventDefault(); const form = event.target; const button = form.querySelector('[type=submit]'); button.disabled = true;
  try {
    const values = Object.fromEntries(new FormData(form));
    if (form.id === 'login-form') {
      $('#login-error').textContent = '';
      const auth = await api('/auth/login',values); form.elements.password.value = ''; authReady(auth);
      await navigate(location.hash.slice(2) || 'overview');
    } else if (form.id === 'mapping-form') {
      $('#mapping-error').textContent = '';
      if (values.session_id === form.dataset.expected) throw new Error('请选择另一个历史会话');
      await api('/mappings',{conversation:form.dataset.conversation,session_id:values.session_id,expected_current:form.dataset.expected || null,confirm:'switch'});
      $('#action-dialog').close(); toast('会话映射已切换，原历史保留'); await navigate('sessions',true);
    } else {
      $('#account-error').textContent = '';
      if (values.password !== values.repeat) throw new Error('两次输入的新密码不一致');
      const auth = await api('/auth/password',values); authReady(auth); $('#action-dialog').close(); form.reset(); toast('账号已更新，其他登录已失效');
      if (state.view === 'system') await navigate('system',true);
    }
  } catch(error) { const node = form.id === 'login-form' ? $('#login-error') : form.id === 'mapping-form' ? $('#mapping-error') : $('#account-error'); if (node) node.textContent = error.message; }
  finally { button.disabled = false; }
});
async function boot() {
  try { const auth = await api('/auth/status'); if (auth.authenticated) { authReady(auth); await navigate(location.hash.slice(2) || 'overview'); } else showLogin(); }
  catch { $('#loading').innerHTML = '暂时无法连接管理台，请稍后刷新。'; }
}
uiRoot.addEventListener('scroll',event => { if (event.target.id === 'chat-history') conversations.updateLatest(); },true);
matchMedia('(max-width:760px)').addEventListener('change',() => { setMenu(false); renderSidebarState(); });
fillIcons(); renderSidebarState();
setInterval(refresh,5000);
boot();
