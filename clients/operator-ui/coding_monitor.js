/* Phase 29.22: owner view of coding-agent projects and sessions. All text is
   rendered with textContent; nothing is kept in localStorage. */
function createCodingMonitor({api, isLoggedIn}) {
  const el = id => document.getElementById(id);
  const root = '/coding-agents';
  const POLL_MS = 15000;
  const ACTIVE = new Set(['created', 'starting', 'running', 'waiting_for_input', 'waiting_for_permission', 'rate_limited']);
  let timer = null;
  let projects = [];
  const open = new Map(); // session id -> 'events' | 'usage'
  function say(text) { el('coding-status').textContent = text; }
  function fail(error) { if (isLoggedIn()) say(error.message); }
  function node(tag, text, className) {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (className) n.className = className;
    return n;
  }
  const when = value => value ? new Date(value).toLocaleString() : '';
  function button(text, onClick, secondary = true) {
    const b = node('button', text); b.type = 'button';
    if (secondary) b.className = 'secondary';
    b.addEventListener('click', async () => {
      b.disabled = true;
      try { await onClick(); } catch (error) { fail(error); } finally { b.disabled = false; }
    });
    return b;
  }
  function dimensionText(d) {
    const reset = d.resets_at ? ' (resets ' + when(d.resets_at) + ')' : '';
    return d.name.replaceAll('_', ' ') + ': ' + d.value + ' ' + d.unit + reset;
  }
  async function loadAllowance() {
    const box = el('coding-allowance');
    try {
      const allowance = await api(root + '/allowance/claude-code');
      if (!isLoggedIn()) return;
      if (!allowance.windows.length) {
        box.textContent = 'No allowance reading available. Save a Claude account usage credential in Settings · Accounts to see the live 5-hour and weekly figures.';
        return;
      }
      const label = allowance.source === 'live' ? 'Live from your Claude account' : 'Last reported by Claude Code';
      box.replaceChildren(node('strong', label), ...allowance.windows.map(d => node('div', dimensionText(d))));
    } catch (error) { if (isLoggedIn()) box.textContent = 'Allowance unavailable: ' + error.message; }
  }
  function renderProjects() {
    const list = el('coding-projects');
    list.replaceChildren(...projects.map(p => node('li', p.name + ' — ' + p.repository_path + ' (' + p.default_branch + ', ' + p.provider + ')')));
    if (!projects.length) list.append(node('li', 'No projects yet. Add one below.', 'muted'));
    const select = el('coding-session-project');
    const current = select.value;
    select.replaceChildren(...projects.map(p => { const o = node('option', p.name); o.value = p.id; return o; }));
    if (projects.some(p => p.id === current)) select.value = current;
  }
  async function renderDetail(session, kind, container) {
    try {
      if (kind === 'events') {
        const events = await api(root + '/sessions/' + session.id + '/events');
        container.replaceChildren(...events.map(e => node('div', when(e.timestamp) + ' · ' + e.type.replaceAll('_', ' ') + ' · ' + e.summary)));
        if (!events.length) container.textContent = 'No events recorded.';
      } else {
        const usage = await api(root + '/sessions/' + session.id + '/usage');
        container.replaceChildren(...usage.dimensions.map(d => node('div', dimensionText(d))));
        if (!usage.dimensions.length) container.textContent = 'No usage figures recorded for this session.';
      }
    } catch (error) { container.textContent = error.message; }
  }
  function renderSessions(sessions) {
    const box = el('coding-sessions');
    const names = Object.fromEntries(projects.map(p => [p.id, p.name]));
    box.replaceChildren();
    if (!sessions.length) { box.append(node('p', 'No sessions yet. Start one above.', 'muted')); return; }
    for (const s of sessions) {
      const card = node('div', undefined, 'card');
      card.append(
        node('strong', (names[s.project_id] || 'Unknown project') + ' — ' + s.status.replaceAll('_', ' ')),
        node('p', s.task_summary),
        node('p', 'Started ' + when(s.started_at) + ' · last activity ' + when(s.last_activity_at) + (s.branch ? ' · ' + s.branch : ''), 'muted'),
      );
      if (s.last_event) card.append(node('p', s.last_event, 'muted'));
      const detail = node('div', undefined, 'muted');
      const toggle = kind => button(kind === 'events' ? 'Events' : 'Usage', async () => {
        if (open.get(s.id) === kind) { open.delete(s.id); detail.replaceChildren(); return; }
        open.set(s.id, kind); await renderDetail(s, kind, detail);
      });
      card.append(toggle('events'), toggle('usage'));
      if (ACTIVE.has(s.status)) {
        card.append(
          button('Refresh status', async () => { await api(root + '/sessions/' + s.id + '/refresh', {method: 'POST'}); await load(); }),
          button('Stop', async () => {
            if (!window.confirm('Stop this coding session?')) return;
            await api(root + '/sessions/' + s.id + '/stop', {method: 'POST'}); await load();
          }),
        );
      }
      card.append(detail);
      box.append(card);
      if (open.has(s.id)) void renderDetail(s, open.get(s.id), detail);
    }
  }
  async function loadTerminal() {
    const box = el('coding-terminal-sessions');
    try {
      const sessions = await api(root + '/terminal-sessions');
      if (!isLoggedIn()) return;
      box.replaceChildren();
      if (!sessions.length) { box.append(node('p', 'No terminal sessions found. The host session history may not be mounted (CLAUDE_PROJECTS_DIR).', 'muted')); return; }
      for (const s of sessions) {
        const card = node('div', undefined, 'card');
        card.append(
          node('strong', (s.active ? 'Active — ' : '') + (s.title || s.session_id)),
          node('p', (s.project_path || 'Unknown folder') + (s.git_branch ? ' · ' + s.git_branch : '') + ' · last activity ' + when(s.last_activity_at), 'muted'),
        );
        if (s.last_prompt) card.append(node('p', 'Last prompt: ' + s.last_prompt, 'muted'));
        box.append(card);
      }
    } catch (error) { if (isLoggedIn()) box.textContent = 'Terminal sessions unavailable: ' + error.message; }
  }
  async function load() {
    if (!isLoggedIn()) return;
    void loadTerminal();
    try {
      const [p, sessions] = await Promise.all([api(root + '/projects'), api(root + '/sessions')]);
      if (!isLoggedIn()) return;
      projects = p; renderProjects(); renderSessions(sessions); say('');
    } catch (error) { fail(error); }
    void loadAllowance();
  }
  el('coding-refresh').addEventListener('click', () => void load());
  el('coding-project-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      await api(root + '/projects', {method: 'POST', body: JSON.stringify({
        name: el('coding-project-name').value.trim(), repository_path: el('coding-project-path').value.trim(),
        default_branch: el('coding-project-branch').value.trim() || 'main', provider: el('coding-project-provider').value,
      })});
      el('coding-project-name').value = ''; el('coding-project-path').value = '';
      say('Project added.'); await load();
    } catch (error) { fail(error); }
  });
  el('coding-session-form').addEventListener('submit', async event => {
    event.preventDefault();
    const project = projects.find(p => p.id === el('coding-session-project').value);
    if (!project) { say('Add a project first.'); return; }
    const note = project.provider === 'simulated' ? '' : ' This spends Claude usage, and with an API key it can change files in the repository.';
    if (!window.confirm('Start a coding session on "' + project.name + '"?' + note)) return;
    try {
      await api(root + '/sessions', {method: 'POST', body: JSON.stringify({
        project_id: project.id, task_summary: el('coding-session-task').value.trim(),
        branch: el('coding-session-branch').value.trim() || null,
      })});
      el('coding-session-task').value = ''; el('coding-session-branch').value = '';
      say('Session started.'); await load();
    } catch (error) { fail(error); }
  });
  function stop() { if (timer !== null) { clearInterval(timer); timer = null; } }
  function start() { stop(); void load(); timer = setInterval(() => void load(), POLL_MS); }
  function reset() {
    stop(); projects = []; open.clear();
    for (const id of ['coding-projects', 'coding-sessions', 'coding-terminal-sessions']) el(id).replaceChildren();
    el('coding-allowance').textContent = ''; say('');
  }
  return {start, stop, reset};
}
