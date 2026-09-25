const $ = id => document.getElementById(id);
// Relative to the mounted UI, so direct hub and /hub/ reverse-proxy URLs work.
const base = new URL('../', window.location.href).pathname.replace(/\/$/, '');
let loggedIn = false;
let polling = false;
let selectedUser = null;
let hasSavedCloud = false;
let routingEdited = false;
const chat = createChat({
  api, isLoggedIn: () => loggedIn,
  onUserChange(user) {
    if ($('user-id').value !== user) {
      $('user-id').value = user; selectedUser = null; $('session-fields').disabled = true;
    }
  },
  onBusyChange(busy) {
    $('user-id').disabled = busy;
    $('session-select').querySelector('button').disabled = busy;
  },
});
const accounts = createAccounts({api, isLoggedIn: () => loggedIn});
const motionSettings = createMotionSettings();
const voice = createVoice({api, isLoggedIn: () => loggedIn, chat});
function showView(view) {
  const isChat = view === 'chat';
  $('chat-pane').hidden = !isChat; $('overview-pane').hidden = view !== 'overview';
  $('accounts-pane').hidden = view !== 'accounts';
  for (const name of ['chat', 'overview', 'accounts']) {
    $(name + '-tab').setAttribute('aria-pressed', String(name === view));
    $(name + '-tab').classList.toggle('secondary', name !== view);
  }
  if (isChat) void chat.refreshSession();
  if (view === "accounts") { void accounts.load(); void motionSettings.load(); }
}
$('accounts-tab').addEventListener('click', () => showView('accounts'));
$('chat-tab').addEventListener('click', () => showView('chat'));
$('overview-tab').addEventListener('click', () => showView('overview'));
function notice(text) { $('notice').textContent = text; }
function showLogin() {
  loggedIn = false; selectedUser = null;
  $('login-panel').hidden = false; $('dashboard').hidden = true; $('nav').hidden = true;
  $('api-key').value = ''; $('cloud-api-key').value = ''; $('websearch-api-key').value = ''; for (const name of HOSTED_SEARCH) $(`websearch-${name}-api-key`).value = ''; $('password').value = '';
  $('search-log-dialog').close(); $('search-log-entries').replaceChildren();
  chat.reset(); accounts.reset(); voice.reset(); motionSettings.reset(); showView('overview');
}
async function api(path, options = {}) {
  const response = await fetch(base + path, {
    ...options, cache: 'no-store', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json', 'X-Reachy-CSRF': '1', ...options.headers},
  });
  if (!response.ok) {
    if (response.status === 401) showLogin();
    let detail = '';
    try { detail = (await response.json()).detail; } catch { /* Non-JSON gateway failure. */ }
    const error = new Error(typeof detail === 'string' && detail ? detail : `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}
function submit(form, action) {
  $(form).addEventListener('submit', async event => {
    event.preventDefault(); const button = event.submitter; if (button) button.disabled = true;
    try { await action(); } catch (error) { notice(error.message); }
    finally { if (button) button.disabled = false; }
  });
}
function renderSettings(config) {
  hasSavedCloud = Boolean(config.cloud); routingEdited = false;
  $('cloud-base-url').value = config.cloud?.base_url || '';
  $('cloud-model').value = config.cloud?.model || '';
  $('cloud-key-state').textContent = config.cloud?.api_key ? `Saved key: ${config.cloud.api_key}` : 'No saved key';
  $('cloud-api-key').value = ''; $('cloud-clear-key').checked = false;
  $('llm-routing').value = config.routing?.mode || 'local_only';
  $('base-url').value = config.local?.base_url || '';
  $('model').value = config.local?.model || '';
  $('key-state').textContent = config.local?.api_key ? `Saved key: ${config.local.api_key}` : 'No saved key';
  $('api-key').value = ''; $('clear-key').checked = false; $('llm-fields').disabled = false;
}
const DEFAULT_PERSONA_NAME = 'Reachy';
const DEFAULT_PERSONA_PROMPT = 'You are Reachy, an embodied work assistant. You help with tasks, calendar, email, reminders, and general questions. Keep replies concise and practical, and be clear when something is outside what you can do.';
function renderPersona(config) {
  $('persona-name').value = config.name || '';
  $('persona-prompt').value = config.system_prompt || '';
  $('persona-location').value = config.location || '';
  $('persona-timezone').value = config.timezone || 'UTC';
  $('persona-fields').disabled = false;
}
const HOSTED_SEARCH = ['brave', 'exa', 'tavily'];
function updateWebsearchFallbackFields() {
  // Built-in SearXNG needs no base URL or API key at all — Companion Core
  // already knows its internal address (Phase 24 cleanup).
  const fallback = $('websearch-fallback').value;
  $('websearch-base-url-field').hidden = fallback !== 'searxng';
  $('websearch-key-fields').hidden = fallback !== 'searxng';
}
function renderWebsearch(config) {
  $('websearch-policy').value = config.policy || 'off';
  for (const name of HOSTED_SEARCH) {
    const hosted = (config.hosted || {})[name] || {};
    $(`websearch-${name}-enabled`).checked = !!hosted.enabled;
    $(`websearch-${name}-key-state`).textContent = hosted.api_key ? `Saved key: ${hosted.api_key}` : 'No saved key';
    $(`websearch-${name}-api-key`).value = ''; $(`websearch-${name}-clear-key`).checked = false;
    $(`websearch-${name}-limit`).value = hosted.monthly_limit ?? '';
    const used = config.usage?.used?.[name];
    $(`websearch-${name}-usage`).textContent = used === undefined ? '' : `Used ${used} of ${hosted.monthly_limit} in ${config.usage.period} (UTC)`;
  }
  $('websearch-fallback').value = config.fallback || 'builtin_searxng';
  $('websearch-base-url').value = config.base_url || '';
  $('websearch-key-state').textContent = config.api_key ? `Saved key: ${config.api_key}` : 'No saved key';
  $('websearch-api-key').value = ''; $('websearch-clear-key').checked = false;
  $('websearch-result-count').value = config.result_count ?? 5;
  $('websearch-fields').disabled = false;
  updateWebsearchFallbackFields();
}
$('websearch-fallback').addEventListener('change', updateWebsearchFallbackFields);
function renderSearchUsage(usage = {}) {
  $('search-usage-period').textContent = usage.period ? `This month (${usage.period}, UTC)` : 'No usage data';
  const rows = HOSTED_SEARCH.map(name => {
    const used = usage.used?.[name] ?? 0, limit = usage.limits?.[name] ?? 0;
    const row = document.createElement('div'); row.className = 'search-usage-row';
    const label = document.createElement('span'); label.textContent = name + (usage.enabled?.[name] ? '' : ' (off)');
    const meter = document.createElement('meter'); meter.min = 0; meter.max = limit || 1; meter.value = used;
    meter.high = (limit || 1) * 0.8;
    const count = document.createElement('small'); count.textContent = `${used} / ${limit}`;
    row.append(label, meter, count); return row;
  });
  $('search-usage').replaceChildren(...rows);
}
function searchLogEntry(entry) {
  // Queries, titles and snippets are rendered as literal text; result URLs
  // come from the provider, so only http(s) ones become links.
  const item = document.createElement('article'); item.className = 'search-entry';
  const head = document.createElement('p');
  head.textContent = `${new Date(entry.at).toLocaleString()} · ${entry.served_by ? 'served by ' + entry.served_by : 'FAILED'} · ${entry.total_ms} ms · policy ${entry.policy}`;
  const query = document.createElement('p'); const q = document.createElement('strong'); q.textContent = entry.query;
  query.append('Query: ', q);
  const attempts = document.createElement('small');
  attempts.textContent = 'Attempts: ' + (entry.attempts.map(a => `${a.provider} ${a.outcome} (${a.ms} ms)`).join(' → ') || 'none');
  const results = document.createElement('ol');
  for (const result of entry.results) {
    const li = document.createElement('li');
    const title = /^https?:\/\//i.test(result.url) ? document.createElement('a') : document.createElement('span');
    title.textContent = result.title;
    if (title.tagName === 'A') { title.href = result.url; title.target = '_blank'; title.rel = 'noopener noreferrer'; }
    const domain = document.createElement('small'); domain.textContent = ` ${result.source_domain}`;
    const snippet = document.createElement('p'); snippet.className = 'muted'; snippet.textContent = result.snippet;
    li.append(title, domain, snippet); results.append(li);
  }
  if (!entry.results.length) { const li = document.createElement('li'); li.textContent = 'No results'; results.append(li); }
  item.append(head, query, attempts, results); return item;
}
async function loadSearchLog() {
  const data = await api('/websearch/log');
  renderSearchUsage(data?.usage);
  const entries = Array.isArray(data?.entries) ? data.entries : [];
  const empty = document.createElement('p'); empty.textContent = 'No searches since Companion Core started.';
  $('search-log-entries').replaceChildren(...(entries.length ? entries.map(searchLogEntry) : [empty]));
}
$('open-search-log').addEventListener('click', async () => {
  $('search-log-dialog').showModal();
  try { await loadSearchLog(); } catch (error) { notice(error.message); }
});
$('refresh-search-log').addEventListener('click', async () => {
  try { await loadSearchLog(); } catch (error) { notice(error.message); }
});
$('close-search-log').addEventListener('click', () => $('search-log-dialog').close());
function component(name, value, warning = false) {
  const card = document.createElement('div'); card.className = 'component';
  const title = document.createElement('strong'); title.textContent = name;
  const status = document.createElement('span'); status.textContent = value;
  if (warning) status.className = 'warn';
  card.append(title, status); $('components').append(card);
}
async function refresh() {
  if (!loggedIn || polling) return;
  polling = true;
  try {
    const status = await api('/status');
    const usage = status.llm.usage.data;
    if (!loggedIn) return;
    $('components').replaceChildren();
    component('Reachy hub', status.reachy_hub.status);
    component('Companion core', status.companion_core.status, status.companion_core.status !== 'ok');
    component('Language model', status.llm.configured === null ? 'Unavailable' : status.llm.configured ? 'Configured' : 'Not configured', !status.llm.configured);
    component('Telegram', telegramLabel(status.telegram), !status.telegram.healthy);
    chat.initializeUser(status.default_user_id);
    $('chat-user-form').hidden = Boolean(status.owner_bound);
    $('session-select').hidden = Boolean(status.owner_bound);
    if (status.owner_bound && !selectedUser) {
      try { await loadSession(); } catch (error) { if (error.status !== 404) throw error; }
    }
    chat.updateTelegram(status.telegram);
    await chat.refreshSession();
    await voice.refresh();
    if (!status.robots.length) component('Robots', 'None registered', true);
    for (const robot of status.robots) component(robot.robot_id, robot.data?.embodiment_state || robot.status, robot.status !== 'ok');
    if (usage) {
    const s = usage.summary;
    $('role-usage').textContent = ['local', 'cloud'].map(role => {
      const counts = usage.by_role?.[role];
      return `${role}: ${counts?.calls ?? 0} calls · ${counts?.errors ?? 0} errors · ${counts?.prompt_tokens ?? 0} input / ${counts?.completion_tokens ?? 0} output tokens`;
    }).join(' | ');
    const escalation = usage.latest_escalation;
    $('latest-escalation').textContent = escalation ? `Latest escalation: ${escalation.reason === 'manual' ? 'manual request' : 'local error'} · ${new Date(escalation.at).toLocaleString()}` : 'No escalation in this usage window.';
    $('usage-summary').textContent = `${s.calls} calls · ${s.errors} errors · ${s.prompt_tokens} input / ${s.completion_tokens} output tokens · ${Math.round(s.avg_latency_ms)} ms average${s.unreported_token_calls ? ` · ${s.unreported_token_calls} calls without full token counts` : ''}`;
    $('usage-rows').replaceChildren();
    for (const entry of usage.entries) {
      const row = document.createElement('tr');
      for (const value of [new Date(entry.at).toLocaleString(), `${entry.role} / ${entry.model}`, entry.success ? 'Success' : entry.error_message, `${entry.prompt_tokens ?? '—'} / ${entry.completion_tokens ?? '—'}`, `${Math.round(entry.latency_ms)} ms`]) {
        const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
      }
      $('usage-rows').append(row);
    }
    if (!usage.entries.length) {
      const row = document.createElement('tr'); const cell = document.createElement('td');
      cell.colSpan = 5; cell.textContent = 'No model calls yet. Usage appears after a conversation uses the configured model.'; row.append(cell); $('usage-rows').append(row);
    }
    } else {
      $('usage-summary').textContent = 'Usage unavailable — companion core is not responding.';
      $('usage-rows').replaceChildren();
      $('role-usage').textContent = ''; $('latest-escalation').textContent = '';
    }
    if ($('llm-fields').disabled && status.companion_core.status === 'ok') renderSettings(await api('/settings/llm'));
    if (selectedUser) await loadActivity(selectedUser);
    $('updated').textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (error) { notice(`Status refresh failed: ${error.message}`); $('updated').textContent = 'Status may be stale'; chat.updateTelegram(null); }
  finally { polling = false; }
}
function renderList(id, entries, format) {
  $(id).replaceChildren();
  for (const entry of entries) { const li = document.createElement('li'); li.textContent = format(entry); $(id).append(li); }
  if (!entries.length) { const li = document.createElement('li'); li.textContent = 'Nothing here yet.'; $(id).append(li); }
}
async function loadActivity(user) {
  const [audit, notifications] = await Promise.all([api(`/audit/${user}?limit=10`), api(`/notifications/${user}`)]);
  if (selectedUser !== user || !loggedIn) return;
  renderList('audit', audit, e => `${e.action || 'response'} · ${e.reason || e.delivery_channel || ''}`);
  renderList('notifications', notifications, e => e.text || e.reason || 'Queued notification');
}
async function loadSession() {
  selectedUser = null; $('session-fields').disabled = true;
  if (!chat.setUser($('user-id').value)) return;
  const user = encodeURIComponent($('user-id').value.trim());
  const session = await api(`/sessions/${user}`);
  selectedUser = user; $('mode').value = session.interaction_mode; $('dnd').checked = session.dnd;
  $('session-fields').disabled = false; $('session-state').textContent = `Active channel: ${session.active_channel}`;
  await loadActivity(user);
}
async function enter() {
  loggedIn = true; $('login-panel').hidden = true; $('dashboard').hidden = false; $('nav').hidden = false;
  $('llm-fields').disabled = true; $('persona-fields').disabled = true; $('websearch-fields').disabled = true; notice('');
  try { renderSettings(await api('/settings/llm')); } catch (error) { notice(error.message); }
  try { renderPersona(await api('/settings/persona')); } catch (error) { notice(error.message); }
  try { renderWebsearch(await api('/settings/websearch')); } catch (error) { notice(error.message); }
  try { await loadSearchLog(); } catch (error) { notice(error.message); }
  await refresh();
  if (new URLSearchParams(location.search).get('google') === 'return') {
    history.replaceState(null, '', location.pathname);
    showView('accounts'); await accounts.complete();
  }
}
submit('login', async () => {
  await api('/auth/login', {method: 'POST', body: JSON.stringify({username: $('username').value, password: $('password').value})});
  $('password').value = ''; await enter();
});
$('logout').addEventListener('click', async () => {
  try { await api('/auth/logout', {method: 'POST'}); showLogin(); notice('Logged out.'); }
  catch (error) { notice(error.message); }
});
submit('session-select', loadSession);
$('user-id').addEventListener('input', () => { selectedUser = null; $('session-fields').disabled = true; });
submit('session-controls', async () => {
  if (!selectedUser) return;
  await api(`/sessions/${selectedUser}/mode`, {method: 'PATCH', body: JSON.stringify({interaction_mode: $('mode').value})});
  await api(`/sessions/${selectedUser}/dnd`, {method: 'PATCH', body: JSON.stringify({dnd: $('dnd').checked})});
  notice('Session settings saved.'); await loadSession(); await chat.refreshSession();
});
submit('persona', async () => {
  const patch = {
    name: $('persona-name').value.trim(), system_prompt: $('persona-prompt').value.trim(),
    location: $('persona-location').value.trim() || null, timezone: $('persona-timezone').value.trim() || 'UTC',
  };
  renderPersona(await api('/settings/persona', {method: 'PUT', body: JSON.stringify(patch)}));
  notice('Persona saved.');
});
$('persona-browser-timezone').addEventListener('click', () => {
  $('persona-timezone').value = Intl.DateTimeFormat().resolvedOptions().timeZone;
});
$('reset-persona').addEventListener('click', () => {
  $('persona-name').value = DEFAULT_PERSONA_NAME;
  $('persona-prompt').value = DEFAULT_PERSONA_PROMPT;
  notice('Default persona loaded — click Save persona to apply.');
});
$('llm-routing').addEventListener('change', () => { routingEdited = true; });
for (const id of ['cloud-base-url', 'cloud-model']) $(id).addEventListener('input', () => {
  if (!hasSavedCloud && !routingEdited) $('llm-routing').value = $('base-url').value.trim() ? 'local_with_cloud_fallback' : 'cloud_only';
});
submit('llm', async () => {
  function provider(prefix) {
    const value = {base_url: $(prefix + 'base-url').value.trim(), model: $(prefix + 'model').value.trim()};
    if (!value.base_url && !value.model) return null;
    if (!value.base_url || !value.model) throw new Error('Each provider needs both a URL and model name.');
    if ($(prefix + 'clear-key').checked) value.api_key = null;
    else if ($(prefix + 'api-key').value) value.api_key = $(prefix + 'api-key').value;
    return value;
  }
  const config = {local: provider(''), cloud: provider('cloud-'), routing: {mode: $('llm-routing').value}};
  renderSettings(await api('/settings/llm', {method: 'PUT', body: JSON.stringify(config)}));
  notice('Model settings saved.'); await refresh();
});
$('disable-llm').addEventListener('click', async () => {
  try { renderSettings(await api('/settings/llm', {method: 'PUT', body: JSON.stringify({local: null, cloud: null, routing: {mode: 'local_only'}})})); notice('Model disabled.'); await refresh(); }
  catch (error) { notice(error.message); }
});
submit('websearch', async () => {
  const fallback = $('websearch-fallback').value;
  const hosted = {};
  for (const name of HOSTED_SEARCH) {
    hosted[name] = {enabled: $(`websearch-${name}-enabled`).checked};
    const limit = Number($(`websearch-${name}-limit`).value);
    if (limit) hosted[name].monthly_limit = limit;
    if ($(`websearch-${name}-clear-key`).checked) hosted[name].api_key = null;
    else if ($(`websearch-${name}-api-key`).value) hosted[name].api_key = $(`websearch-${name}-api-key`).value;
  }
  const patch = {
    policy: $('websearch-policy').value,
    hosted,
    fallback,
    // Only External SearXNG carries a base_url/api_key; Companion Core
    // resolves the built-in container's address itself (Phase 24 cleanup).
    base_url: fallback === 'searxng' ? $('websearch-base-url').value.trim() : null,
    result_count: Number($('websearch-result-count').value) || 5,
  };
  if (fallback !== 'searxng' || $('websearch-clear-key').checked) patch.api_key = null;
  else if ($('websearch-api-key').value) patch.api_key = $('websearch-api-key').value;
  renderWebsearch(await api('/settings/websearch', {method: 'PUT', body: JSON.stringify(patch)}));
  await loadSearchLog();
  notice('Web search settings saved.');
});
$('disable-websearch').addEventListener('click', async () => {
  try { renderWebsearch(await api('/settings/websearch', {method: 'PUT', body: JSON.stringify({policy: 'off'})})); notice('Web search turned off.'); }
  catch (error) { notice(error.message); }
});
api('/auth/me').then(enter).catch(error => { showLogin(); if (error.message !== 'Login required') notice(error.message); });
setInterval(refresh, 10000);


function createMotionSettings() {
  let generation = 0;
  let busy = false;
  const path = () => `/robots/${encodeURIComponent($('motion-robot').value)}/settings/motion`;
  function render(settings) {
    if (typeof settings.conversation_motion !== 'boolean' || typeof settings.speech_wobble !== 'boolean' || typeof settings.conversation_active !== 'boolean') {
      throw new Error('This robot does not support animation settings.');
    }
    $('motion-gestures').checked = settings.conversation_motion;
    $('motion-wobble').checked = settings.speech_wobble;
    $('motion-fields').disabled = settings.conversation_active;
    $('motion-status').textContent = settings.conversation_active
      ? 'Stop listening, then refresh to change animations.' : 'Current animation settings loaded.';
  }
  async function selected() {
    const version = ++generation;
    $('motion-fields').disabled = true;
    $('motion-gestures').checked = false; $('motion-wobble').checked = false;
    if (!loggedIn || !$('motion-robot').value) return;
    $('motion-status').textContent = 'Loading animation settings…';
    try {
      const settings = await api(path());
      if (version === generation && loggedIn) render(settings);
    } catch (error) {
      if (version === generation && loggedIn) $('motion-status').textContent = error.message;
    }
  }
  async function load() {
    if (!loggedIn || busy) return;
    const version = ++generation;
    $('motion-fields').disabled = true; $('motion-robot').disabled = true;
    $('motion-status').textContent = 'Loading robots…';
    try {
      const robots = await api('/robots');
      if (version !== generation || !loggedIn) return;
      const previous = $('motion-robot').value;
      $('motion-robot').replaceChildren();
      for (const robot of robots) {
        const option = document.createElement('option');
        option.value = robot.robot_id; option.textContent = robot.robot_id;
        $('motion-robot').append(option);
      }
      if (robots.some(robot => robot.robot_id === previous)) $('motion-robot').value = previous;
      $('motion-robot').disabled = !robots.length;
      if (robots.length) await selected();
      else $('motion-status').textContent = 'No robots registered.';
    } catch (error) {
      if (version === generation && loggedIn) $('motion-status').textContent = error.message;
    }
  }
  $('motion-robot').addEventListener('change', selected);
  $('motion-refresh').addEventListener('click', load);
  $('motion-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !loggedIn || $('motion-fields').disabled) return;
    const version = ++generation;
    const body = JSON.stringify({conversation_motion: $('motion-gestures').checked, speech_wobble: $('motion-wobble').checked});
    busy = true;
    $('motion-fields').disabled = true; $('motion-robot').disabled = true; $('motion-refresh').disabled = true;
    $('motion-status').textContent = 'Applying animation settings…';
    try {
      const settings = await api(path(), {method: 'PUT', body});
      if (version !== generation || !loggedIn) return;
      render(settings);
      $('motion-status').textContent = 'Animation settings applied for the next conversation.';
    } catch (error) {
      if (version !== generation || !loggedIn) return;
      // An ambiguous failure may already have changed the robot. Require
      // a fresh read rather than showing the unsaved draft as applied.
      $('motion-gestures').checked = false; $('motion-wobble').checked = false;
      $('motion-status').textContent = `${error.message}. Refresh to check the robot's current settings.`;
    } finally {
      if (version === generation && loggedIn) {
        busy = false; $('motion-robot').disabled = false; $('motion-refresh').disabled = false;
      }
    }
  });
  return {load, reset() {
    generation += 1; busy = false;
    $('motion-robot').replaceChildren(); $('motion-robot').disabled = true;
    $('motion-fields').disabled = true; $('motion-refresh').disabled = false;
    $('motion-gestures').checked = false; $('motion-wobble').checked = false;
    $('motion-status').textContent = '';
  }};
}
