// Tab-local presentation only. All conversation/session behavior stays in hub.
function telegramLabel(telegram) {
  if (!telegram.configured) return 'Not configured';
  if (telegram.last_poll_error) return telegram.last_poll_error;
  if (telegram.healthy) return 'Polling healthy';
  return telegram.last_poll_at ? 'Polling stalled' : 'Awaiting first successful poll';
}

function createChat({api, isLoggedIn, onUserChange, onBusyChange}) {
  const el = id => document.getElementById(id);
  let user = null;
  let generation = 0;
  let pending = false;
  let requestController = null;

  function controls() {
    el('chat-send').disabled = pending || !user || !isLoggedIn() || el('chat-user').value.trim() !== user;
    el('chat-text').disabled = !user || !isLoggedIn();
    el('chat-user').disabled = pending;
    el('chat-use-user').disabled = pending;
    el('clear-chat').disabled = pending;
    onBusyChange(pending);
  }

  function clearView() {
    el('chat-transcript').replaceChildren();
    const empty = document.createElement('p');
    empty.id = 'chat-empty';
    empty.textContent = 'Send a message to start or continue your conversation.';
    el('chat-transcript').append(empty);
  }

  function appendMessage(speaker, text) {
    el('chat-empty')?.remove();
    const item = document.createElement('article');
    item.className = `chat-message ${speaker === 'You' ? 'from-user' : 'from-reachy'}`;
    const label = document.createElement('strong'); label.textContent = speaker;
    const body = document.createElement('p'); body.textContent = text;
    item.append(label, body);
    el('chat-transcript').append(item);
    item.scrollIntoView({block: 'nearest'});
    return item;
  }

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
      clearView();
      el('chat-text').value = '';
      el('chat-status').textContent = '';
      el('chat-session').textContent = `User: ${user} · Loading session…`;
    }
    el('chat-user').value = user;
    onUserChange(user);
    controls();
    void refreshSession();
    return true;
  }

  el('chat-user').addEventListener('input', controls);
  el('chat-user-form').addEventListener('submit', event => {
    event.preventDefault();
    if (!setUser(el('chat-user').value)) el('chat-status').textContent = 'Enter a user ID before sending.';
  });
  el('clear-chat').addEventListener('click', () => {
    clearView();
    el('chat-status').textContent = 'Visible messages cleared. The companion session is unchanged.';
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
    if (!isLoggedIn() || !user || pending || !text || el('chat-user').value.trim() !== user) return;
    const version = generation;
    const recipient = user;
    pending = true;
    requestController = new AbortController();
    const signal = requestController.signal;
    controls();
    let sent = false;
    let item = null;
    el('chat-status').textContent = 'Sending…';
    // Do not automatically retry an ambiguous failure: a task or confirmation
    // may already have been processed even when its reply was lost.
    const timeout = setTimeout(() => requestController?.abort(), 75000);
    try {
      await api('/auth/me', {signal});
      if (generation !== version || !isLoggedIn()) return;
      item = appendMessage('You', text);
      el('chat-text').value = '';
      sent = true;
      const result = await api('/messages', {
        method: 'POST', signal,
        body: JSON.stringify({user_id: recipient, channel: 'web', text, input_modality: 'text'}),
      });
      if (generation !== version || !isLoggedIn()) return;
      appendMessage('Reachy', result.reply);
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
        : 'Could not verify your login. Your message was not sent.';
      if (!el('chat-text').value) el('chat-text').value = text;
    } finally {
      clearTimeout(timeout);
      if (generation === version) {
        pending = false;
        requestController = null;
        controls();
        el('chat-text').focus();
      }
    }
  });

  return {
    setUser, refreshSession,
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
      clearView();
      el('chat-user').value = ''; el('chat-text').value = '';
      el('chat-session').textContent = 'Loading session…';
      el('chat-status').textContent = '';
      controls();
    },
  };
}
