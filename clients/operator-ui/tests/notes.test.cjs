// Real browser, fixture API: the Notes tab laid out like Apple Notes, at both mounts and widths. Note text is hostile
// on purpose and must render literally; edits save by themselves.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('notes tab groups by date, opens, autosaves, creates, searches and deletes with literal text', async () => {
  const day = 86400000;
  const iso = ago => new Date(Date.now() - ago * day).toISOString();
  const fresh = () => [
    {id: 'n1', title: '<img src=x onerror=boom()> Groceries', body: 'milk <b>eggs</b>\nbread', created_at: iso(0), updated_at: iso(0)},
    {id: 'n2', title: 'Baby names', body: '', created_at: iso(1), updated_at: iso(1)},
    {id: 'n3', title: 'Old idea', body: 'something from ages ago', created_at: iso(70), updated_at: iso(70)},
  ];
  let notes = fresh();
  const calls = [];
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://fixture');
    const route = url.pathname.replace(/^\/hub/, '');
    const json = (body, status = 200) => {res.writeHead(status, {'Content-Type': 'application/json'}); res.end(JSON.stringify(body));};
    if (route.startsWith('/ui/')) {
      const file = route.slice(4) || 'index.html';
      if (!/^[a-z_.-]+\.(html|js|css)$/.test(file)) return json({}, 404);
      res.setHeader('Content-Type', file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html');
      return res.end(fs.readFileSync(path.join(__dirname, '..', file)));
    }
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    const body = chunks.length ? JSON.parse(Buffer.concat(chunks)) : null;
    if (req.method !== 'GET') assert.equal(req.headers['x-reachy-csrf'], '1');
    if (route === '/auth/me') return json({username: 'owner'});
    if (route === '/status') return json({reachy_hub: {status: 'ok'}, companion_core: {status: 'ok'}, robots: [], owner_bound: true, default_user_id: 'owner', llm: {configured: true, usage: {data: null}}, telegram: {configured: false}});
    if (route.startsWith('/planner/notes')) calls.push(`${req.method} ${route}${url.search}`);
    if (route === '/planner/notes' && req.method === 'GET') {
      const q = (url.searchParams.get('q') || '').toLowerCase();
      return json(notes.filter(n => !q || `${n.title} ${n.body}`.toLowerCase().includes(q)));
    }
    if (route === '/planner/notes' && req.method === 'POST') {
      const note = {id: 'n9', created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...body};
      notes.unshift(note); return json(note);
    }
    const m = route.match(/^\/planner\/notes\/(n\d)$/);
    if (m && req.method === 'PUT') {
      const note = notes.find(n => n.id === m[1]); Object.assign(note, body, {updated_at: new Date().toISOString()}); return json(note);
    }
    if (m && req.method === 'DELETE') { notes = notes.filter(n => n.id !== m[1]); return json({deleted: true}); }
    return json([]);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    for (const [mount, width] of [['/hub/ui/', 1440], ['/ui/', 390]]) {
      notes = fresh(); calls.length = 0;
      const page = await browser.newPage({viewport: {width, height: 950}});
      const errors = []; page.on('pageerror', e => errors.push(e.message));
      await page.goto(`http://127.0.0.1:${server.address().port}${mount}`);
      await page.locator('#notes-tab').click();
      await page.waitForFunction(() => document.querySelectorAll('#notes-list .notes-row').length === 3);

      // grouped by when each note was last changed, newest first, with the first body line as the preview
      const sections = await page.locator('#notes-list .notes-section').allTextContents();
      assert.equal(sections[0], 'Today'); assert.equal(sections[1], 'Yesterday');
      assert.match(sections[2], /^[A-Z][a-z]+( \d{4})?$/);
      assert.match(await page.locator('#notes-list .notes-row').nth(0).textContent(), /milk <b>eggs<\/b>/);
      assert.match(await page.locator('#notes-list .notes-row').nth(1).textContent(), /No additional text/);
      assert.equal(await page.locator('#notes-list img, #notes-list b, #notes-edit-area b').count(), 0);
      assert.equal(await page.textContent('#notes-count'), '3');
      if (width > 760) assert.equal(await page.locator('#notes-edit-area').isHidden(), true);

      // open a note: title and text appear as plain field values; editing saves by itself
      await page.locator('#notes-list .notes-row').nth(0).click();
      await page.waitForSelector('#notes-edit-area:not([hidden])');
      assert.equal(await page.inputValue('#notes-title'), '<img src=x onerror=boom()> Groceries');
      assert.equal(await page.inputValue('#notes-body'), 'milk <b>eggs</b>\nbread');
      await page.fill('#notes-body', 'milk <b>eggs</b>\nbread\nbutter');
      await page.waitForFunction(() => document.getElementById('notes-status').textContent === 'Saved');
      assert.ok(calls.includes('PUT /planner/notes/n1'));
      assert.equal(notes[0].body, 'milk <b>eggs</b>\nbread\nbutter');

      // a new note is created on the first text and titled by what was typed
      await page.locator('#notes-new').click();
      assert.equal(await page.inputValue('#notes-title'), '');
      await page.fill('#notes-title', 'Trip plan');
      await page.press('#notes-title', 'Enter');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'notes-body');
      await page.fill('#notes-body', 'book flights');
      await page.waitForFunction(() => document.querySelectorAll('#notes-list .notes-row').length === 4);
      assert.ok(calls.includes('POST /planner/notes'));
      assert.deepEqual({title: notes[0].title, body: notes[0].body}, {title: 'Trip plan', body: 'book flights'});
      // a further edit updates that note rather than creating another
      await page.fill('#notes-body', 'book flights and hotel');
      await page.waitForFunction(() => document.getElementById('notes-status').textContent === 'Saved');
      await page.waitForTimeout(100);
      assert.equal(calls.filter(c => c === 'POST /planner/notes').length, 1);
      assert.ok(calls.includes('PUT /planner/notes/n9'));

      // a blank new note is not created
      const before = calls.length;
      await page.locator('#notes-new').click();
      await page.waitForTimeout(900);
      assert.equal(calls.slice(before).filter(c => c.startsWith('POST')).length, 0);

      // search goes to the hub (on a narrow screen the list is behind the editor until Back)
      if (width <= 760) await page.locator('#notes-back').click();
      await page.fill('#notes-search', 'ages');
      await page.waitForFunction(() => document.querySelectorAll('#notes-list .notes-row').length === 1);
      assert.ok(calls.some(c => c.includes('q=ages')));
      await page.fill('#notes-search', '');
      await page.waitForFunction(() => document.querySelectorAll('#notes-list .notes-row').length === 4);

      // delete asks first
      await page.locator('#notes-list .notes-row', {hasText: 'Old idea'}).click();
      await page.waitForFunction(() => document.getElementById('notes-title').value === 'Old idea');
      await page.locator('#notes-delete').click();
      await page.locator('#confirm-cancel').click();
      assert.equal(calls.some(c => c.startsWith('DELETE')), false);
      await page.locator('#notes-delete').click();
      await page.locator('#confirm-ok').click();
      await page.waitForFunction(() => document.querySelectorAll('#notes-list .notes-row').length === 3);
      assert.ok(calls.includes('DELETE /planner/notes/n3'));

      if (width <= 760) {
        // narrow: the list and the editor take turns, with a Back button
        assert.equal(await page.locator('.notes-list-pane').isVisible(), true);
        await page.locator('#notes-list .notes-row').first().click();
        assert.equal(await page.locator('.notes-list-pane').isHidden(), true);
        await page.locator('#notes-back').click();
        assert.equal(await page.locator('.notes-list-pane').isVisible(), true);
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
      assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally {
    await browser.close();
    server.close();
  }
});
