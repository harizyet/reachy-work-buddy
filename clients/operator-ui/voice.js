// Phase 24c: owner controls for a robot microphone conversation (ADR 0023).
// The hub owns the session; this tab only starts/stops it and renews its
// short lease while open. Closing the tab or losing the login lets the lease
// lapse, which stops capture on the robot.
const VOICE_STATE_LABELS = {
  starting: 'Starting…', listening: 'Listening — speak now', thinking: 'Thinking…',
  speaking: 'Speaking', stopped: 'Off',
};
const VOICE_RENEW_MS = 1500;

function createVoice({api, isLoggedIn, chat}) {
  const el = id => document.getElementById(id);
  let session = null;
  let timer = null;
  let busy = false;
  let shownTurns = 0;

  function active() { return Boolean(session && session.state !== 'stopped'); }

  function controls() {
    const robot = el('voice-robot');
    const option = robot.selectedOptions[0];
    el('voice-start').disabled = busy || active() || !isLoggedIn() || !option?.dataset.capable;
    el('voice-stop').disabled = busy || !active();
    robot.disabled = busy || active() || robot.options.length === 0 || !robot.options[0].value;
  }

  function render(status) {
    session = status;
    const state = status?.state || 'stopped';
    el('voice-state').textContent = VOICE_STATE_LABELS[state] || state;
    el('voice-state').classList.toggle('active', active());
    const detail = [];
    if (status?.state === 'stopped' && status.stop_reason) detail.push(`Stopped: ${status.stop_reason}`);
    if (active() && status.last_error) detail.push(`Last problem: ${status.last_error}`);
    if (active() && state === 'listening') detail.push('Wait for "Listening" before each turn; Reachy does not listen while it thinks or speaks.');
    el('voice-detail').textContent = detail.join(' · ');
    for (const turn of status?.turns || []) {
      if (turn.turn <= shownTurns) continue;
      shownTurns = turn.turn;
      chat.appendVoiceTurn(turn);
      void chat.refreshSession();
    }
    if (!active()) stopPolling();
    controls();
  }

  function renderRobots(robots) {
    const select = el('voice-robot');
    const previous = select.value;
    select.replaceChildren();
    for (const robot of robots) {
      const option = document.createElement('option');
      option.value = robot.robot_id;
      option.textContent = robot.voice_capable ? robot.robot_id
        : `${robot.robot_id} (${robot.online ? 'voice not enabled' : 'offline'})`;
      if (robot.voice_capable) option.dataset.capable = '1';
      select.append(option);
    }
    if (!robots.length) {
      const option = document.createElement('option');
      option.value = ''; option.textContent = 'No robot connected';
      select.append(option);
    }
    const capable = robots.find(robot => robot.voice_capable);
    select.value = robots.some(robot => robot.robot_id === previous) ? previous : capable?.robot_id || select.options[0].value;
  }

  function stopPolling() { clearInterval(timer); timer = null; }
  function startPolling() {
    if (timer) return;
    timer = setInterval(renew, VOICE_RENEW_MS);
  }

  async function renew() {
    if (!active() || !isLoggedIn()) { stopPolling(); return; }
    try {
      render(await api('/robot-voice/renew', {method: 'POST', body: JSON.stringify({voice_session_id: session.voice_session_id})}));
    } catch (error) {
      el('voice-detail').textContent = `Could not reach the hub: ${error.message}. Listening stops automatically if this continues.`;
    }
  }

  async function refresh() {
    if (!isLoggedIn()) return;
    try {
      const overview = await api('/robot-voice');
      renderRobots(overview.robots);
      if (overview.session) {
        // A session that ended before this tab loaded shouldn't replay its turns.
        if (!session) shownTurns = Math.max(...overview.session.turns.map(turn => turn.turn), 0);
        render(overview.session);
        if (active()) startPolling();
      } else { controls(); }
    } catch (error) {
      el('voice-detail').textContent = `Robot microphone status unavailable: ${error.message}`;
    }
  }

  el('voice-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || active()) return;
    busy = true; controls();
    try {
      const status = await api('/robot-voice/start', {method: 'POST', body: JSON.stringify({robot_id: el('voice-robot').value, user_id: chat.currentUser()})});
      shownTurns = Math.max(...status.turns.map(turn => turn.turn), 0);
      render(status); startPolling();
    } catch (error) {
      el('voice-detail').textContent = `Could not start listening: ${error.message}`;
    } finally { busy = false; controls(); }
  });
  el('voice-stop').addEventListener('click', async () => {
    if (!active()) return;
    busy = true; controls();
    try {
      render(await api('/robot-voice/stop', {method: 'POST', body: JSON.stringify({voice_session_id: session.voice_session_id})}));
    } catch (error) {
      el('voice-detail').textContent = `Stop request failed: ${error.message}. Listening also stops when this page stops renewing it.`;
    } finally { busy = false; controls(); }
  });
  el('voice-robot').addEventListener('change', controls);

  return {
    refresh,
    reset() {
      stopPolling(); session = null; shownTurns = 0; busy = false;
      el('voice-state').textContent = VOICE_STATE_LABELS.stopped;
      el('voice-state').classList.remove('active');
      el('voice-detail').textContent = '';
      controls();
    },
  };
}
