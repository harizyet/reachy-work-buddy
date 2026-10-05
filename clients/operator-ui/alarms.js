// Alarms and TuneIn stations. Talks only to reachy-hub's /planner proxy; the
// hub decides delivery (privacy, presence) and core stores the records. All
// user and station text is rendered with textContent, never as HTML.
function createAlarms({api, isLoggedIn}) {
  const el = id => document.getElementById(id);
  let loadToken = 0;
  let stations = [];

  function node(tag, props = {}, ...children) {
    const item = document.createElement(tag);
    Object.assign(item, props);
    item.append(...children);
    return item;
  }
  function button(label, onClick) {
    const b = node('button', {type: 'button', textContent: label, className: 'secondary'});
    b.addEventListener('click', onClick);
    return b;
  }
  const status = text => { el('alarm-status').textContent = text; };
  const send = (method, path, body) => api(path, {method, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  const when = iso => new Date(iso).toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'});
  async function act(call) {
    try { await call(); status(''); } catch (error) { if (isLoggedIn()) status(error.message); return; }
    if (isLoggedIn()) await load();
  }

  function renderStations() {
    el('alarm-station-list').replaceChildren(...stations.map(station => node('li', {className: 'planner-row'},
      node('span', {className: 'planner-grow', textContent: station.name}),
      button('Remove', () => act(() => send('DELETE', `/planner/stations/${encodeURIComponent(station.id)}`))))));
    el('alarm-station-empty').hidden = stations.length > 0;
    const select = el('alarm-station');
    const chosen = select.value;
    select.replaceChildren(node('option', {value: '', textContent: 'Chime (no station)'}),
      ...stations.map(station => node('option', {value: station.id, textContent: station.name})));
    select.value = stations.some(s => s.id === chosen) ? chosen : '';
  }

  function renderAlarms(alarms) {
    const names = new Map(stations.map(s => [s.id, s.name]));
    const rank = {scheduled: 0, fired: 1, cancelled: 2};
    const sorted = [...alarms].sort((a, b) => rank[a.status] - rank[b.status] || new Date(a.due_at) - new Date(b.due_at));
    el('alarm-list').replaceChildren(...sorted.map(alarm => {
      const detail = [when(alarm.due_at), alarm.station_id ? names.get(alarm.station_id) || 'saved station' : 'chime',
        alarm.status === 'scheduled' ? '' : alarm.status, alarm.delivery || ''].filter(Boolean).join(' · ');
      const row = node('li', {className: 'planner-row'},
        node('span', {className: 'planner-grow'}, node('span', {className: alarm.status === 'scheduled' ? '' : 'planner-done', textContent: alarm.label}),
          node('br'), node('span', {className: 'muted', textContent: detail})));
      if (alarm.status === 'scheduled') row.append(button('Cancel', () => act(() => send('DELETE', `/planner/alarms/${encodeURIComponent(alarm.id)}`))));
      return row;
    }));
    el('alarm-empty').hidden = alarms.length > 0;
  }

  async function load() {
    if (!isLoggedIn()) return;
    const token = ++loadToken;
    try {
      const [savedStations, alarms] = await Promise.all([send('GET', '/planner/stations'), send('GET', '/planner/alarms')]);
      if (token !== loadToken || !isLoggedIn()) return;
      stations = savedStations; renderStations(); renderAlarms(alarms); status('');
    } catch (error) { if (isLoggedIn() && token === loadToken) status(error.message); }
  }

  el('alarm-form').addEventListener('submit', async event => {
    event.preventDefault();
    const label = el('alarm-label').value.trim();
    const due = el('alarm-due').value;
    if (!label || !due) return;
    const station_id = el('alarm-station').value || null;
    await act(() => send('POST', '/planner/alarms', {label, due_at: new Date(due).toISOString(), station_id}));
    el('alarm-label').value = ''; el('alarm-due').value = '';
  });

  el('alarm-stop').addEventListener('click', async () => {
    try {
      const result = await send('POST', '/planner/alarms/stop');
      status(result.stopped ? 'Alarm stopped.' : 'No alarm is playing.');
    } catch (error) { if (isLoggedIn()) status(error.message); }
  });

  el('alarm-search-form').addEventListener('submit', async event => {
    event.preventDefault();
    const query = el('alarm-search').value.trim();
    if (query.length < 2) return;
    const list = el('alarm-search-results');
    try {
      const found = await send('GET', `/planner/stations/search?q=${encodeURIComponent(query)}`);
      list.replaceChildren(...found.map(station => node('li', {className: 'planner-row'},
        node('span', {className: 'planner-grow'}, node('span', {textContent: station.name}), node('br'),
          node('span', {className: 'muted', textContent: station.detail})),
        button('Save', () => act(() => send('POST', '/planner/stations', {name: station.name, guide_id: station.guide_id}))))));
      el('alarm-search-empty').hidden = found.length > 0;
      status('');
    } catch (error) { if (isLoggedIn()) status(error.message); }
  });
  el('alarm-refresh').addEventListener('click', () => void load());

  function reset() {
    loadToken++; stations = [];
    for (const id of ['alarm-list', 'alarm-station-list', 'alarm-search-results']) el(id).replaceChildren();
    for (const id of ['alarm-label', 'alarm-due', 'alarm-search']) el(id).value = '';
    el('alarm-search-empty').hidden = true;
    status('');
  }
  return {load, reset};
}
