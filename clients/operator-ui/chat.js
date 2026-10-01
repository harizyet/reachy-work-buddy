// Saved web records live in hub; assistant context remains shared across channels.
function telegramLabel(telegram) {
  if (!telegram.configured) return 'Not configured';
  if (telegram.last_poll_error) return telegram.last_poll_error;
  if (telegram.healthy) return 'Polling healthy';
  return telegram.last_poll_at ? 'Polling stalled' : 'Awaiting first successful poll';
}

// Phase 24b: the fixed set of explicit commands the parser accepts —
// used only for client-side autocomplete/button rendering, never to
// decide anything authoritative (that's companion_core/commands/parser.py).
const REACHY_COMMANDS = ['/reachy standby', '/reachy wake', '/reachy status'];
const SUGGESTED_COMMAND_PATTERN = /\/reachy (standby|wake|status)\b/;

// Search evidence belongs to this reply, never the global debug log.
function searchDetails(search) {
  const details = document.createElement('details');
  details.className = 'chat-search';
  const summary = document.createElement('summary');
  const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  icon.setAttribute('viewBox', '0 0 32 32');
  icon.setAttribute('aria-hidden', 'true');
  // Reachy's antennae, rounded head and eyes, with a search lens.
  for (const d of ['M9 9 6 3M21 9l3-6', 'M7 9h15a4 4 0 0 1 4 4v7a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4v-7a4 4 0 0 1 4-4Z', 'M10 15v3m8-3v3', 'M28 25a5 5 0 1 1-10 0 5 5 0 0 1 10 0Zm-1 4 4 2']) {
    const path = document.createElementNS(icon.namespaceURI, 'path');
    path.setAttribute('d', d);
    icon.append(path);
  }
  const label = document.createElement('span');
  label.textContent = search.failed ? 'Web search unavailable' : `Web search · ${search.results.length} results`;
  summary.append(icon, label);
  const query = document.createElement('p');
  query.className = 'chat-search-query';
  query.textContent = `Searched: ${search.query}`;
  details.append(summary, query);
  if (search.failed || !search.results.length) {
    const status = document.createElement('p');
    status.textContent = search.failed ? 'The search failed. No results were available for this reply.' : 'No results were found.';
    details.append(status);
  }
  const list = document.createElement('ol');
  for (const [index, result] of search.results.entries()) {
    const item = document.createElement('li');
    let url;
    try {
      const parsed = new URL(result.url);
      if (['https:', 'http:'].includes(parsed.protocol) && !parsed.username && !parsed.password) url = parsed.href;
    } catch { /* Invalid source URLs remain plain text. */ }
    const title = document.createElement(url ? 'a' : 'span');
    title.textContent = `[S${index + 1}] ${result.title || result.source_domain || result.url}`;
    if (url) {
      title.href = url;
      title.target = '_blank';
      title.rel = 'noopener noreferrer';
    }
    const domain = document.createElement('small');
    domain.textContent = result.source_domain;
    const snippet = document.createElement('p');
    snippet.textContent = result.snippet;
    item.append(title, domain, snippet);
    list.append(item);
  }
  if (list.children.length) details.append(list);
  return details;
}

function createChat({api, isLoggedIn, onUserChange, onBusyChange}) {
  const el = id => document.getElementById(id);
  let user = null;
  let generation = 0;
  let pending = false;
  let requestController = null;
  let activeChat = null;
  let history = [];
  let historyInitialized = false;
  let reading = false;
  let readVersion = 0;

  function renderHistory() {
    const query = el('chat-history-search').value.trim().toLowerCase();
    const records = history.filter(record => record.title.toLowerCase().includes(query));
    el('chat-history').replaceChildren();
    for (const record of records) {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'history-button';
      button.setAttribute('aria-pressed', String(record.id === activeChat));
      button.disabled = pending || reading;
      const title = document.createElement('span'); title.textContent = record.title;
      const date = document.createElement('small'); date.textContent = new Date(record.updated_at).toLocaleDateString();
      button.append(title, date);
      button.addEventListener('click', () => void openChat(record.id));
      item.append(button); el('chat-history').append(item);
    }
    if (!records.length) {
      const item = document.createElement('li'); item.className = 'muted';
      item.textContent = query ? 'No matching chats.' : 'Your chats will appear here.';
      el('chat-history').append(item);
    }
  }

  async function openChat(id) {
    if (pending || !user || !isLoggedIn()) return;
    const version = generation, read = ++readVersion;
    reading = true; controls();
    el('chat-history-status').textContent = 'Loading chat…';
    try {
      const record = await api(`/chats/${encodeURIComponent(id)}?user_id=${encodeURIComponent(user)}`);
      if (generation !== version || read !== readVersion || !isLoggedIn()) return;
      activeChat = record.id;
      clearView();
      el('chat-title').textContent = record.title;
      for (const turn of record.turns) {
        const item = appendMessage('You', turn.text);
        if (turn.status !== 'complete') {
          const note = document.createElement('small');
          note.textContent = 'Reply not recorded. This message may have been processed; check before sending again.';
          item.append(note);
        }
        if (turn.reply !== null) appendMessage('Reachy', turn.reply, {webSearch: turn.web_search});
      }
      el('chat-history-status').textContent = '';
      el('chat-status').textContent = '';
    } catch (error) {
      if (generation === version && read === readVersion) el('chat-history-status').textContent = `Could not load chat: ${error.message}`;
    } finally {
      if (generation === version && read === readVersion) { reading = false; controls(); }
    }
  }

  async function loadHistory() {
    if (!user || !isLoggedIn()) return;
    const version = generation;
    try {
      const records = await api(`/chats?user_id=${encodeURIComponent(user)}`);
      if (generation !== version || !isLoggedIn()) return;
      history = records;
      el('chat-history-status').textContent = '';
      renderHistory();
      if (!historyInitialized) {
        historyInitialized = true;
        if (records.length && !pending && !activeChat) await openChat(records[0].id);
      }
    } catch (error) {
      if (generation === version) el('chat-history-status').textContent = `Chat history unavailable: ${error.message}`;
    }
  }

  el('chat-history-search').addEventListener('input', renderHistory);
  el('new-chat').addEventListener('click', () => {
    if (pending || reading) return;
    activeChat = null; historyInitialized = true; clearView();
    el('chat-title').textContent = 'Chat with Reachy';
    el('chat-text').value = ''; el('chat-status').textContent = '';
    renderHistory(); el('chat-text').focus();
  });

  function controls() {
    el('chat-send').disabled = pending || reading || !user || !isLoggedIn() || el('chat-user').value.trim() !== user;
    el('chat-text').disabled = reading || !user || !isLoggedIn();
    el('force-frontier').disabled = pending || !isLoggedIn();
    el('chat-user').disabled = pending;
    el('chat-use-user').disabled = pending;
    el('clear-chat').disabled = pending;
    el('new-chat').disabled = pending || reading || !user;
    renderHistory();
    onBusyChange(pending || reading);
    updateCommandHints();
  }

  function clearView() {
    el('chat-transcript').replaceChildren();
    const empty = document.createElement('p');
    empty.id = 'chat-empty';
    empty.textContent = 'Send a message to start or continue your conversation.';
    el('chat-transcript').append(empty);
  }

  function dispatchCommand(command) {
    if (pending) return;
    el('chat-text').value = command;
    el('chat-form').requestSubmit();
  }

  function appendMessage(speaker, text, {fromUser = speaker === 'You', note = false, webSearch = null} = {}) {
    el('chat-empty')?.remove();
    const item = document.createElement('article');
    item.className = `chat-message ${fromUser ? 'from-user' : 'from-reachy'}${note ? ' voice-note' : ''}`;
    const label = document.createElement('strong'); label.textContent = speaker;
    const body = document.createElement('p'); body.textContent = text;
    item.append(label, body);
    if (!fromUser && webSearch) item.append(searchDetails(webSearch));
    // Phase 24b: a suggested-command reply renders as a real button, not
    // by re-parsing the reply text as HTML — clicking it re-sends the
    // literal command text through the normal /messages path, the same
    // as typing it, which is itself the authorization event.
    const match = !fromUser && SUGGESTED_COMMAND_PATTERN.exec(text);
    if (match) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'chat-command-suggestion';
      button.textContent = `Run: ${match[0]}`;
      button.addEventListener('click', () => dispatchCommand(match[0]));
      item.append(button);
    }
    el('chat-transcript').append(item);
    item.scrollIntoView({block: 'nearest'});
    return item;
  }

  function updateCommandHints() {
    const hints = el('chat-command-hints');
    if (!hints) return;
    const value = el('chat-text').value;
    const matches = value.startsWith('/') ? REACHY_COMMANDS.filter(c => c.startsWith(value)) : [];
    hints.replaceChildren();
    hints.hidden = matches.length === 0 || matches[0] === value;
    for (const command of matches) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = command;
      button.addEventListener('click', () => {
        el('chat-text').value = command;
        hints.hidden = true;
        el('chat-text').focus();
      });
      hints.append(button);
    }
  }
  el('chat-text').addEventListener('input', updateCommandHints);

  async function refreshSession() {
    if (!user || !isLoggedIn()) return;
    const version = generation;
    try {
      const session = await api(`/sessions/${encodeURIComponent(user)}`);
      if (generation !== version || !isLoggedIn()) return;
      el('chat-session').textContent = `User: ${user} · Mode: ${session.interaction_mode} · DND: ${session.dnd ? 'on' : 'off'} · Active channel: ${session.active_channel}`;
    } catch (error) {
      if (generation !== version || !isLoggedIn()) return;
      el('chat-session').textContent = error.status === 404
        ? `User: ${user} · No session yet. Your first message will start one.`
        : `User: ${user} · Session status unavailable.`;
    }
  }

  function setUser(value) {
    const next = value.trim();
    if (pending || !next) return false;
    if (next !== user) {
      generation += 1;
      user = next;
      activeChat = null; history = []; historyInitialized = false; reading = false; readVersion += 1;
      el('chat-title').textContent = 'Chat with Reachy';
      el('chat-history-search').value = '';
      clearView();
      el('chat-text').value = '';
      el('force-frontier').checked = false;
      el('chat-status').textContent = '';
      el('chat-session').textContent = `User: ${user} · Loading session…`;
    }
    el('chat-user').value = user;
    onUserChange(user);
    controls();
    void refreshSession();
    void loadHistory();
    return true;
  }

  el('chat-user').addEventListener('input', controls);
  el('chat-user-form').addEventListener('submit', event => {
    event.preventDefault();
    if (!setUser(el('chat-user').value)) el('chat-status').textContent = 'Enter a user ID before sending.';
  });
  el('clear-chat').addEventListener('click', () => {
    clearView();
    el('chat-status').textContent = 'Messages hidden. Select the chat in history to show its saved messages again.';
  });
  el('chat-text').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!pending) el('chat-form').requestSubmit();
    }
  });
  el('chat-form').addEventListener('submit', async event => {
    event.preventDefault();
    const text = el('chat-text').value.trim();
    if (!isLoggedIn() || !user || pending || reading || !text || el('chat-user').value.trim() !== user) return;
    const version = generation;
    const recipient = user;
    const forceFrontier = el('force-frontier').checked;
    pending = true;
    requestController = new AbortController();
    const signal = requestController.signal;
    controls();
    let sent = false;
    let item = null;
    el('chat-status').textContent = 'Sending…';
    // Do not automatically retry an ambiguous failure: a task or confirmation
    // may already have been processed even when its reply was lost.
    const timeout = setTimeout(() => requestController?.abort(), 135000);
    try {
      await api('/auth/me', {signal});
      if (generation !== version || !isLoggedIn()) return;
      if (!activeChat) {
        const record = await api('/chats', {method: 'POST', signal,
          body: JSON.stringify({user_id: recipient, title: text.slice(0, 120)})});
        if (generation !== version || !isLoggedIn()) return;
        activeChat = record.id;
        el('chat-title').textContent = record.title;
        historyInitialized = true;
      }
      item = appendMessage('You', text);
      el('chat-text').value = '';
      el('force-frontier').checked = false;
      sent = true;
      const result = await api('/messages', {
        method: 'POST', signal,
        body: JSON.stringify({user_id: recipient, channel: 'web', text, input_modality: 'text', chat_id: activeChat, ...(forceFrontier ? {force_frontier: true} : {})}),
      });
      if (generation !== version || !isLoggedIn()) return;
      appendMessage('Reachy', result.reply, {webSearch: result.web_search});
      el('chat-status').textContent = '';
      await refreshSession();
    } catch (error) {
      if (generation !== version || !isLoggedIn()) return;
      if (item) {
        const failure = document.createElement('small');
        failure.textContent = 'Reply not received';
        item.append(failure);
      }
      el('chat-status').textContent = sent
        ? 'No reply received. This message may have been processed; check before sending it again.'
        : 'Could not prepare this chat. Your message was not sent.';
      if (!el('chat-text').value) el('chat-text').value = text;
    } finally {
      clearTimeout(timeout);
      if (generation === version) {
        pending = false;
        requestController = null;
        controls();
        void loadHistory();
        el('chat-text').focus();
      }
    }
  });

  // Phase 24c: robot microphone turns share this transcript so the owner
  // sees one conversation across speech and typing. Text stays literal.
  function appendVoiceTurn(turn) {
    if (turn.transcript) appendMessage('You · spoken to Reachy', turn.transcript, {fromUser: true});
    if (turn.outcome === 'spoken') appendMessage('Reachy · said aloud', turn.reply || '', {webSearch: turn.web_search});
    else if (turn.outcome === 'withheld') appendMessage(`Reachy · not spoken (${turn.reason || 'withheld'})`, turn.reply || '', {webSearch: turn.web_search});
    else if (turn.outcome === 'no_speech') appendMessage('Reachy', 'I heard a sound but no words. Try again.', {note: true});
    else if (turn.outcome === 'failed') appendMessage('Reachy', `That turn failed: ${turn.reason || 'unknown error'}. Speak again when listening resumes.`, {note: true});
    else if (turn.outcome === 'cancelled') {
      // A held turn the robot moved past carries its own reason (Phase 24e).
      const why = turn.reason && turn.reason !== 'Stopped' ? `Not answered: ${turn.reason}.` : 'Stopped before replying.';
      appendMessage('Reachy', why, {note: true});
    }
  }

  return {
    setUser, refreshSession, appendVoiceTurn, loadHistory,
    currentUser() { return user; },
    initializeUser(defaultUser) { if (!user) setUser(defaultUser); },
    updateTelegram(telegram) {
      el('chat-telegram').textContent = !telegram ? 'Telegram status unavailable. You can still try web chat.'
        : !telegram.configured ? 'Telegram is not configured. You can chat here.'
        : telegram.healthy ? 'Telegram polling is healthy. You can also chat here anytime.'
        : `${telegramLabel(telegram)}. You can continue the conversation here.`;
      el('chat-telegram').classList.toggle('warn', Boolean(telegram?.configured && !telegram.healthy));
    },
    reset() {
      generation += 1;
      requestController?.abort(); requestController = null;
      user = null; pending = false;
      activeChat = null; history = []; historyInitialized = false; reading = false; readVersion += 1;
      el('chat-history-search').value = ''; el('chat-history-status').textContent = '';
      el('chat-title').textContent = 'Chat with Reachy';
      clearView();
      el('chat-user').value = ''; el('chat-text').value = ''; el('force-frontier').checked = false;
      el('chat-session').textContent = 'Loading session…';
      el('chat-status').textContent = '';
      controls();
    },
  };
}
