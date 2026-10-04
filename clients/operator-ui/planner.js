// To-do, reminders and notes. Talks only to reachy-hub's /planner proxy;
// companion-core stores the records. All user text is rendered with
// textContent, never as HTML.
function createPlanner({api, isLoggedIn}) {
  const el = id => document.getElementById(id);
  let editingNote = null;
  let noteSearchTimer = null;
  let loadToken = 0;

  function node(tag, props = {}, ...children) {
    const item = document.createElement(tag);
    Object.assign(item, props);
    item.append(...children);
    return item;
  }
  function button(label, onClick, secondary = true) {
    const b = node('button', {type: 'button', textContent: label});
    if (secondary) b.className = 'secondary';
    b.addEventListener('click', onClick);
    return b;
  }
  function status(text) {
    for (const line of document.querySelectorAll('.planner-status')) line.textContent = text;
  }
  async function act(call, after = loadAll) {
    try { await call(); status(''); } catch (error) { if (isLoggedIn()) status(error.message); return; }
    if (isLoggedIn()) await after();
  }
  const send = (method, path, body) => api(path, {method, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  const when = iso => new Date(iso).toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'});

  function renderTasks(tasks) {
    const list = el('planner-task-list');
    const open = tasks.filter(t => t.status === 'open');
    const done = tasks.filter(t => t.status === 'done');
    list.replaceChildren(...[...open, ...done].map(task => {
      const isDone = task.status === 'done';
      const check = node('input', {type: 'checkbox', checked: isDone});
      check.setAttribute('aria-label', `${isDone ? 'Reopen' : 'Complete'}: ${task.text}`);
      check.addEventListener('change', () =>
        act(() => send('POST', `/planner/tasks/${encodeURIComponent(task.id)}/${isDone ? 'reopen' : 'complete'}`)));
      const text = node('span', {className: isDone ? 'planner-done' : '', textContent: task.text});
      const edit = button('Edit', () => {
        const next = window.prompt('Edit to-do', task.text);
        if (next && next.trim() && next.trim() !== task.text) {
          void act(() => send('PUT', `/planner/tasks/${encodeURIComponent(task.id)}`, {text: next.trim()}));
        }
      });
      const remove = button('Delete', () => act(() => send('DELETE', `/planner/tasks/${encodeURIComponent(task.id)}`)));
      return node('li', {className: 'planner-row'}, check, text, edit, remove);
    }));
    el('planner-task-empty').hidden = tasks.length > 0;
  }

  function renderReminders(reminders) {
    const list = el('planner-reminder-list');
    const now = Date.now();
    const sorted = [...reminders].sort((a, b) =>
      (a.status === b.status ? 0 : a.status === 'pending' ? -1 : 1) || new Date(a.due_at) - new Date(b.due_at));
    list.replaceChildren(...sorted.map(reminder => {
      const isDone = reminder.status === 'done';
      const overdue = !isDone && new Date(reminder.due_at).getTime() <= now;
      const label = node('span', {className: isDone ? 'planner-done' : ''}, reminder.text);
      const stamp = node('span', {className: overdue ? 'planner-overdue muted' : 'muted',
        textContent: `${when(reminder.due_at)}${overdue ? ' · due' : ''}`});
      const row = node('li', {className: 'planner-row'}, node('span', {className: 'planner-grow'}, label, node('br'), stamp));
      if (!isDone) row.append(button('Done', () => act(() => send('POST', `/planner/reminders/${encodeURIComponent(reminder.id)}/complete`))));
      row.append(button('Delete', () => act(() => send('DELETE', `/planner/reminders/${encodeURIComponent(reminder.id)}`))));
      return row;
    }));
    el('planner-reminder-empty').hidden = reminders.length > 0;
  }

  function renderNotes(notes) {
    const list = el('planner-note-list');
    list.replaceChildren(...notes.map(note => {
      const edit = button('Edit', () => startNoteEdit(note));
      const remove = button('Delete', () => act(() => send('DELETE', `/planner/notes/${encodeURIComponent(note.id)}`)));
      return node('li', {className: 'planner-note'},
        node('div', {className: 'section-title'}, node('strong', {textContent: note.title}), node('span', {}, edit, remove)),
        node('p', {className: 'planner-note-body', textContent: note.body}),
        node('span', {className: 'muted', textContent: `Updated ${when(note.updated_at)}`}));
    }));
    el('planner-note-empty').hidden = notes.length > 0;
  }

  function startNoteEdit(note) {
    editingNote = note ? note.id : null;
    el('planner-note-title').value = note ? note.title : '';
    el('planner-note-body').value = note ? note.body : '';
    el('planner-note-cancel').hidden = !note;
    el('planner-note-save').textContent = note ? 'Save note' : 'Add note';
    el('planner-note-title').focus();
  }

  async function loadNotes() {
    const q = el('planner-note-search').value.trim();
    renderNotes(await send('GET', `/planner/notes${q ? `?q=${encodeURIComponent(q)}` : ''}`));
  }

  async function loadAll() {
    if (!isLoggedIn()) return;
    const token = ++loadToken;
    try {
      const [tasks, reminders] = await Promise.all([send('GET', '/planner/tasks'), send('GET', '/planner/reminders')]);
      if (token !== loadToken || !isLoggedIn()) return;
      renderTasks(tasks); renderReminders(reminders);
      await loadNotes();
      status('');
    } catch (error) { if (isLoggedIn() && token === loadToken) status(error.message); }
  }

  el('planner-task-form').addEventListener('submit', async event => {
    event.preventDefault();
    const text = el('planner-task-text').value.trim();
    if (!text) return;
    await act(() => send('POST', '/planner/tasks', {text}));
    el('planner-task-text').value = '';
  });

  el('planner-reminder-form').addEventListener('submit', async event => {
    event.preventDefault();
    const text = el('planner-reminder-text').value.trim();
    const due = el('planner-reminder-due').value;
    if (!text || !due) return;
    await act(() => send('POST', '/planner/reminders', {text, due_at: new Date(due).toISOString()}));
    el('planner-reminder-text').value = ''; el('planner-reminder-due').value = '';
  });

  el('planner-note-form').addEventListener('submit', async event => {
    event.preventDefault();
    const title = el('planner-note-title').value.trim();
    if (!title) return;
    const body = {title, body: el('planner-note-body').value};
    await act(() => editingNote
      ? send('PUT', `/planner/notes/${encodeURIComponent(editingNote)}`, body)
      : send('POST', '/planner/notes', body));
    startNoteEdit(null);
  });
  el('planner-note-cancel').addEventListener('click', () => startNoteEdit(null));
  el('planner-note-search').addEventListener('input', () => {
    clearTimeout(noteSearchTimer);
    noteSearchTimer = setTimeout(() => void loadNotes().catch(error => isLoggedIn() && status(error.message)), 250);
  });
  for (const refresh of document.querySelectorAll('.planner-refresh')) refresh.addEventListener('click', () => void loadAll());

  function reset() {
    loadToken++; clearTimeout(noteSearchTimer); editingNote = null;
    for (const id of ['planner-task-list', 'planner-reminder-list', 'planner-note-list']) el(id).replaceChildren();
    for (const id of ['planner-task-text', 'planner-reminder-text', 'planner-reminder-due', 'planner-note-title', 'planner-note-body', 'planner-note-search']) el(id).value = '';
    status('');
  }
  return {load: loadAll, reset};
}
