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
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];  // weekday numbers 0 = Monday, as the server counts them
  let editing = false;     // list "Edit" mode: shows a delete control on every row
  let editingId = null;    // the alarm open in the sheet, null when adding
  let alarmsNow = [];
  let repeatDays = new Set();

  function timeParts(iso) {
    const parts = new Intl.DateTimeFormat([], {hour: 'numeric', minute: '2-digit'}).formatToParts(new Date(iso));
    const part = type => parts.find(p => p.type === type)?.value || '';
    return {time: `${part('hour')}:${part('minute')}`, suffix: part('dayPeriod')};
  }
  function repeatText(days) {
    const set = [...days].sort((a, b) => a - b).join();
    if (!set) return '';
    if (set === '0,1,2,3,4,5,6') return 'Every day';
    if (set === '0,1,2,3,4') return 'Weekdays';
    if (set === '5,6') return 'Weekends';
    return [...days].sort((a, b) => a - b).map(d => DAYS[d]).join(', ');
  }
  function dayLabel(iso) {
    const due = new Date(iso), today = new Date();
    const days = Math.round((new Date(due.getFullYear(), due.getMonth(), due.getDate()) - new Date(today.getFullYear(), today.getMonth(), today.getDate())) / 86400000);
    if (days === 0) return 'Today';
    if (days === 1) return 'Tomorrow';
    return due.toLocaleDateString([], {weekday: 'short', day: 'numeric', month: 'short'});
  }
  const isOn = alarm => alarm.enabled !== false && alarm.status === 'scheduled';
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
    alarmsNow = alarms.filter(a => a.status !== 'cancelled');
    const names = new Map(stations.map(s => [s.id, s.name]));
    const minutes = a => { const d = new Date(a.due_at); return d.getHours() * 60 + d.getMinutes(); };
    const sorted = [...alarmsNow].sort((a, b) => minutes(a) - minutes(b));
    el('alarm-list').replaceChildren(...sorted.map(alarm => {
      const on = isOn(alarm);
      const {time, suffix} = timeParts(alarm.due_at);
      const repeat = repeatText(alarm.repeat || []);
      const sub = [alarm.label, repeat || (on ? dayLabel(alarm.due_at) : '')].filter(Boolean).join(', ');
      const extra = [alarm.station_id ? names.get(alarm.station_id) || 'saved station' : '', (alarm.volume ?? 100) !== 100 ? `${alarm.volume}% volume` : '',
        alarm.status === 'fired' && alarm.delivery ? `last: ${alarm.delivery}` : ''].filter(Boolean).join(' · ');
      const toggle = node('input', {type: 'checkbox', checked: on, className: 'alarm-switch'});
      toggle.setAttribute('role', 'switch');
      toggle.setAttribute('aria-label', `${alarm.label} ${time} ${suffix}`.trim());
      toggle.addEventListener('change', () => act(() => send('PATCH', `/planner/alarms/${encodeURIComponent(alarm.id)}`, {enabled: toggle.checked})));
      const open = node('button', {type: 'button', className: 'alarm-open'},
        node('span', {className: 'alarm-time'}, node('span', {className: 'alarm-clock-big', textContent: time}), node('span', {className: 'alarm-suffix', textContent: suffix})),
        node('span', {className: 'alarm-sub', textContent: sub}),
        ...(extra ? [node('span', {className: 'alarm-extra', textContent: extra})] : []));
      open.addEventListener('click', () => openSheet(alarm));
      const row = node('li', {className: `alarm-row${on ? '' : ' off'}`});
      if (editing) {
        const remove = node('button', {type: 'button', className: 'alarm-remove', textContent: '−'});
        remove.setAttribute('aria-label', `Delete alarm ${alarm.label}`);
        remove.addEventListener('click', () => act(() => send('DELETE', `/planner/alarms/${encodeURIComponent(alarm.id)}`)));
        row.append(remove);
      }
      row.append(open, toggle);
      return row;
    }));
    el('alarm-empty').hidden = sorted.length > 0;
    el('alarm-edit').textContent = editing ? 'Done' : 'Edit';
  }

  // --- the Add Alarm / Edit Alarm sheet ---------------------------------------------------------------
  function fillWheels() {
    if (el('alarm-hour').options.length) return;
    for (let h = 1; h <= 12; h++) el('alarm-hour').append(node('option', {value: String(h), textContent: String(h)}));
    for (let m = 0; m < 60; m++) el('alarm-minute').append(node('option', {value: String(m), textContent: String(m).padStart(2, '0')}));
    el('alarm-days').replaceChildren(...DAYS.map((name, day) => {
      const b = node('button', {type: 'button', className: 'day-toggle', textContent: name});
      b.setAttribute('aria-pressed', 'false'); b.dataset.day = String(day);
      b.addEventListener('click', () => { repeatDays.has(day) ? repeatDays.delete(day) : repeatDays.add(day); showRepeat(); });
      return b;
    }));
  }
  function showRepeat() {
    for (const b of el('alarm-days').children) b.setAttribute('aria-pressed', String(repeatDays.has(Number(b.dataset.day))));
    el('alarm-repeat-text').textContent = repeatText(repeatDays) || 'Never';
  }
  function setWheels(date) {
    const h24 = date.getHours();
    el('alarm-hour').value = String(h24 % 12 || 12);
    el('alarm-minute').value = String(date.getMinutes());
    el('alarm-ampm').value = h24 >= 12 ? 'PM' : 'AM';
    centerWheels();
  }
  // Keep each wheel's chosen value in the middle of its window, like a picker.
  function centerWheels() {
    for (const id of ['alarm-hour', 'alarm-minute', 'alarm-ampm']) {
      const select = el(id);
      const option = select.selectedOptions[0];
      if (option) select.scrollTop = option.offsetTop - (select.clientHeight - option.offsetHeight) / 2;
    }
  }
  function wheelTime() {
    const h = Number(el('alarm-hour').value) % 12 + (el('alarm-ampm').value === 'PM' ? 12 : 0);
    return `${String(h).padStart(2, '0')}:${String(Number(el('alarm-minute').value)).padStart(2, '0')}`;
  }
  function openSheet(alarm) {
    fillWheels();
    editingId = alarm ? alarm.id : null;
    el('alarm-dialog-title').textContent = alarm ? 'Edit Alarm' : 'Add Alarm';
    const base = new Date();
    if (alarm) setWheels(new Date(alarm.due_at)); else { base.setMinutes(base.getMinutes() + 1); setWheels(base); }
    repeatDays = new Set(alarm?.repeat || []);
    el('alarm-label').value = alarm ? alarm.label : 'Alarm';
    renderStations();
    el('alarm-station').value = alarm?.station_id && stations.some(s => s.id === alarm.station_id) ? alarm.station_id : '';
    el('alarm-volume').value = String(alarm?.volume ?? 100);
    el('alarm-volume-value').textContent = `${el('alarm-volume').value}%`;
    el('alarm-delete').hidden = !alarm;
    showRepeat();
    el('alarm-dialog').showModal();
    centerWheels();
  }
  for (const id of ['alarm-hour', 'alarm-minute', 'alarm-ampm']) el(id).addEventListener('change', centerWheels);
  el('alarm-add').addEventListener('click', () => openSheet(null));
  el('alarm-edit').addEventListener('click', () => { editing = !editing; renderAlarms(alarmsNow); });
  el('alarm-cancel').addEventListener('click', () => el('alarm-dialog').close());
  el('alarm-delete').addEventListener('click', async () => {
    const id = editingId; el('alarm-dialog').close();
    if (id) await act(() => send('DELETE', `/planner/alarms/${encodeURIComponent(id)}`));
  });

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
    if (!label) return;
    const body = {label, time: wheelTime(), repeat: [...repeatDays].sort((a, b) => a - b), station_id: el('alarm-station').value || null,
      volume: Number(el('alarm-volume').value)};
    const id = editingId;
    el('alarm-dialog').close();
    await act(() => id ? send('PATCH', `/planner/alarms/${encodeURIComponent(id)}`, body) : send('POST', '/planner/alarms', body));
  });

  el('alarm-volume').addEventListener('input', () => { el('alarm-volume-value').textContent = `${el('alarm-volume').value}%`; });

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
    for (const id of ['alarm-search']) el(id).value = '';
    alarmsNow = []; editing = false; editingId = null;
    if (el('alarm-dialog').open) el('alarm-dialog').close();
    el('alarm-search-empty').hidden = true;
    status('');
  }
  return {load, reset};
}
