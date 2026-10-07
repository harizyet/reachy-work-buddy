// To Do and Reminders, laid out like the Apple Reminders app: coloured list title, round check circles, the due date under a
// reminder, a collapsed Completed section and a New Reminder button. Talks only to reachy-hub's /planner proxy; companion-core
// stores the records. All user text is rendered with textContent, never as HTML.
function createPlanner({api, isLoggedIn}) {
  const el = id => document.getElementById(id);
  let loadToken = 0;
  let tasks = [];
  let reminders = [];
  let addingTask = false;      // the inline "new to-do" row is open
  let editingTask = null;      // id of the to-do being renamed inline
  const showDone = {task: false, reminder: false};

  function node(tag, props = {}, ...children) {
    const item = document.createElement(tag);
    Object.assign(item, props);
    item.append(...children);
    return item;
  }
  function status(text) {
    for (const line of document.querySelectorAll('.planner-status')) line.textContent = text;
  }
  async function act(call, after = loadAll) {
    try { await call(); status(''); } catch (error) { if (isLoggedIn()) status(error.message); return; }
    if (isLoggedIn()) await after();
  }
  const send = (method, path, body) => api(path, {method, ...(body === undefined ? {} : {body: JSON.stringify(body)})});

  // "Today, 4:00 PM", "Tomorrow, 9:00 AM", otherwise a short date and the time, like the Reminders subtitle.
  function dueText(iso, now = new Date()) {
    const due = new Date(iso);
    const days = Math.round((new Date(due.getFullYear(), due.getMonth(), due.getDate()) - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
    const time = due.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
    const day = days === 0 ? 'Today' : days === 1 ? 'Tomorrow' : days === -1 ? 'Yesterday' : due.toLocaleDateString([], {dateStyle: 'short'});
    return `${day}, ${time}`;
  }

  function circle(checked, label, onChange, disabled = false) {
    const box = node('input', {type: 'checkbox', checked, disabled, className: 'rl-check'});
    box.setAttribute('aria-label', label);
    box.addEventListener('change', onChange);
    return box;
  }
  function deleteButton(label, onClick) {
    const b = node('button', {type: 'button', className: 'rl-delete secondary', textContent: '✕'});
    b.setAttribute('aria-label', label);
    b.addEventListener('click', onClick);
    return b;
  }
  function completedToggle(kind, count) {
    const toggle = el(`planner-${kind}-completed`);
    toggle.hidden = count === 0;
    toggle.textContent = `${count} Completed · ${showDone[kind] ? 'Hide' : 'Show'}`;
    toggle.setAttribute('aria-expanded', String(showDone[kind]));
    el(`planner-${kind}-done-list`).hidden = count === 0 || !showDone[kind];
  }

  // --- To Do ---------------------------------------------------------------------------------------------------
  function taskRow(task) {
    const isDone = task.status === 'done';
    const check = circle(isDone, `${isDone ? 'Reopen' : 'Complete'}: ${task.text}`,
      () => act(() => send('POST', `/planner/tasks/${encodeURIComponent(task.id)}/${isDone ? 'reopen' : 'complete'}`)));
    let body;
    if (editingTask === task.id) {
      body = node('input', {className: 'rl-edit', value: task.text, maxLength: 2000});
      body.setAttribute('aria-label', 'Edit to-do');
      const finish = save => {
        const next = body.value.trim();
        editingTask = null;
        if (save && next && next !== task.text) void act(() => send('PUT', `/planner/tasks/${encodeURIComponent(task.id)}`, {text: next}));
        else renderTasks();
      };
      body.addEventListener('keydown', event => { if (event.key === 'Enter') finish(true); if (event.key === 'Escape') finish(false); });
      body.addEventListener('blur', () => { if (editingTask === task.id) finish(true); });
      setTimeout(() => body.focus(), 0);
    } else {
      body = node('button', {type: 'button', className: `rl-text${isDone ? ' planner-done' : ''}`, textContent: task.text});
      body.setAttribute('aria-label', `Edit: ${task.text}`);
      body.addEventListener('click', () => { editingTask = task.id; renderTasks(); });
    }
    return node('li', {className: 'rl-row'}, check, node('span', {className: 'rl-body'}, body),
      deleteButton(`Delete: ${task.text}`, () => act(() => send('DELETE', `/planner/tasks/${encodeURIComponent(task.id)}`))));
  }
  function newTaskRow() {
    const input = node('input', {className: 'rl-edit', maxLength: 2000, placeholder: 'New reminder'});
    input.setAttribute('aria-label', 'New to-do');
    const add = () => {
      const text = input.value.trim();
      if (!text) { addingTask = false; renderTasks(); return; }
      void act(() => send('POST', '/planner/tasks', {text}));   // the row reopens (empty) after the list reloads
    };
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); add(); }
      if (event.key === 'Escape') { addingTask = false; renderTasks(); }
    });
    input.addEventListener('blur', () => { if (!input.value.trim()) { addingTask = false; renderTasks(); } });
    setTimeout(() => input.focus(), 0);
    return node('li', {className: 'rl-row rl-new-row'}, node('input', {type: 'checkbox', disabled: true, className: 'rl-check', ariaHidden: 'true'}), node('span', {className: 'rl-body'}, input));
  }
  function renderTasks() {
    const open = tasks.filter(t => t.status === 'open');
    const done = tasks.filter(t => t.status === 'done');
    el('planner-task-list').replaceChildren(...open.map(taskRow), ...(addingTask ? [newTaskRow()] : []));
    el('planner-task-done-list').replaceChildren(...done.map(taskRow));
    completedToggle('task', done.length);
    el('planner-task-empty').hidden = tasks.length > 0 || addingTask;
  }

  // --- Reminders -----------------------------------------------------------------------------------------------
  function reminderRow(reminder) {
    const isDone = reminder.status === 'done';
    const overdue = !isDone && new Date(reminder.due_at).getTime() <= Date.now();
    // The hub can complete a reminder but not reopen one, so a ticked circle stays ticked.
    const check = circle(isDone, `${isDone ? 'Completed' : 'Complete'}: ${reminder.text}`,
      () => act(() => send('POST', `/planner/reminders/${encodeURIComponent(reminder.id)}/complete`)), isDone);
    return node('li', {className: 'rl-row'}, check,
      node('span', {className: 'rl-body'},
        node('span', {className: `rl-text${isDone ? ' planner-done' : ''}`, textContent: reminder.text}),
        node('span', {className: `rl-sub${overdue ? ' rl-overdue' : ''}`, textContent: dueText(reminder.due_at) + (overdue ? ' · due' : '')})),
      deleteButton(`Delete: ${reminder.text}`, () => act(() => send('DELETE', `/planner/reminders/${encodeURIComponent(reminder.id)}`))));
  }
  function renderReminders() {
    const byDue = (a, b) => new Date(a.due_at) - new Date(b.due_at);
    const pending = reminders.filter(r => r.status !== 'done').sort(byDue);
    const done = reminders.filter(r => r.status === 'done').sort((a, b) => byDue(b, a));
    el('planner-reminder-list').replaceChildren(...pending.map(reminderRow));
    el('planner-reminder-done-list').replaceChildren(...done.map(reminderRow));
    completedToggle('reminder', done.length);
    el('planner-reminder-empty').hidden = reminders.length > 0;
  }

  async function loadAll() {
    if (!isLoggedIn()) return;
    const token = ++loadToken;
    try {
      const [loadedTasks, loadedReminders] = await Promise.all([send('GET', '/planner/tasks'), send('GET', '/planner/reminders')]);
      if (token !== loadToken || !isLoggedIn()) return;
      tasks = loadedTasks; reminders = loadedReminders;
      renderTasks(); renderReminders(); status('');
    } catch (error) { if (isLoggedIn() && token === loadToken) status(error.message); }
  }

  el('planner-task-new').addEventListener('click', () => { addingTask = true; renderTasks(); });
  for (const kind of ['task', 'reminder']) {
    el(`planner-${kind}-completed`).addEventListener('click', () => {
      showDone[kind] = !showDone[kind];
      if (kind === 'task') renderTasks(); else renderReminders();
    });
  }

  // New Reminder sheet: a title, a date and a time.
  function openReminderSheet() {
    const soon = new Date(Date.now() + 3600000);
    soon.setMinutes(0, 0, 0);
    const pad = n => String(n).padStart(2, '0');
    el('reminder-text').value = '';
    el('reminder-date').value = `${soon.getFullYear()}-${pad(soon.getMonth() + 1)}-${pad(soon.getDate())}`;
    el('reminder-time').value = `${pad(soon.getHours())}:${pad(soon.getMinutes())}`;
    el('reminder-dialog').showModal();
    el('reminder-text').focus();
  }
  el('planner-reminder-new').addEventListener('click', openReminderSheet);
  el('reminder-cancel').addEventListener('click', () => el('reminder-dialog').close());
  el('reminder-form').addEventListener('submit', async event => {
    event.preventDefault();
    const text = el('reminder-text').value.trim();
    const date = el('reminder-date').value, time = el('reminder-time').value;
    if (!text || !date || !time) return;
    el('reminder-dialog').close();
    await act(() => send('POST', '/planner/reminders', {text, due_at: new Date(`${date}T${time}`).toISOString()}));
  });
  for (const refresh of document.querySelectorAll('.planner-refresh')) refresh.addEventListener('click', () => void loadAll());

  function reset() {
    loadToken++; tasks = []; reminders = []; addingTask = false; editingTask = null;
    showDone.task = false; showDone.reminder = false;
    for (const id of ['planner-task-list', 'planner-task-done-list', 'planner-reminder-list', 'planner-reminder-done-list']) el(id).replaceChildren();
    for (const kind of ['task', 'reminder']) el(`planner-${kind}-completed`).hidden = true;
    if (el('reminder-dialog').open) el('reminder-dialog').close();
    status('');
  }
  return {load: loadAll, reset};
}
