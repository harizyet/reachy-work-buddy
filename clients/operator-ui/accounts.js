/* Google credentials never enter localStorage; provider text is always literal. */
function createAccounts({api, isLoggedIn}) {
  const el = id => document.getElementById(id);
  const root = '/settings/accounts/google';
  let generation = 0;
  let current = null;
  let desktopPoll = null;
  const messages = {
    setup_required: 'Complete the one-time connection setup below first.',
    authorization_cancelled: 'Google sign-in was cancelled. You can try again whenever you are ready.',
    permissions_not_granted: 'Google did not grant all the read permissions needed. Reconnect and allow the permissions for this feature.',
    invalid_or_expired_authorization: 'This sign-in link has expired or was already used. Select Connect to start again.',
    different_google_account_disconnect_first: 'Both features must use the same Google account. Disconnect first to choose a different account.',
    offline_access_missing_reconnect: 'Google did not provide ongoing access. Select Reconnect and approve access again.',
    stale: 'The last check is out of date. Select Test connection to check Google access.',
    reconnect_required: 'Google access has expired or was revoked. Select Reconnect.',
    temporarily_unavailable: 'Google is temporarily unavailable. Please try again shortly.',
    permission_denied: 'Google refused this read. Check the enabled APIs and reconnect with the requested permissions.',
    result_limit_exceeded: 'Too many results. Narrow your search or select fewer calendars.',
    select_calendars: 'Choose at least one calendar and save your choices.',
    selected_calendar_unavailable: 'A selected calendar is no longer available. Update your calendar choices.',
    disconnect_required_for_client_change: 'Select the disconnect checkbox before replacing an existing connection.',
    credential_unavailable: 'The saved connection cannot be opened. Ask the person who manages this Reachy installation to check its credential key.',
    not_connected: 'Connect this feature first.',
    unknown_calendar: 'Choose calendars from the current list and save again.',
    invalid_provider_response: 'Google returned an unexpected response. Please try Test connection.',
    provider_request_failed: 'Google could not complete this request. Please try again.',
    response_too_large: 'This item is too large to preview here. Open it in Google instead.',
    invalid_date_range: 'Choose a time range of at most 31 days.',
    invalid_message_id: 'Choose a message from the current mail list.',
    invalid_event: 'A calendar event could not be read. Try Test connection.',
    invalid_pagination: 'Google returned an unexpected page of results. Please try again.',
  };
  function say(value) { el('accounts-status').textContent = messages[value] || value; }
  function button(text, action) {
    const node = document.createElement('button'); node.type = 'button'; node.textContent = text;
    node.addEventListener('click', () => run(action, node)); return node;
  }
  async function run(action, buttonNode) {
    if (buttonNode) buttonNode.disabled = true;
    try { await action(); } catch (error) { if (isLoggedIn()) say(messages[error.message] || error.message); }
    finally { if (buttonNode) buttonNode.disabled = false; }
  }
  function stopDesktopPoll() {
    if (desktopPoll) { clearInterval(desktopPoll); desktopPoll = null; }
    el('google-desktop-connect').hidden = true;
  }
  function reset() {
    generation++; current = null;
    stopDesktopPoll();
    el('account-cards').replaceChildren(); el('account-results').replaceChildren();
    el('calendar-options').replaceChildren(); el('google-identity').textContent = '';
    el('google-client-file').value = ''; el('gmail-query').value = '';
    el('calendar-selection').hidden = true; el('mail-preview').hidden = true;
  }
  function render(status) {
    if (!isLoggedIn()) return;
    current = status;
    el('google-identity').textContent = status.identity ? 'Signed in as ' + status.identity.email : 'No Google account connected.';
    el('google-callback').value = location.origin + new URL('../settings/accounts/google/callback', location.href).pathname;
    el('google-callback-label').hidden = status.client_type === 'desktop';
    el('google-setup-state').textContent = status.configured ? 'Connection setup saved. Your client secret is stored securely.' : 'Google sign-in is not ready yet. The person setting up this Reachy installation needs to complete this one-time setup.';
    if (status.configured) el('google-setup').open = false;
    el('account-cards').replaceChildren();
    for (const [cap, title] of [['gmail', 'Gmail'], ['calendar', 'Google Calendar']]) {
      const state = status.capabilities[cap];
      const card = document.createElement('section'); card.className = 'card';
      const heading = document.createElement('h3'); heading.textContent = title;
      const health = document.createElement('p');
      const labels = {connected: 'Ready to read', disconnected: 'Not connected', not_checked: 'Permission saved; connection not checked'};
      health.textContent = labels[state.status] || messages[state.status] || 'Connection needs attention';
      const success = document.createElement('p');
      success.textContent = state.last_success ? 'Last successful check: ' + new Date(state.last_success).toLocaleString() : 'No successful check yet.';
      const connect = button(state.enabled ? 'Reconnect' : 'Connect', async () => {
        if (status.client_type === 'desktop') { await desktopConnect(cap); return; }
        const response = await api(root + '/connect', {method: 'POST', body: JSON.stringify({capability: cap})});
        const url = new URL(response.authorization_url);
        if (url.origin !== 'https://accounts.google.com') throw new Error('Unexpected sign-in address');
        location.assign(url.href);
      });
      connect.disabled = !status.configured;
      card.append(heading, health, success, connect);
      if (state.enabled) {
        card.append(button('Test connection', async () => {
          const response = await api(root + '/test', {method: 'POST', body: JSON.stringify({capability: cap})});
          render(response); say('Connection checked.');
        }));
        card.append(button('Disconnect', async () => {
          if (!window.confirm('Disconnect Google? This removes access for both Gmail and Calendar. Your local drafts are kept.')) return;
          const response = await api(root + '/disconnect', {method: 'POST'});
          reset(); render(response.status);
          say(response.revocation !== 'revoked'
            ? 'Disconnected here. Google could not be reached to revoke access; remove Reachy access in your Google account as well.'
            : 'Google disconnected. Local drafts were kept.');
        }));
      }
      el('account-cards').append(card);
    }
    const permissions = document.createElement('p'); permissions.className = 'muted';
    permissions.textContent = 'Granted permissions: ' + (status.scopes.length ? status.scopes.map(s => (
      s.includes('gmail.readonly') ? 'Read Gmail' : s.includes('calendar.events.readonly') ? 'Read calendar events' :
        s.includes('calendar.calendarlist.readonly') ? 'List calendars' : 'Identify your Google account'
    )).filter((v, i, a) => a.indexOf(v) === i).join(', ') : 'None');
    el('account-cards').append(permissions);
    el('mail-preview').hidden = !status.capabilities.gmail.enabled;
    el('calendar-selection').hidden = !status.capabilities.calendar.enabled;
  }
  function shellQuote(value) { return "'" + String(value).replace(/'/g, "'\\''") + "'"; }
  async function desktopConnect(cap) {
    const response = await api(root + '/desktop/start', {method: 'POST', body: JSON.stringify({capability: cap})});
    const hubBase = location.origin + new URL('..', location.href).pathname;
    stopDesktopPoll();
    el('google-desktop-command').textContent = [
      'python3 google_auth_helper.py',
      '--hub-url', shellQuote(hubBase), '--client-id', shellQuote(response.client_id),
      '--scope', shellQuote(response.scope), '--state', shellQuote(response.state),
      '--binding', shellQuote(response.binding), '--code-challenge', shellQuote(response.code_challenge),
    ].join(' ');
    el('google-desktop-connect').hidden = false;
    el('google-desktop-waiting').textContent = 'Waiting for the helper to finish (this expires in 10 minutes)…';
    const ticket = generation, deadline = Date.now() + 10 * 60 * 1000;
    desktopPoll = setInterval(async () => {
      if (ticket !== generation) { stopDesktopPoll(); return; }
      if (Date.now() > deadline) { stopDesktopPoll(); say('invalid_or_expired_authorization'); return; }
      try {
        const latest = await api(root);
        if (ticket !== generation) return;
        if (latest.capabilities[cap].enabled) {
          stopDesktopPoll();
          render(latest); say('Google connected. Choose calendars below if you enabled Calendar.');
          if (latest.capabilities.calendar.enabled) await calendarChoices(ticket);
        }
      } catch { /* transient; keep polling until the deadline */ }
    }, 3000);
  }
  async function calendarChoices(ticket) {
    const response = await api(root + '/calendars');
    if (!isLoggedIn() || ticket !== generation) return;
    el('calendar-options').replaceChildren();
    for (const calendar of response.calendars) {
      const label = document.createElement('label'); label.className = 'check';
      const check = document.createElement('input'); check.type = 'checkbox'; check.value = calendar.id;
      check.checked = current.selected_calendars.includes(calendar.id);
      label.append(check, document.createTextNode(calendar.name + ' (' + calendar.timezone + ')'));
      el('calendar-options').append(label);
    }
  }
  async function load() {
    const ticket = ++generation;
    await run(async () => {
      const status = await api(root);
      if (!isLoggedIn() || ticket !== generation) return;
      render(status); say('');
      if (status.capabilities.calendar.enabled) await calendarChoices(ticket);
    });
  }
  async function complete() {
    const ticket = ++generation;
    await run(async () => {
      const status = await api(root + '/complete', {method: 'POST'});
      if (!isLoggedIn() || ticket !== generation) return;
      render(status); say('Google connected. Choose calendars below if you enabled Calendar.');
      if (status.capabilities.calendar.enabled) await calendarChoices(ticket);
    });
  }
  el('google-client-setup').addEventListener('submit', event => {
    event.preventDefault();
    void run(async () => {
      const file = el('google-client-file').files[0];
      if (!file || file.size > 65536) throw new Error('Choose the Google connection JSON file (under 64 KB).');
      let parsed;
      try { parsed = JSON.parse(await file.text()); } catch { throw new Error('This is not a Google connection file.'); }
      const clientType = parsed.installed ? 'desktop' : parsed.web ? 'web' : null;
      const client = parsed.installed || parsed.web;
      if (!clientType || !client?.client_id || !client?.client_secret) {
        throw new Error('Choose a Web application or Desktop app connection file downloaded from Google.');
      }
      const status = await api(root + '/configure', {method: 'PUT', body: JSON.stringify({
        client_id: client.client_id, client_secret: client.client_secret, client_type: clientType,
        redirect_uri: clientType === 'web' ? el('google-callback').value : undefined,
        disconnect_existing: el('google-replace').checked,
      })});
      el('google-client-file').value = ''; stopDesktopPoll(); render(status); say('Setup saved. Select Connect to sign in with Google.');
    }, event.submitter);
  });
  el('google-desktop-copy').addEventListener('click', () => {
    void run(async () => {
      await navigator.clipboard.writeText(el('google-desktop-command').textContent);
      say('Command copied.');
    });
  });
  el('calendar-choice').addEventListener('submit', event => {
    event.preventDefault(); void run(async () => {
      const calendar_ids = [...el('calendar-options').querySelectorAll('input:checked')].map(n => n.value);
      render(await api(root + '/selection', {method: 'PUT', body: JSON.stringify({calendar_ids})}));
      say('Calendar choices saved.');
    }, event.submitter);
  });
  for (const [id, busy] of [['calendar-preview', false], ['calendar-busy', true]]) {
    el(id).addEventListener('click', event => {
      void run(async () => {
        const ticket = generation;
        const start = new Date(), end = new Date(start.getTime() + 7 * 86400000);
        const response = await api(root + (busy ? '/free-busy?' : '/events?') + new URLSearchParams({start: start.toISOString(), end: end.toISOString()}));
        if (ticket !== generation || !isLoggedIn()) return;
        el('account-results').replaceChildren();
        const rows = busy ? response.busy : response.events;
        for (const item of rows) {
          const p = document.createElement('p');
          p.textContent = busy
            ? 'Busy · ' + new Date(item.start).toLocaleString() + ' – ' + new Date(item.end).toLocaleString()
            : item.title + ' · ' + (item.all_day ? 'All day · ' : '') + new Date(item.start).toLocaleString();
          el('account-results').append(p);
        }
        if (!rows.length) el('account-results').textContent = busy ? 'No busy times in the selected calendars this week.' : 'No events in the next seven days.';
      }, event.target);
    });
  }
  el('gmail-search').addEventListener('submit', event => {
    event.preventDefault(); void run(async () => {
      const ticket = generation;
      const response = await api(root + '/messages?' + new URLSearchParams({query: el('gmail-query').value}));
      if (ticket !== generation || !isLoggedIn()) return;
      el('account-results').replaceChildren();
      for (const message of response.messages) {
        const p = document.createElement('p');
        p.append(button(message.sender + ': ' + message.subject, async () => {
          const result = await api(root + '/messages/' + encodeURIComponent(message.id));
          if (ticket !== generation || !isLoggedIn()) return;
          const body = document.createElement('pre'); body.style.whiteSpace = 'pre-wrap';
          body.textContent = result.body || result.snippet; p.replaceChildren(body);
        }));
        el('account-results').append(p);
      }
      if (!response.messages.length) el('account-results').textContent = 'No matching messages.';
    }, event.submitter);
  });
  return {load, complete, reset};
}
