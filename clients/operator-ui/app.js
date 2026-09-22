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
function showView(view) {
  const isChat = view === 'chat';
  $('chat-pane').hidden = !isChat; $('overview-pane').hidden = isChat;
  for (const name of ['chat', 'overview']) {
    $(name + '-tab').setAttribute('aria-pressed', String(name === view));
    $(name + '-tab').classList.toggle('secondary', name !== view);
  }
  if (isChat) void chat.refreshSession();
}
$('chat-tab').addEventListener('click', () => showView('chat'));
$('overview-tab').addEventListener('click', () => showView('overview'));
function notice(text) { $('notice').textContent = text; }
function showLogin() {
  loggedIn = false; selectedUser = null;
  $('login-panel').hidden = false; $('dashboard').hidden = true; $('nav').hidden = true;
  $('api-key').value = ''; $('cloud-api-key').value = ''; $('password').value = '';
  chat.reset(); showView('overview');
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
    chat.updateTelegram(status.telegram);
    await chat.refreshSession();
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
  $('llm-fields').disabled = true; notice('');
  try { renderSettings(await api('/settings/llm')); } catch (error) { notice(error.message); }
  await refresh();
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
api('/auth/me').then(enter).catch(error => { showLogin(); if (error.message !== 'Login required') notice(error.message); });
setInterval(refresh, 10000);
