// Notes, laid out like the Apple Notes web app: folders, a month-grouped list and an editor whose first field is the
// title. Talks only to reachy-hub's /planner proxy; companion-core stores the records. All note text is rendered with
// textContent or as a field value, never as HTML. Edits save by themselves shortly after typing stops.
function createNotes({api, isLoggedIn}) {
  const el = id => document.getElementById(id);
  const SAVE_DELAY_MS = 700;
  let notes = [];
  let selectedId = null;        // the note open in the editor; null for none or a brand-new note
  let draftOpen = false;        // a new note is open and not saved yet
  let saveTimer = null;
  let searchTimer = null;
  let loadToken = 0;
  let saving = Promise.resolve();

  const send = (method, path, body) => api(path, {method, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  const status = text => { el('notes-status').textContent = text; };
  function node(tag, props = {}, ...children) {
    const item = document.createElement(tag);
    Object.assign(item, props);
    item.append(...children);
    return item;
  }

  // --- grouping and row text, like the iOS list --------------------------------------------------------------
  const startOfDay = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  function daysAgo(iso, now) { return Math.round((startOfDay(now) - startOfDay(new Date(iso))) / 86400000); }
  function sectionOf(iso, now = new Date()) {
    const days = daysAgo(iso, now);
    if (days <= 0) return 'Today';
    if (days === 1) return 'Yesterday';
    if (days <= 7) return 'Previous 7 Days';
    if (days <= 30) return 'Previous 30 Days';
    const d = new Date(iso);
    return d.getFullYear() === now.getFullYear()
      ? d.toLocaleDateString([], {month: 'long'})
      : d.toLocaleDateString([], {month: 'long', year: 'numeric'});
  }
  function shortDate(iso, now = new Date()) {
    const days = daysAgo(iso, now), d = new Date(iso);
    if (days <= 0) return d.toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
    if (days === 1) return 'Yesterday';
    if (days <= 7) return d.toLocaleDateString([], {weekday: 'long'});
    return d.toLocaleDateString([], {dateStyle: 'short'});
  }
  const preview = note => (note.body || '').split('\n').map(line => line.trim()).find(Boolean) || 'No additional text';

  function renderList() {
    const list = el('notes-list');
    const sorted = [...notes].sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
    const groups = new Map();
    for (const note of sorted) {
      const name = sectionOf(note.updated_at);
      if (!groups.has(name)) groups.set(name, []);
      groups.get(name).push(note);
    }
    list.replaceChildren(...[...groups].flatMap(([name, items]) => [
      node('h3', {className: 'notes-section', textContent: name}),
      node('ul', {className: 'notes-group'}, ...items.map(note => {
        const open = node('button', {type: 'button', className: 'notes-row'},
          node('strong', {textContent: note.title}),
          node('span', {className: 'notes-row-sub'}, node('span', {textContent: shortDate(note.updated_at)}), ' ', node('span', {className: 'muted', textContent: preview(note)})),
          node('span', {className: 'notes-row-folder muted', textContent: '🗀 Notes'}));
        open.setAttribute('aria-current', String(note.id === selectedId));
        open.addEventListener('click', () => void openNote(note.id));
        return node('li', {className: note.id === selectedId ? 'selected' : ''}, open);
      })),
    ]));
    el('notes-empty').hidden = notes.length > 0;
    el('notes-count').textContent = String(notes.length);
  }

  function showEditor(open) {
    el('notes-edit-area').hidden = !open;
    el('notes-placeholder').hidden = open;
    el('notes-delete').disabled = !selectedId;
    el('notes-app').classList.toggle('notes-editing', open);
  }

  // --- saving ------------------------------------------------------------------------------------------------
  const fieldTitle = () => el('notes-title').value.trim();
  const fieldBody = () => el('notes-body').value;
  function dirtyAgainst(note) { return !note || fieldTitle() !== note.title || fieldBody() !== (note.body || ''); }

  function queueSave() {
    clearTimeout(saveTimer);
    status('Editing…');
    saveTimer = setTimeout(() => void flush(), SAVE_DELAY_MS);
  }
  // Saves whatever is in the editor now. A blank new note is never created; a title left empty falls back to the first line of
  // the text, then "New Note", because notes need a title.
  function flush() {
    clearTimeout(saveTimer);
    saving = saving.then(async () => {
      if (!isLoggedIn()) return;
      const current = selectedId ? notes.find(n => n.id === selectedId) : null;
      if (!selectedId && !draftOpen) return;
      if (!dirtyAgainst(current)) { status(current || selectedId ? 'Saved' : ''); return; }
      const text = fieldBody();
      if (!selectedId && !fieldTitle() && !text.trim()) return;
      const firstLine = text.split('\n').map(l => l.trim()).find(Boolean) || '';
      const title = (fieldTitle() || firstLine || 'New Note').slice(0, 200);
      try {
        status('Saving…');
        const payload = {title, body: text};
        const saved = selectedId
          ? await send('PUT', `/planner/notes/${encodeURIComponent(selectedId)}`, payload)
          : await send('POST', '/planner/notes', payload);
        if (!selectedId) { selectedId = saved.id; draftOpen = false; el('notes-delete').disabled = false; }
        notes = notes.some(n => n.id === saved.id) ? notes.map(n => (n.id === saved.id ? saved : n)) : [saved, ...notes];
        if (document.activeElement !== el('notes-title') && !el('notes-title').value) el('notes-title').value = saved.title;
        renderList(); showMeta(saved); status('Saved');
      } catch (error) { if (isLoggedIn()) status(`Not saved: ${error.message}`); }
    });
    return saving;
  }

  function showMeta(note) {
    el('notes-meta').textContent = note ? new Date(note.updated_at).toLocaleString([], {dateStyle: 'long', timeStyle: 'short'}) : '';
  }

  async function openNote(id) {
    await flush();
    const note = notes.find(n => n.id === id);
    if (!note) return;
    selectedId = id; draftOpen = false;
    el('notes-title').value = note.title; el('notes-body').value = note.body || '';
    showMeta(note); status(''); showEditor(true); renderList();
  }

  async function newNote() {
    await flush();
    selectedId = null; draftOpen = true;
    el('notes-title').value = ''; el('notes-body').value = '';
    showMeta(null); status(''); showEditor(true); renderList();
    el('notes-title').focus();
  }

  function confirmDelete(title) {
    return new Promise(resolve => {
      const dialog = el('confirm-dialog');
      el('confirm-title').textContent = 'Delete this note?'; el('confirm-text').textContent = `“${title}” will be deleted. This cannot be undone.`; el('confirm-ok').textContent = 'Delete';
      const done = value => { el('confirm-ok').onclick = null; el('confirm-cancel').onclick = null; dialog.close(); resolve(value); };
      el('confirm-ok').onclick = () => done(true); el('confirm-cancel').onclick = () => done(false);
      dialog.addEventListener('cancel', () => done(false), {once: true});
      dialog.showModal();
    });
  }

  async function deleteSelected() {
    const note = notes.find(n => n.id === selectedId);
    if (!note || !await confirmDelete(note.title)) return;
    clearTimeout(saveTimer);
    try {
      await send('DELETE', `/planner/notes/${encodeURIComponent(note.id)}`);
      notes = notes.filter(n => n.id !== note.id);
      selectedId = null; draftOpen = false;
      showEditor(false); renderList(); status('');
    } catch (error) { if (isLoggedIn()) status(error.message); }
  }

  async function load() {
    if (!isLoggedIn()) return;
    const token = ++loadToken;
    const q = el('notes-search').value.trim();
    try {
      const found = await send('GET', `/planner/notes${q ? `?q=${encodeURIComponent(q)}` : ''}`);
      if (token !== loadToken || !isLoggedIn()) return;
      notes = found;
      renderList();
      if (selectedId && !notes.some(n => n.id === selectedId) && !q) { selectedId = null; showEditor(draftOpen); }
    } catch (error) { if (isLoggedIn() && token === loadToken) status(error.message); }
  }

  el('notes-new').addEventListener('click', () => void newNote());
  el('notes-delete').addEventListener('click', () => void deleteSelected());
  el('notes-back').addEventListener('click', async () => { await flush(); selectedId = null; draftOpen = false; showEditor(false); renderList(); });
  el('notes-refresh').addEventListener('click', () => void flush().then(load));
  el('notes-title').addEventListener('input', queueSave);
  el('notes-body').addEventListener('input', queueSave);
  el('notes-title').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); el('notes-body').focus(); } });
  el('notes-search').addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => void load(), 250);
  });

  function reset() {
    loadToken++; clearTimeout(saveTimer); clearTimeout(searchTimer);
    notes = []; selectedId = null; draftOpen = false; saving = Promise.resolve();
    el('notes-list').replaceChildren(); el('notes-search').value = ''; el('notes-title').value = ''; el('notes-body').value = '';
    showEditor(false); status(''); el('notes-count').textContent = '0';
  }
  return {load, reset, flush};
}
