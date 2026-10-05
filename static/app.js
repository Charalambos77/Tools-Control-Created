// Tools Control — UI. Plain ES module, no build step.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const when = (ts) => { if (!ts) return ''; const d = new Date(ts); const days = (Date.now() - d) / 864e5; return days < 1 ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : days < 7 ? d.toLocaleDateString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' }) : d.toLocaleDateString(); };
const short = (p) => { const parts = String(p || '').replace(/\\/g, '/').split('/').filter(Boolean); return parts.slice(-2).join('/') || p; };
const SOURCE_LABEL = { personal: 'Your skills (~/.claude/skills)', project: 'This project (.claude/skills)', plugin: 'From plugins', claude: 'Built into Claude Code / synced', library: 'Tools Control library (added only to chats you choose)' };
const SCOPE_LABEL = { user: 'Every project (user)', local: 'This folder only (local)', project: 'Project file (.mcp.json)', plugin: 'From plugins', library: 'Tools Control library (only in chats you choose)' };

async function api(method, path, body) {
  const r = await fetch(path, { method, headers: body !== undefined ? { 'Content-Type': 'application/json' } : {}, body: body !== undefined ? JSON.stringify(body) : undefined });
  const data = r.headers.get('content-type')?.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error(data?.detail || data || r.statusText);
  return data;
}
function toast(msg, bad = false) {
  const t = document.createElement('div');
  t.className = 'toast' + (bad ? ' bad' : '');
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), bad ? 6500 : 3000);
}
const run = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };
async function waitJob(id, label) {
  for (let i = 0; i < 900; i++) {
    const j = await api('GET', `/api/jobs/${id}`);
    if (j.status === 'done') return j.result;
    if (j.status === 'failed') throw new Error(j.error);
    if (label) label(Math.round((Date.now() / 1000 - j.started)));
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error('Claude took too long');
}
function modal(html, mount, wide = false) {
  const o = $('#overlay');
  o.innerHTML = `<div class="modal-back"><div class="modal ${wide ? 'wide' : ''}">${html}</div></div>`;
  const back = $('.modal-back', o);
  back.addEventListener('mousedown', (e) => { if (e.target === back) closeModal(); });
  mount?.($('.modal', o));
}
const closeModal = () => { $('#overlay').innerHTML = ''; };
const confirmBox = (title, text, ok = 'Yes, do it', danger = false) => new Promise((res) => {
  modal(`<h2>${esc(title)}</h2><p class="sub" style="font-size:13px">${esc(text)}</p><div class="row" style="justify-content:flex-end;margin-top:16px">
    <button class="btn" data-no>Cancel</button><button class="btn ${danger ? 'danger' : 'primary'}" data-yes>${esc(ok)}</button></div>`, (m) => {
    $('[data-no]', m).onclick = () => { closeModal(); res(false); };
    $('[data-yes]', m).onclick = () => { closeModal(); res(true); };
  });
});
const copy = async (text) => { await navigator.clipboard.writeText(text); toast('Copied'); };

const S = { settings: null, page: 'chats', chatQuery: '', chatProject: '', chats: [], projects: [] };

const ICON = {
  chats: '<path d="M4 5h16v11H8l-4 4z"/>',
  skills: '<path d="M12 3l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.4 6.8 19.1l1-5.8L3.5 9.2l5.9-.8z"/>',
  mcp: '<path d="M8 7V3M16 7V3M6 7h12v5a6 6 0 0 1-12 0zM12 18v3"/>',
  create: '<path d="M12 5v14M5 12h14"/>',
  sdk: '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M14 5l-4 14"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
};
const PAGES = [['chats', 'Chats'], ['skills', 'Skills'], ['mcp', 'MCP servers'], ['create', 'Create'], ['sdk', 'SDK & connect'], ['settings', 'Settings']];

function renderNav() {
  $('#nav').innerHTML = PAGES.map(([k, l]) => `<a href="#${k}" class="${S.page === k ? 'on' : ''}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICON[k]}</svg>${l}</a>`).join('');
  $('#rail-foot').innerHTML = `${S.settings?.demo ? '<div class="demo-tag">Demo mode — pretend chats and tools</div>' : ''}
    <div class="mini">Reads <span class="mono">${esc(short(S.settings?.claude_dir_used || ''))}</span></div>`;
}

// =========================================================================================================
// Chats
// =========================================================================================================

const Chats = {
  async render(id) {
    $('#page').innerHTML = `<div class="split">
      <div><div class="sticky-top"><div class="page-head" style="margin-bottom:10px"><div><h1>Chats</h1><p>Pick a conversation to see what it's about and choose its tools.</p></div></div>
        <input type="text" id="c-q" placeholder="Search chats…" value="${esc(S.chatQuery)}">
        <select id="c-proj" style="margin-top:6px"><option value="">All projects</option></select></div>
        <div class="chat-list" id="c-list"><div class="hint">Reading your chats…</div></div></div>
      <div id="c-detail"><div class="empty" style="margin-top:70px">Select a chat on the left.</div></div></div>`;
    let t;
    $('#c-q').oninput = (e) => { S.chatQuery = e.target.value; clearTimeout(t); t = setTimeout(() => this.loadList(id), 250); };
    $('#c-proj').onchange = (e) => { S.chatProject = e.target.value; this.loadList(id); };
    api('GET', '/api/projects').then((ps) => {
      S.projects = ps;
      $('#c-proj').innerHTML = `<option value="">All projects</option>${ps.map((p) => `<option value="${esc(p.cwd || p.folder)}" ${S.chatProject === (p.cwd || p.folder) ? 'selected' : ''}>${esc(short(p.cwd || p.folder))} (${p.chats})</option>`).join('')}`;
    }).catch(() => {});
    await this.loadList(id);
    if (id) this.detail(id);
  },
  async loadList(active) {
    const q = new URLSearchParams({ q: S.chatQuery, project: S.chatProject });
    S.chats = await api('GET', `/api/chats?${q}`);
    const box = $('#c-list');
    if (!box) return;
    box.innerHTML = S.chats.length ? S.chats.map((c) => `<button class="chat-item ${c.id === active ? 'on' : ''}" data-id="${c.id}">
        <div class="t">${esc(c.title)}</div>
        <div class="m"><span>${esc(when(c.updated))}</span><span>${esc(short(c.cwd))}</span><span>${c.prompts} msgs</span>${c.has_profile ? '<span class="pill">tools chosen</span>' : ''}</div>
        ${c.about ? `<div class="m" style="color:#c9d0ff">${esc(c.about.slice(0, 110))}</div>` : ''}</button>`).join('')
      : `<div class="empty">${S.chatQuery ? 'No chat matches.' : 'No Claude Code chats found. Check the folder in Settings.'}</div>`;
    $$('.chat-item', box).forEach((b) => { b.onclick = () => { location.hash = `#chats/${b.dataset.id}`; }; });
  },
  async detail(id) {
    $$('.chat-item').forEach((b) => b.classList.toggle('on', b.dataset.id === id));
    const box = $('#c-detail');
    box.innerHTML = '<div class="hint">Loading…</div>';
    const [d, tools, msgs] = await Promise.all([api('GET', `/api/chats/${id}`), api('GET', `/api/chats/${id}/tools`), api('GET', `/api/chats/${id}/messages?offset=-30&limit=30`)]);
    this.cur = { id, info: d.info, profile: tools.profile, tools, msgs };
    this.paint();
  },
  paint() {
    const { id, info, profile, tools, msgs } = this.cur;
    const ai = profile.ai_suggestions;
    const usedTools = Object.entries(info.tools || {}).slice(0, 12);
    $('#c-detail').innerHTML = `
      <div class="card"><div class="card-head"><div style="min-width:0"><h2 style="font-size:18px">${esc(info.title)}</h2>
        <div class="sub mono" style="word-break:break-all">${esc(info.cwd)}${info.branch ? ` · ${esc(info.branch)}` : ''}</div>
        <div class="sub">${esc(new Date(info.started).toLocaleString())} → ${esc(when(info.updated))} · ${info.prompts} messages from you · ${info.replies} replies${info.cost_usd != null ? ` · $${Number(info.cost_usd).toFixed(2)} of usage` : ''}</div></div></div>
        <div class="row"><button class="btn primary" id="d-open">Open with these tools</button><button class="btn" id="d-new">New chat with these tools</button><button class="btn" id="d-cmd">Command…</button><button class="btn" id="d-proj" title="Write the skill choice into this folder's .claude/settings.local.json">Make default for this folder…</button></div></div>

      <div class="card" style="margin-top:14px"><div class="card-head"><div><h2>What it's about</h2><div class="sub">Your words — shown in the chat list and used for the suggestions</div></div>
        <button class="btn" id="d-ask">${ai ? 'Ask Claude again' : 'Ask Claude'}</button></div>
        <textarea id="d-about" style="min-height:70px;font-family:inherit;font-size:13px" placeholder="e.g. Instagram captions for the bakery launch, in their voice">${esc(profile.about || '')}</textarea>
        <div class="row" style="margin-top:8px"><button class="btn small" id="d-about-save">Save</button><span class="hint">Or press Ask Claude: it reads the chat, writes a summary and suggests tools (uses your subscription).</span></div>
        ${profile.about_auto ? `<div class="about-claude" style="margin-top:12px"><b style="font-size:12px;color:var(--accent)">Claude's summary</b><br>${esc(profile.about_auto)}
          ${!profile.about ? `<div style="margin-top:6px"><button class="btn small" id="d-use-auto">Use as my description</button></div>` : ''}</div>` : ''}
        ${ai?.missing?.length ? `<div class="alert info" style="margin-top:10px">Claude thinks this chat would also benefit from: ${esc(ai.missing.join(' · '))}. Make one on the Create page.</div>` : ''}
        ${usedTools.length ? `<h3>Tools this chat used</h3><div class="chips">${usedTools.map(([k, v]) => `<span class="chip">${esc(k)} <b>${v}</b></span>`).join('')}</div>` : ''}
      </div>

      <div class="card" style="margin-top:14px"><div class="card-head"><div><h2>Tools for this chat</h2><div class="sub">Applies when you open the chat from here. Claude Code's own settings are not changed.</div></div></div>
        <div class="tabs" id="d-tabs"><button data-t="skills" class="${(this.tab || 'skills') === 'skills' ? 'on' : ''}">Skills <span class="count">${this.count('skills')}</span></button><button data-t="mcp" class="${this.tab === 'mcp' ? 'on' : ''}">MCP servers <span class="count">${this.count('mcp')}</span></button></div>
        <div id="d-tools"></div></div>

      <div class="card" style="margin-top:14px"><div class="card-head"><div><h2>Inside the chat</h2><div class="sub">${msgs.total} messages${msgs.total > msgs.items.length ? ` · showing the last ${msgs.items.length}` : ''}</div></div>
        ${msgs.offset > 0 ? '<button class="btn small" id="d-more">Load all</button>' : ''}</div>
        <div class="msgs" id="d-msgs">${this.msgHtml(msgs.items)}</div></div>`;
    $('#d-tabs').onclick = (e) => { const b = e.target.closest('button'); if (!b) return; this.tab = b.dataset.t; $$('#d-tabs button').forEach((x) => x.classList.toggle('on', x === b)); this.paintTools(); };
    this.paintTools();
    const m = $('#d-msgs'); m.scrollTop = m.scrollHeight;
    $('#d-about-save').onclick = run(async () => { await api('POST', `/api/chats/${id}/about`, { about: $('#d-about').value }); this.cur.profile.about = $('#d-about').value; toast('Saved'); Chats.loadList(id); });
    $('#d-use-auto')?.addEventListener('click', run(async () => { await api('POST', `/api/chats/${id}/about`, { about: profile.about_auto }); this.cur.profile.about = profile.about_auto; this.paint(); Chats.loadList(id); }));
    $('#d-ask').onclick = run(async () => {
      const b = $('#d-ask'); b.disabled = true;
      try {
        const { job } = await api('POST', `/api/chats/${id}/ask-claude`);
        await waitJob(job, (s) => { b.textContent = `Claude is reading… ${s}s`; });
        await this.detail(id); toast('Claude has read the chat');
      } finally { if ($('#d-ask')) { $('#d-ask').disabled = false; } }
    });
    $('#d-more')?.addEventListener('click', run(async () => { const all = await api('GET', `/api/chats/${id}/messages?limit=5000`); $('#d-msgs').innerHTML = this.msgHtml(all.items); $('#d-more').remove(); }));
    $('#d-open').onclick = run(async () => this.open(false));
    $('#d-new').onclick = run(async () => this.open(true));
    $('#d-cmd').onclick = run(async () => commandModal(await api('GET', `/api/chats/${id}/command`)));
    $('#d-proj').onclick = run(async () => {
      if (this.cur.profile.skills == null) throw new Error('Choose the skills for this chat first');
      if (!(await confirmBox('Make this the default for the folder?', `Every chat in ${info.cwd} (also from VS Code or the desktop app) will have only these skills, through .claude/settings.local.json. A backup of that file is kept.`, 'Make default'))) return;
      const r = await api('POST', `/api/chats/${id}/apply-to-project`); toast(`Written to ${r.path}`);
    });
  },
  async open(isNew) {
    await this.flush();
    const r = await api('POST', `/api/chats/${this.cur.id}/open`, { new: isNew });
    if (S.settings?.demo) commandModal(r.command, r.message); else toast(r.message);
  },
  msgHtml(items) {
    return items.map((m) => `<div class="msg ${m.role}">${esc(m.text.length > 1800 ? m.text.slice(0, 1800) + ' …' : m.text)}${m.tools?.length ? `<div class="tools">${m.tools.slice(0, 14).map((t) => `<span>${esc(t)}</span>`).join('')}${m.tools.length > 14 ? `<span>+${m.tools.length - 14}</span>` : ''}</div>` : ''}</div>`).join('') || '<div class="hint">No messages.</div>';
  },
  count(kind) {
    const sel = this.cur.profile[kind];
    const total = kind === 'skills' ? this.cur.tools.skills.length : this.cur.tools.mcp.length;
    return sel == null ? `all ${total}` : `${sel.filter((x) => (kind === 'skills' ? this.cur.tools.skills : this.cur.tools.mcp).some((s) => s.id === x)).length}/${total}`;
  },
  paintTools() {
    const kind = this.tab || 'skills';
    const { tools, profile } = this.cur;
    const items = kind === 'skills' ? tools.skills : tools.mcp;
    const sel = profile[kind] == null ? null : new Set(profile[kind]);
    const sug = tools.suggested[kind] || [];
    const ai = profile.ai_suggestions?.[kind] || [];
    const why = {};
    sug.forEach((x) => { why[x.id] = x.why; });
    ai.forEach((x) => { why[x.id] = 'Claude: ' + x.why + (why[x.id] ? ' · ' + why[x.id] : ''); });
    const suggestedIds = [...new Set([...ai.map((x) => x.id), ...sug.map((x) => x.id)])];
    const label = (x) => kind === 'skills' ? x.invoke : x.name;
    const desc = (x) => kind === 'skills' ? x.description : `${x.type} · ${x.description || x.config?.url || [x.config?.command, ...(x.config?.args || [])].join(' ')}`;
    const groupKey = (x) => kind === 'skills' ? x.source : x.scope;
    const groups = {};
    items.forEach((x) => { (groups[groupKey(x)] ||= []).push(x); });
    const row = (x) => {
      const on = sel ? sel.has(x.id) : !(kind === 'skills' && x.source === 'library');
      return `<label class="tool-row ${on ? 'sel' : ''} ${x.enabled === false || x.approved === false ? 'dim' : ''}" data-id="${esc(x.id)}">
        <input type="checkbox" ${on ? 'checked' : ''}><div><div class="n">${suggestedIds.includes(x.id) ? '<span class="star">★</span> ' : ''}${esc(label(x))}</div>
        <div class="d">${esc(desc(x))}</div>${why[x.id] ? `<div class="why">${esc(why[x.id])}</div>` : ''}${x.enabled === false ? '<div class="why">plugin is switched off in Claude Code</div>' : ''}${x.approved === false ? '<div class="why">not approved in this project yet</div>' : ''}</div>
        <span class="hint">${esc(x.source === 'plugin' ? x.plugin : '')}</span></label>`;
    };
    const unknownSkills = kind === 'skills' && !tools.claude_skills_checked;
    $('#d-tools').innerHTML = `
      <div class="mode"><div class="seg" id="t-mode"><button data-v="normal" class="${sel ? '' : 'on'}">Normal — everything Claude Code has</button><button data-v="chosen" class="${sel ? 'on' : ''}">Only what I choose</button></div>
        ${sel ? `<span class="count">${[...sel].filter((x) => items.some((s) => s.id === x)).length} on</span>` : ''}</div>
      ${unknownSkills ? `<div class="alert info" style="margin-top:10px">Built-in skills (like code-review or pdf) aren't files on your PC. <button class="btn small" id="t-detect">Ask Claude which skills it has</button> so they can be switched off too.</div>` : ''}
      ${suggestedIds.length ? `<div class="tool-group"><h4><span>★ Suggested for this chat</span><button class="btn small" id="t-use-sug">Use only the suggested</button></h4>${suggestedIds.map((sid) => items.find((x) => x.id === sid)).filter(Boolean).map(row).join('')}</div>`
        : `<p class="hint" style="margin-top:10px">No suggestions yet${profile.about ? '' : ' — write what the chat is about, or Ask Claude'}.</p>`}
      <div class="row" style="margin-top:12px"><input type="text" id="t-filter" placeholder="Filter ${kind === 'skills' ? 'skills' : 'servers'}…" style="max-width:300px"></div>
      ${Object.entries(groups).map(([g, list]) => `<div class="tool-group" data-group="${g}"><h4><span>${esc((kind === 'skills' ? SOURCE_LABEL : SCOPE_LABEL)[g] || g)} · ${list.length}</span>
        <span class="row" style="gap:4px"><button class="btn small" data-all="${g}">All</button><button class="btn small" data-none="${g}">None</button></span></h4>${list.map(row).join('')}</div>`).join('') || '<div class="empty">None found.</div>'}`;
    const box = $('#d-tools');
    const current = () => (this.cur.profile[kind] == null ? items.filter((x) => !(kind === 'skills' && x.source === 'library')).map((x) => x.id) : [...this.cur.profile[kind]]);
    const set = (ids) => { this.cur.profile[kind] = ids; this.paintTools(); this.refreshCounts(); this.save(kind); };
    $$('#t-mode button', box).forEach((b) => { b.onclick = () => {
      if (b.dataset.v === 'normal') set(null);
      else set(suggestedIds.length ? [...suggestedIds] : current());
    }; });
    $$('.tool-row', box).forEach((r) => { r.querySelector('input').onchange = (e) => {
      const ids = new Set(current());
      if (e.target.checked) ids.add(r.dataset.id); else ids.delete(r.dataset.id);
      set([...ids]);
    }; });
    $('#t-use-sug')?.addEventListener('click', () => set([...suggestedIds]));
    $$('[data-all]', box).forEach((b) => { b.onclick = () => { const ids = new Set(current()); groups[b.dataset.all].forEach((x) => ids.add(x.id)); set([...ids]); }; });
    $$('[data-none]', box).forEach((b) => { b.onclick = () => { const ids = new Set(current()); groups[b.dataset.none].forEach((x) => ids.delete(x.id)); set([...ids]); }; });
    $('#t-filter').oninput = (e) => { const q = e.target.value.toLowerCase(); $$('.tool-row', box).forEach((r) => { r.style.display = !q || r.textContent.toLowerCase().includes(q) ? '' : 'none'; }); };
    $('#t-detect')?.addEventListener('click', run(async () => { const b = $('#t-detect'); b.disabled = true; const { job } = await api('POST', '/api/skills/detect', { cwd: this.cur.info.cwd }); await waitJob(job, (s) => { b.textContent = `Asking… ${s}s`; }); toast('Claude listed its skills'); await this.detail(this.cur.id); }));
  },
  refreshCounts() {
    $('#d-tabs').innerHTML = `<button data-t="skills" class="${(this.tab || 'skills') === 'skills' ? 'on' : ''}">Skills <span class="count">${this.count('skills')}</span></button><button data-t="mcp" class="${this.tab === 'mcp' ? 'on' : ''}">MCP servers <span class="count">${this.count('mcp')}</span></button>`;
  },
  saveTimer: null,
  pending: {},
  save(kind) {
    this.pending[kind] = this.cur.profile[kind];
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => this.flush().then(() => toast('Saved for this chat')).catch((e) => toast(e.message, true)), 500);
  },
  async flush() {
    clearTimeout(this.saveTimer);
    if (!Object.keys(this.pending).length) return;
    const body = this.pending; this.pending = {};
    await api('POST', `/api/chats/${this.cur.id}/tools`, body);
    Chats.loadList(this.cur.id);
  },
};

function commandModal(c, message) {
  modal(`<h2>Open this chat with its tools</h2>${message ? `<div class="alert info">${esc(message)}</div>` : ''}
    <p class="sub">${c.notes.map(esc).join(' · ') || 'Normal tools (nothing chosen yet).'}</p>
    <h3 class="sub" style="margin:12px 0 6px">PowerShell (Windows)</h3><pre class="cmd">${esc(c.powershell)}</pre>
    <h3 class="sub" style="margin:12px 0 6px">macOS / Linux</h3><pre class="cmd">${esc(c.shell)}</pre>
    <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="btn" data-ps>Copy PowerShell</button><button class="btn" data-sh>Copy shell</button><button class="btn primary" data-x>Close</button></div>`, (m) => {
    $('[data-ps]', m).onclick = () => copy(c.powershell);
    $('[data-sh]', m).onclick = () => copy(c.shell);
    $('[data-x]', m).onclick = closeModal;
  }, true);
}

// =========================================================================================================
// Skills
// =========================================================================================================

function projectOptions(selected = '', none = 'No project') {
  return `<option value="">${none}</option>${S.projects.map((p) => `<option value="${esc(p.cwd)}" ${selected === p.cwd ? 'selected' : ''}>${esc(p.cwd)}</option>`).join('')}`;
}

const Skills = {
  cwd: '',
  async render() {
    if (!S.projects.length) S.projects = await api('GET', '/api/projects').catch(() => []);
    const data = await api('GET', `/api/skills?cwd=${encodeURIComponent(this.cwd)}`);
    const groups = {};
    data.skills.forEach((s) => { (groups[s.source] ||= []).push(s); });
    $('#page').innerHTML = `<div class="page-head"><div><h1>Skills</h1><p>Every skill Claude Code can use on this PC. Open one to read or edit it; make new ones on the Create page.</p></div>
      <div class="row"><button class="btn" id="s-detect">Ask Claude which skills it has</button><button class="btn primary" id="s-new">New skill</button></div></div>
      <div class="row" style="margin-bottom:12px"><select id="s-proj" style="max-width:420px">${projectOptions(this.cwd, 'Show project skills for…')}</select><input type="text" id="s-filter" placeholder="Filter…" style="max-width:260px">
        <span class="hint">${data.claude.checked ? `Claude listed its skills: ${esc(data.claude.checked)}` : 'Built-in skills not listed yet'}</span></div>
      ${Object.entries(groups).map(([g, list]) => `<div class="card" style="margin-bottom:12px"><h2>${esc(SOURCE_LABEL[g] || g)} <span class="count">${list.length}</span></h2>
        <div style="margin-top:10px">${list.map((s) => `<div class="tool-row" data-id="${esc(s.id)}" style="grid-template-columns:1fr auto"><div><div class="n">${esc(s.invoke)}${s.user_only ? ' <span class="hint">(only when you call it)</span>' : ''}</div><div class="d">${esc(s.description)}</div></div>
          <span class="hint">${s.enabled === false ? 'plugin off' : ''}</span></div>`).join('')}</div></div>`).join('') || '<div class="empty">No skills found.</div>'}`;
    $('#s-proj').onchange = (e) => { this.cwd = e.target.value; this.render(); };
    $('#s-filter').oninput = (e) => { const q = e.target.value.toLowerCase(); $$('.tool-row').forEach((r) => { r.style.display = !q || r.textContent.toLowerCase().includes(q) ? '' : 'none'; }); };
    $$('.tool-row').forEach((r) => { r.onclick = run(() => skillModal(r.dataset.id, this.cwd)); });
    $('#s-new').onclick = () => newSkillModal();
    $('#s-detect').onclick = run(async () => { const b = $('#s-detect'); b.disabled = true; const { job } = await api('POST', '/api/skills/detect', { cwd: this.cwd }); const r = await waitJob(job, (s) => { b.textContent = `Asking Claude… ${s}s`; }); toast(`Claude has ${r.skills.length} skills`); this.render(); });
  },
};

async function skillModal(id, cwd) {
  const { skill, text } = await api('GET', `/api/skills/text?id=${encodeURIComponent(id)}&cwd=${encodeURIComponent(cwd || '')}`);
  const editable = ['library', 'personal', 'project'].includes(skill.source);
  modal(`<h2>${esc(skill.invoke)}</h2><p class="sub mono" style="word-break:break-all">${esc(skill.path || 'inside Claude Code')}</p>
    <textarea class="code" id="sk-text" ${editable ? '' : 'readonly'}>${esc(text)}</textarea>
    <div class="row spread" style="margin-top:12px"><div class="row">${skill.path ? `<select id="sk-to" style="width:auto"><option value="library">Copy to library</option><option value="personal">Copy to my skills</option>${S.projects.map((p) => `<option value="project|${esc(p.cwd)}">Copy to ${esc(short(p.cwd))}</option>`).join('')}</select><button class="btn" id="sk-copy">Copy</button>` : ''}
      ${editable ? '<button class="btn danger" id="sk-del">Delete</button>' : ''}</div>
      <div class="row"><button class="btn" data-x>Close</button>${editable ? '<button class="btn primary" id="sk-save">Save</button>' : ''}</div></div>`, (m) => {
    $('[data-x]', m).onclick = closeModal;
    $('#sk-save', m)?.addEventListener('click', run(async () => { await api('POST', '/api/skills/text', { id, cwd, text: $('#sk-text', m).value }); toast('Saved'); closeModal(); if (S.page === 'skills') Skills.render(); }));
    $('#sk-copy', m)?.addEventListener('click', run(async () => { const [scope, to] = $('#sk-to', m).value.split('|'); await api('POST', '/api/skills/copy', { id, cwd, scope, to_cwd: to || '' }); toast('Copied'); closeModal(); if (S.page === 'skills') Skills.render(); }));
    $('#sk-del', m)?.addEventListener('click', run(async () => { if (!(await confirmBox('Delete this skill?', 'It moves to Tools Control\'s trash folder (data/trash), so it can be recovered.', 'Delete', true))) return; await api('POST', '/api/skills/delete', { id, cwd }); toast('Deleted'); if (S.page === 'skills') Skills.render(); }));
  }, true);
}

function newSkillModal(prefill = {}) {
  modal(`<h2>New skill</h2><div class="stack">
    <label class="field"><span>Describe what the skill should do — Claude can draft it</span><textarea id="ns-req" style="font-family:inherit;min-height:60px" placeholder="e.g. Write Instagram captions in a client's brand voice with hashtags and a call to action">${esc(prefill.request || '')}</textarea></label>
    <div class="row"><button class="btn" id="ns-draft">Draft with Claude</button><span class="hint">or fill in below yourself</span></div>
    <label class="field"><span>Name (lowercase-with-hyphens)</span><input type="text" id="ns-name" value="${esc(prefill.name || '')}"></label>
    <label class="field"><span>Description — what it does and when Claude should use it</span><textarea id="ns-desc" style="font-family:inherit;min-height:56px">${esc(prefill.description || '')}</textarea></label>
    <label class="field"><span>Instructions (Markdown)</span><textarea class="code" id="ns-body" style="min-height:200px">${esc(prefill.body || '')}</textarea></label>
    <label class="field"><span>Where</span><select id="ns-scope"><option value="library">Tools Control library — only in chats where you switch it on</option><option value="personal">My skills — every chat</option>${S.projects.map((p) => `<option value="project|${esc(p.cwd)}">Project ${esc(short(p.cwd))} — chats in that folder</option>`).join('')}</select></label>
    <div class="row" style="justify-content:flex-end"><button class="btn" data-x>Cancel</button><button class="btn primary" id="ns-save">Create skill</button></div></div>`, (m) => {
    $('[data-x]', m).onclick = closeModal;
    $('#ns-draft', m).onclick = run(async () => {
      const b = $('#ns-draft', m); b.disabled = true;
      try {
        const { job } = await api('POST', '/api/skills/draft', { request: $('#ns-req', m).value });
        const r = await waitJob(job, (s) => { b.textContent = `Claude is writing… ${s}s`; });
        $('#ns-name', m).value = r.name; $('#ns-desc', m).value = r.description; $('#ns-body', m).value = r.body;
      } finally { b.disabled = false; b.textContent = 'Draft with Claude'; }
    });
    $('#ns-save', m).onclick = run(async () => {
      const [scope, cwd] = $('#ns-scope', m).value.split('|');
      const s = await api('POST', '/api/skills', { name: $('#ns-name', m).value, description: $('#ns-desc', m).value, body: $('#ns-body', m).value, scope, cwd: cwd || '' });
      closeModal(); toast(`Skill ${s.invoke} created`); if (S.page === 'skills') Skills.render();
    });
  }, true);
}

// =========================================================================================================
// MCP servers
// =========================================================================================================

const Mcp = {
  cwd: '',
  async render() {
    if (!S.projects.length) S.projects = await api('GET', '/api/projects').catch(() => []);
    const [list, self] = await Promise.all([api('GET', `/api/mcp?cwd=${encodeURIComponent(this.cwd)}`), api('GET', '/api/self-mcp')]);
    this.list = list;
    const groups = {};
    list.forEach((s) => { (groups[s.scope] ||= []).push(s); });
    $('#page').innerHTML = `<div class="page-head"><div><h1>MCP servers</h1><p>Every MCP server Claude Code knows on this PC, plus your library. Test a connection, try a tool, connect a server to Claude Code.</p></div>
      <div class="row"><button class="btn" id="m-import">Paste JSON…</button><button class="btn primary" id="m-add">Add server</button></div></div>
      <div class="card" style="margin-bottom:12px"><div class="card-head"><div><h2>Tools Control itself</h2><div class="sub">Lets Claude look up your chats and choose their tools from inside any conversation.</div></div>
        ${self.connected ? '<span class="badge ok">Connected</span>' : '<button class="btn primary" id="m-self">Connect to Claude Code</button>'}</div><pre class="cmd">${esc(self.command)}</pre></div>
      <div class="row" style="margin-bottom:12px"><select id="m-proj" style="max-width:420px">${projectOptions(this.cwd, 'Show project servers for…')}</select></div>
      ${Object.entries(groups).map(([g, items]) => `<div class="card" style="margin-bottom:12px"><h2>${esc(SCOPE_LABEL[g] || g)} <span class="count">${items.length}</span></h2>
        <div style="margin-top:10px">${items.map((s) => `<div class="tool-group" style="margin-top:6px"><div class="tool-row" style="grid-template-columns:1fr auto;cursor:default">
          <div><div class="n">${esc(s.name)} <span class="chip">${esc(s.type)}</span>${s.blocked ? ' <span class="badge bad">blocked</span>' : s.approved === false ? ' <span class="badge warn">not approved</span>' : ''}</div>
            <div class="d mono">${esc(s.config.url || [s.config.command, ...(s.config.args || [])].join(' '))}</div>${s.description ? `<div class="d">${esc(s.description)}</div>` : ''}</div>
          <div class="row" style="gap:6px;justify-content:flex-end">
            <button class="btn small" data-test="${esc(s.id)}">Test</button>
            ${g === 'library' ? `<button class="btn small" data-edit="${esc(s.name)}">Edit</button><button class="btn small" data-connect="${esc(s.id)}">Connect…</button><button class="btn small danger" data-del="${esc(s.name)}">Delete</button>` : ''}
            ${['user', 'local', 'project'].includes(g) ? `<button class="btn small danger" data-disc="${esc(s.id)}">Disconnect</button>` : ''}</div></div>
          <div id="res-${esc(s.id.replace(/[^\w-]/g, '_'))}"></div></div>`).join('')}</div></div>`).join('') || '<div class="empty">No MCP servers yet.</div>'}
      <p class="hint">Connectors you added on claude.ai (Gmail, Drive…) are managed there and are not listed here.</p>`;
    $('#m-proj').onchange = (e) => { this.cwd = e.target.value; this.render(); };
    $('#m-add').onclick = () => serverModal();
    $('#m-import').onclick = () => importModal();
    $('#m-self')?.addEventListener('click', run(async () => { const r = await api('POST', '/api/self-mcp/connect'); toast(`Connected (${r.path})`); this.render(); }));
    $('#page').onclick = run(async (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      const d = b.dataset;
      if (d.test) await this.test(d.test, b);
      if (d.edit) serverModal(await api('GET', `/api/mcp/library/${encodeURIComponent(d.edit)}`));
      if (d.del && await confirmBox(`Delete ${d.del} from your library?`, 'Chats that had it switched on will skip it.', 'Delete', true)) { await api('DELETE', `/api/mcp/library/${encodeURIComponent(d.del)}`); this.render(); }
      if (d.connect) connectModal(d.connect);
      if (d.disc) {
        const s = this.list.find((x) => x.id === d.disc);
        if (await confirmBox(`Disconnect ${s.name}?`, `It is removed from ${s.where}. A backup of that file is kept next to it.`, 'Disconnect', true)) { await api('POST', '/api/mcp/uninstall', { id: d.disc, cwd: this.cwd }); toast('Disconnected'); this.render(); }
      }
      if (d.try) tryToolModal(d.try, d.tool, JSON.parse(d.schema || '{}'), this.cwd);
    });
  },
  async test(id, btn) {
    const box = $(`#res-${id.replace(/[^\w-]/g, '_')}`);
    btn.disabled = true; btn.textContent = 'Testing…';
    try {
      const r = await api('POST', '/api/mcp/test', { id, cwd: this.cwd });
      box.innerHTML = r.ok ? `<div class="alert info" style="margin:4px 0 8px"><b class="ok-text">Connected</b> to ${esc(r.server?.name || '')} in ${r.ms} ms · ${r.tools.length} tools
          <div style="margin-top:8px">${r.tools.map((t) => `<div class="row spread" style="padding:4px 0;border-top:1px solid #1f3554"><div><span class="mono">${esc(t.name)}</span> <span class="hint">${esc(t.description.slice(0, 160))}</span></div>
          <button class="btn small" data-try="${esc(id)}" data-tool="${esc(t.name)}" data-schema="${esc(JSON.stringify(t.input || {}))}">Try</button></div>`).join('')}</div></div>`
        : `<div class="alert bad" style="margin:4px 0 8px">${esc(r.error)}</div>`;
    } finally { btn.disabled = false; btn.textContent = 'Test'; }
  },
};

function tryToolModal(id, tool, schema, cwd) {
  const props = schema.properties || {};
  const example = Object.fromEntries(Object.entries(props).map(([k, v]) => [k, v.type === 'number' || v.type === 'integer' ? 0 : v.type === 'boolean' ? false : v.type === 'array' ? [] : v.type === 'object' ? {} : '']));
  modal(`<h2>Try ${esc(tool)}</h2><label class="field"><span>Arguments (JSON)</span><textarea class="code" id="tt-args" style="min-height:140px">${esc(JSON.stringify(example, null, 2))}</textarea></label>
    <div class="row" style="justify-content:flex-end;margin-top:10px"><button class="btn" data-x>Close</button><button class="btn primary" id="tt-run">Run</button></div><pre class="cmd" id="tt-out" style="margin-top:12px;display:none;max-height:40vh;overflow:auto"></pre>`, (m) => {
    $('[data-x]', m).onclick = closeModal;
    $('#tt-run', m).onclick = run(async () => {
      const out = $('#tt-out', m); out.style.display = 'block'; out.textContent = 'Running…';
      const r = await api('POST', '/api/mcp/call', { id, tool, arguments: JSON.parse($('#tt-args', m).value || '{}'), cwd });
      out.textContent = (r.content || []).map((c) => c.text ?? JSON.stringify(c)).join('\n') || JSON.stringify(r, null, 2);
    });
  }, true);
}

function serverModal(s = {}) {
  const cfg = s.config || {};
  const remote = !!cfg.url;
  const kv = (o) => Object.entries(o || {}).map(([k, v]) => `${k}=${v}`).join('\n');
  modal(`<h2>${s.name ? 'Edit server' : 'Add an MCP server'}</h2><div class="stack">
    <label class="field"><span>Name</span><input type="text" id="sv-name" value="${esc(s.name || '')}" placeholder="e.g. playwright"></label>
    <label class="field"><span>What it's for (helps the suggestions)</span><input type="text" id="sv-desc" value="${esc(s.description || '')}" placeholder="e.g. control a browser: open pages, click, read"></label>
    <div class="seg" id="sv-kind"><button data-v="stdio" class="${remote ? '' : 'on'}">Runs on this PC (command)</button><button data-v="remote" class="${remote ? 'on' : ''}">Remote (URL)</button></div>
    <div id="sv-stdio" style="display:${remote ? 'none' : 'block'}" class="stack">
      <label class="field"><span>Command</span><input type="text" id="sv-cmd" value="${esc(cfg.command || '')}" placeholder="npx"></label>
      <label class="field"><span>Arguments (one per line)</span><textarea id="sv-args" style="min-height:60px">${esc((cfg.args || []).join('\n'))}</textarea></label>
      <label class="field"><span>Environment (KEY=value per line, e.g. API keys)</span><textarea id="sv-env" style="min-height:50px">${esc(kv(cfg.env))}</textarea></label></div>
    <div id="sv-remote" style="display:${remote ? 'block' : 'none'}" class="stack">
      <div class="row" style="gap:10px"><label class="field" style="flex:1"><span>URL</span><input type="text" id="sv-url" value="${esc(cfg.url || '')}" placeholder="https://…/mcp"></label>
        <label class="field" style="width:120px"><span>Transport</span><select id="sv-type"><option value="http" ${cfg.type !== 'sse' ? 'selected' : ''}>http</option><option value="sse" ${cfg.type === 'sse' ? 'selected' : ''}>sse</option></select></label></div>
      <label class="field"><span>Headers (Name=value per line)</span><textarea id="sv-head" style="min-height:50px" placeholder="Authorization=Bearer …">${esc(kv(cfg.headers))}</textarea></label></div>
    <div id="sv-test"></div>
    <div class="row spread"><button class="btn" id="sv-try">Test connection</button><div class="row"><button class="btn" data-x>Cancel</button><button class="btn primary" id="sv-save">Save to library</button></div></div></div>`, (m) => {
    let kind = remote ? 'remote' : 'stdio';
    $$('#sv-kind button', m).forEach((b) => { b.onclick = () => { kind = b.dataset.v; $$('#sv-kind button', m).forEach((x) => x.classList.toggle('on', x === b)); $('#sv-stdio', m).style.display = kind === 'stdio' ? 'block' : 'none'; $('#sv-remote', m).style.display = kind === 'remote' ? 'block' : 'none'; }; });
    const parseKv = (t) => Object.fromEntries(t.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => { const i = l.indexOf('='); return [l.slice(0, i).trim(), l.slice(i + 1).trim()]; }).filter(([k]) => k));
    const build = () => kind === 'stdio'
      ? { command: $('#sv-cmd', m).value.trim(), args: $('#sv-args', m).value.split('\n').map((x) => x.trim()).filter(Boolean), env: parseKv($('#sv-env', m).value), ...(cfg.cwd ? { cwd: cfg.cwd } : {}) }
      : { type: $('#sv-type', m).value, url: $('#sv-url', m).value.trim(), headers: parseKv($('#sv-head', m).value) };
    $('[data-x]', m).onclick = closeModal;
    $('#sv-try', m).onclick = run(async () => {
      const box = $('#sv-test', m); box.innerHTML = '<div class="hint">Connecting… (first run of an npx server can take a minute)</div>';
      const r = await api('POST', '/api/mcp/test', { config: build(), timeout: 90 });
      box.innerHTML = r.ok ? `<div class="alert info"><b class="ok-text">Works</b> — ${r.tools.length} tools: ${esc(r.tools.map((t) => t.name).join(', '))}</div>` : `<div class="alert bad">${esc(r.error)}</div>`;
    });
    $('#sv-save', m).onclick = run(async () => { await api('POST', '/api/mcp/library', { name: $('#sv-name', m).value.trim(), config: build(), description: $('#sv-desc', m).value, old_name: s.name || '' }); closeModal(); toast('Saved to library'); if (S.page === 'mcp') Mcp.render(); });
  }, true);
}

function importModal() {
  modal(`<h2>Paste an MCP config</h2><p class="sub">From a server's README — e.g. <span class="mono">{"mcpServers": {"name": {"command": "npx", "args": [...]}}}</span>. Goes to your library.</p>
    <textarea class="code" id="im-json" style="min-height:200px"></textarea><div class="row" style="justify-content:flex-end;margin-top:10px"><button class="btn" data-x>Cancel</button><button class="btn primary" id="im-go">Add</button></div>`, (m) => {
    $('[data-x]', m).onclick = closeModal;
    $('#im-go', m).onclick = run(async () => { const r = await api('POST', '/api/mcp/import', { json: $('#im-json', m).value }); closeModal(); toast(`Added ${r.added.join(', ')}`); Mcp.render(); });
  }, true);
}

function connectModal(id) {
  modal(`<h2>Connect to Claude Code</h2><p class="sub">Library servers are already available per chat here. Connecting writes the server into Claude Code's own settings so every chat gets it (a backup of the file is kept).</p>
    <div class="stack" style="margin-top:10px"><label class="row"><input type="radio" name="cs" value="user" checked> Every project (user scope, ~/.claude.json)</label>
    <label class="row"><input type="radio" name="cs" value="project"> One project's .mcp.json:</label><select id="cs-proj">${projectOptions('', 'Choose a project…')}</select>
    <div class="row" style="justify-content:flex-end"><button class="btn" data-x>Cancel</button><button class="btn primary" id="cs-go">Connect</button></div></div>`, (m) => {
    $('[data-x]', m).onclick = closeModal;
    $('#cs-go', m).onclick = run(async () => {
      const scope = $('input[name=cs]:checked', m).value;
      const r = await api('POST', '/api/mcp/install', { id, scope, to_cwd: $('#cs-proj', m).value });
      closeModal(); toast(`Connected — written to ${r.path}`); Mcp.render();
    });
  });
}

// =========================================================================================================
// Create
// =========================================================================================================

const Create = {
  tools: [{ name: '', description: '', params: [{ name: '', type: 'string', description: '' }], body: '' }],
  render() {
    $('#page').innerHTML = `<div class="page-head"><div><h1>Create</h1><p>Make your own MCP server or skill. New ones go to your library: switch them on per chat, or connect them to Claude Code for every chat.</p></div>
      <button class="btn" id="cr-skill">New skill…</button></div>
      <div class="grid two"><div class="card stack"><h2>New MCP server</h2>
        <label class="field"><span>Name</span><input type="text" id="cr-name" placeholder="client-notes"></label>
        <label class="field"><span>What it's for</span><input type="text" id="cr-desc" placeholder="Save and look up notes about clients"></label>
        <label class="field"><span>Kind</span><select id="cr-tpl"><option value="python">Python, no packages needed (recommended)</option><option value="fastmcp">Python FastMCP (needs pip install "mcp<2")</option></select></label>
        <div id="cr-tools"></div><button class="btn" id="cr-addtool">+ Add a tool</button>
        <div class="row" style="justify-content:flex-end"><button class="btn primary" id="cr-go">Create server</button></div></div>
      <div class="card"><h2>How it works</h2><ol class="sub" style="line-height:1.8;padding-left:18px">
        <li>Name the server and list its tools: what each does and what it needs (parameters).</li>
        <li>Write the Python yourself, or leave it empty and press <b>Write the tools with Claude</b> — Claude Code writes them inside the server's folder only, then the server is tested.</li>
        <li><b>Test</b> lists the tools; <b>Try</b> runs one.</li>
        <li>Switch it on for a chat on the Chats page, or <b>Connect</b> it to Claude Code on the MCP page.</li></ol>
        <div id="cr-made"></div></div></div>`;
    this.paintTools();
    $('#cr-addtool').onclick = () => { this.read(); this.tools.push({ name: '', description: '', params: [], body: '' }); this.paintTools(); };
    $('#cr-skill').onclick = () => newSkillModal();
    $('#cr-go').onclick = run(async () => {
      this.read();
      const tools = this.tools.map((t) => ({ ...t, params: t.params.filter((p) => p.name.trim()) }));
      const r = await api('POST', '/api/mcp/create', { name: $('#cr-name').value.trim(), description: $('#cr-desc').value.trim(), template: $('#cr-tpl').value, tools });
      toast('Server created'); this.tools = [{ name: '', description: '', params: [{ name: '', type: 'string', description: '' }], body: '' }];
      this.made(r.server.name);
    });
  },
  paintTools() {
    $('#cr-tools').innerHTML = this.tools.map((t, i) => `<div class="tool-edit" data-i="${i}">
      <div class="row spread"><b class="sub">Tool ${i + 1}</b>${this.tools.length > 1 ? `<button class="icon-btn" data-rm="${i}">✕ remove</button>` : ''}</div>
      <div class="row" style="gap:8px;margin-top:6px"><input type="text" data-f="name" value="${esc(t.name)}" placeholder="tool_name" style="max-width:200px"><input type="text" data-f="description" value="${esc(t.description)}" placeholder="What it does (Claude reads this)"></div>
      <div class="sub" style="margin:8px 0 4px">Parameters</div>${t.params.map((p, j) => `<div class="param-row" data-j="${j}"><input type="text" data-p="name" value="${esc(p.name)}" placeholder="name">
        <select data-p="type">${['string', 'number', 'integer', 'boolean', 'array', 'object'].map((x) => `<option ${p.type === x ? 'selected' : ''}>${x}</option>`).join('')}</select>
        <input type="text" data-p="description" value="${esc(p.description)}" placeholder="description"><button class="icon-btn" data-prm="${j}">✕</button></div>`).join('')}
      <button class="btn small" data-padd="${i}">+ parameter</button>
      <details style="margin-top:8px"><summary class="sub">Python code (optional)</summary><textarea class="code" data-f="body" style="min-height:90px" placeholder="return f'Hello {name}'">${esc(t.body)}</textarea></details></div>`).join('');
    const box = $('#cr-tools');
    $$('[data-rm]', box).forEach((b) => { b.onclick = () => { this.read(); this.tools.splice(Number(b.dataset.rm), 1); this.paintTools(); }; });
    $$('[data-padd]', box).forEach((b) => { b.onclick = () => { this.read(); this.tools[b.dataset.padd].params.push({ name: '', type: 'string', description: '' }); this.paintTools(); }; });
    $$('[data-prm]', box).forEach((b) => { b.onclick = () => { this.read(); const i = b.closest('.tool-edit').dataset.i; this.tools[i].params.splice(Number(b.dataset.prm), 1); this.paintTools(); }; });
  },
  read() {
    $$('.tool-edit').forEach((el) => {
      const t = this.tools[el.dataset.i];
      $$('[data-f]', el).forEach((i) => { t[i.dataset.f] = i.value; });
      $$('.param-row', el).forEach((r) => { const p = t.params[r.dataset.j]; $$('[data-p]', r).forEach((i) => { p[i.dataset.p] = i.value; }); });
    });
  },
  async made(name) {
    const code = await api('GET', `/api/mcp/code/${encodeURIComponent(name)}`);
    $('#cr-made').innerHTML = `<h3>${esc(name)}</h3><p class="hint mono">${esc(code.folder)}</p>
      <label class="field"><span>Extra instructions for Claude (optional)</span><input type="text" id="cm-req" placeholder="e.g. store the notes in D:\\agency\\notes.json"></label>
      <div class="row" style="margin:8px 0"><button class="btn primary" id="cm-claude">Write the tools with Claude</button><button class="btn" id="cm-test">Test</button><button class="btn" id="cm-save">Save code</button></div>
      <div id="cm-out"></div><textarea class="code" id="cm-code">${esc(code.code)}</textarea>`;
    $('#cm-save').onclick = run(async () => { await api('POST', `/api/mcp/code/${encodeURIComponent(name)}`, { code: $('#cm-code').value }); toast('Saved'); });
    $('#cm-test').onclick = run(async () => { const r = await api('POST', '/api/mcp/test', { id: `library/${name}` }); $('#cm-out').innerHTML = r.ok ? `<div class="alert info"><b class="ok-text">Works</b> — tools: ${esc(r.tools.map((t) => t.name).join(', '))}</div>` : `<div class="alert bad">${esc(r.error)}</div>`; });
    $('#cm-claude').onclick = run(async () => {
      const b = $('#cm-claude'); b.disabled = true;
      try {
        const { job } = await api('POST', `/api/mcp/implement/${encodeURIComponent(name)}`, { request: $('#cm-req').value });
        const r = await waitJob(job, (s) => { b.textContent = `Claude is writing the tools… ${s}s`; });
        $('#cm-out').innerHTML = `<div class="alert ${r.test.ok ? 'info' : 'bad'}">${esc(r.summary)}<br><b>${r.test.ok ? `Test passed — ${r.test.tools.length} tools` : 'Test failed: ' + esc(r.test.error)}</b></div>`;
        $('#cm-code').value = (await api('GET', `/api/mcp/code/${encodeURIComponent(name)}`)).code;
      } finally { b.disabled = false; b.textContent = 'Write the tools with Claude'; }
    });
  },
};

// =========================================================================================================
// SDK & connect, Settings
// =========================================================================================================

const Sdk = {
  async render() {
    const self = await api('GET', '/api/self-mcp');
    const app = S.settings.data_dir.replace(/[\\/]data$/, '');
    const sep = app.includes('\\') ? '\\' : '/';
    $('#page').innerHTML = `<div class="page-head"><div><h1>SDK & connect</h1><p>Use Tools Control from Claude itself, from your own scripts, or from the command line.</p></div></div>
      <div class="grid two">
      <div class="card"><h2>1 · Claude can use it (MCP)</h2><p class="sub">Connect Tools Control as an MCP server; then in any chat you can say "switch on the seo skills for my bakery chat".</p>
        <pre class="cmd">${esc(self.command)}</pre><div class="row" style="margin-top:10px">${self.connected ? '<span class="badge ok">Connected</span>' : '<button class="btn primary" id="sd-connect">Connect now</button>'}</div>
        <p class="hint">Its tools: list_conversations, conversation_details, set_conversation_about, suggest_tools, list_skills, list_mcp_servers, set_conversation_tools, launch_command.</p></div>
      <div class="card"><h2>2 · Python SDK</h2><p class="sub">One file, no packages: <span class="mono">${esc(app + sep + 'sdk' + sep + 'tools_control.py')}</span></p>
        <pre class="cmd">from tools_control import ToolsControl
tc = ToolsControl()
chat = tc.chats("instagram")[0]
tc.set_about(chat["id"], "Captions for the bakery launch")
tc.use_suggested(chat["id"])            # or ask_claude=True
print(tc.command(chat["id"])["powershell"])
tc.open(chat["id"])                      # opens it in a terminal</pre></div>
      <div class="card"><h2>3 · Claude Agent SDK</h2><p class="sub">Run a chat from a script with exactly its chosen tools (<span class="mono">pip install claude-agent-sdk</span>).</p>
        <pre class="cmd">from claude_agent_sdk import ClaudeAgentOptions, query
opts = ClaudeAgentOptions(**tc.agent_options(chat["id"]))
async for msg in query(prompt="What's left to do?", options=opts):
    print(msg)</pre><p class="hint">Examples: sdk/examples/agent_with_chat_tools.py and in_process_mcp_tool.py (an agent with its own in-process MCP tool).</p></div>
      <div class="card"><h2>4 · Command line</h2><pre class="cmd">python sdk${sep}toolsctl.py chats bakery
python sdk${sep}toolsctl.py suggest 00000000 --claude
python sdk${sep}toolsctl.py use-suggested 00000000
python sdk${sep}toolsctl.py open 00000000</pre></div></div>`;
    $('#sd-connect')?.addEventListener('click', run(async () => { await api('POST', '/api/self-mcp/connect'); toast('Connected'); this.render(); }));
  },
};

const Settings = {
  async render() {
    const s = S.settings = await api('GET', '/api/settings');
    $('#page').innerHTML = `<div class="page-head"><div><h1>Settings</h1></div></div><div class="grid two"><div class="card stack">
      <label class="field"><span>Claude Code folder (empty = automatic)</span><input type="text" id="st-dir" value="${esc(s.claude_dir)}" placeholder="C:\\Users\\Harry\\.claude"></label>
      <label class="field"><span>claude executable (empty = automatic)</span><input type="text" id="st-exe" value="${esc(s.claude_exe)}"></label>
      <label class="field"><span>"Open" starts Claude in</span><select id="st-term"><option value="powershell" ${s.terminal === 'powershell' ? 'selected' : ''}>PowerShell window</option><option value="wt" ${s.terminal === 'wt' ? 'selected' : ''}>Windows Terminal</option><option value="cmd" ${s.terminal === 'cmd' ? 'selected' : ''}>Command Prompt</option></select></label>
      <label class="field"><span>Model for summaries and suggestions</span><select id="st-model">${['sonnet', 'opus', 'haiku'].map((m) => `<option ${s.summary_model === m ? 'selected' : ''}>${m}</option>`).join('')}</select></label>
      <div class="row"><button class="btn primary" id="st-save">Save</button></div></div>
      <div class="card"><h2>What it reads and writes</h2><dl class="kv" style="margin-top:10px">
        <dt>Chats & skills</dt><dd>${esc(s.claude_dir_used)}</dd><dt>MCP config</dt><dd>${esc(s.claude_json_used)}</dd><dt>claude</dt><dd>${esc(s.claude_found)}</dd><dt>This app's data</dt><dd>${esc(s.data_dir)}</dd></dl>
        <ul class="sub" style="padding-left:18px;line-height:1.7;margin-top:14px"><li>Chats are only read, never changed.</li><li>Per-chat choices live in this app's data folder and apply when you open a chat from here.</li>
        <li>It writes to Claude Code's files only when you press Connect, Disconnect or Make default — and keeps a <span class="mono">.tools-control.bak</span> copy.</li></ul></div></div>`;
    $('#st-save').onclick = run(async () => { await api('POST', '/api/settings', { claude_dir: $('#st-dir').value.trim(), claude_exe: $('#st-exe').value.trim(), terminal: $('#st-term').value, summary_model: $('#st-model').value }); S.settings = await api('GET', '/api/settings'); renderNav(); toast('Saved'); });
  },
};

// ---- routing ---------------------------------------------------------------------------------------------

const VIEWS = { chats: Chats, skills: Skills, mcp: Mcp, create: Create, sdk: Sdk, settings: Settings };

async function route() {
  if (Chats.cur && Object.keys(Chats.pending).length) await Chats.flush().catch(() => {});
  const [page, arg] = (location.hash.slice(1) || 'chats').split('/');
  S.page = VIEWS[page] ? page : 'chats';
  closeModal();
  $('#page').onclick = null;
  renderNav();
  if (S.page === 'chats' && $('#c-list') && S.lastPage === 'chats' && arg) { S.lastPage = 'chats'; Chats.detail(arg).catch((e) => toast(e.message, true)); return; }
  S.lastPage = S.page;
  try { await VIEWS[S.page].render(arg); } catch (e) { $('#page').innerHTML = `<div class="alert bad">${esc(e.message)}</div>`; }
}

(async function start() {
  try { S.settings = await api('GET', '/api/settings'); } catch { S.settings = {}; }
  window.addEventListener('hashchange', route);
  route();
})();
