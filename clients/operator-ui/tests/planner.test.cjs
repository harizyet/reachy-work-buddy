// Real browser, fixture API: To Do and Reminders laid out like Apple Reminders, at both mounts and widths. Text is hostile
// on purpose and must render literally.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('to-do and reminders: circles, due dates, completed section, inline add and edit, new reminder sheet, literal text', async () => {
  const day = 86400000;
  const at = (days, hour, minute = 0) => { const d = new Date(Date.now() + days * day); d.setHours(hour, minute, 0, 0); return d.toISOString(); };
  const fresh = () => ({
    tasks: [
      {id: 't1', text: '<b>Sweep</b> garage', status: 'open'},
      {id: 't2', text: 'Plan menu', status: 'open'},
      {id: 't3', text: 'Old chore', status: 'done'},
    ],
    reminders: [
      {id: 'r1', text: 'Send <i>recipe</i>', due_at: at(1, 16), status: 'pending'},
      {id: 'r2', text: 'Missed call', due_at: at(-1, 9, 30), status: 'pending'},
      {id: 'r3', text: 'Book club', due_at: at(-3, 18), status: 'done'},
    ],
  });
  let data = fresh();
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
    if (route.startsWith('/planner/')) calls.push(`${req.method} ${route}`);
    if (route === '/planner/tasks' && req.method === 'GET') return json(data.tasks);
    if (route === '/planner/tasks' && req.method === 'POST') { data.tasks.push({id: 't9', status: 'open', ...body}); return json(data.tasks.at(-1)); }
    let m = route.match(/^\/planner\/tasks\/(t\d)(?:\/(complete|reopen))?$/);
    if (m) {
      const task = data.tasks.find(t => t.id === m[1]);
      if (req.method === 'DELETE') data.tasks = data.tasks.filter(t => t.id !== m[1]);
      else if (req.method === 'PUT') Object.assign(task, body);
      else task.status = m[2] === 'complete' ? 'done' : 'open';
      return json(task || {});
    }
    if (route === '/planner/reminders' && req.method === 'GET') return json(data.reminders);
    if (route === '/planner/reminders' && req.method === 'POST') { data.reminders.push({id: 'r9', status: 'pending', ...body}); return json(data.reminders.at(-1)); }
    m = route.match(/^\/planner\/reminders\/(r\d)(?:\/(complete))?$/);
    if (m) {
      const reminder = data.reminders.find(r => r.id === m[1]);
      if (req.method === 'DELETE') data.reminders = data.reminders.filter(r => r.id !== m[1]); else reminder.status = 'done';
      return json(reminder || {});
    }
    return json([]);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    for (const [mount, width] of [['/hub/ui/', 1440], ['/ui/', 390]]) {
      data = fresh(); calls.length = 0;
      const page = await browser.newPage({viewport: {width, height: 950}});
      const errors = []; page.on('pageerror', e => errors.push(e.message));
      await page.goto(`http://127.0.0.1:${server.address().port}${mount}`);

      // To Do
      await page.locator('#todo-tab').click();
      await page.waitForFunction(() => document.querySelectorAll('#planner-task-list .rl-row').length === 2);
      assert.equal(await page.textContent('#planner-task-title'), 'To Do');
      assert.equal(await page.locator('#planner-task-list .rl-text').first().textContent(), '<b>Sweep</b> garage');
      assert.equal(await page.locator('#planner-task-list b, #planner-reminder-list i').count(), 0);
      assert.equal(await page.textContent('#planner-task-completed'), '1 Completed · Show');
      assert.equal(await page.locator('#planner-task-done-list').isHidden(), true);
      await page.locator('#planner-task-completed').click();
      assert.equal(await page.locator('#planner-task-done-list .rl-row').count(), 1);
      assert.equal(await page.textContent('#planner-task-completed'), '1 Completed · Hide');
      await page.locator('#planner-task-done-list .rl-check').uncheck();          // reopen
      await page.waitForFunction(() => document.querySelectorAll('#planner-task-list .rl-row').length === 3);
      assert.ok(calls.includes('POST /planner/tasks/t3/reopen'));
      await page.locator('#planner-task-list .rl-check').nth(1).check();          // complete "Plan menu"
      await page.waitForFunction(() => document.querySelectorAll('#planner-task-list .rl-row').length === 2);
      assert.ok(calls.includes('POST /planner/tasks/t2/complete'));

      // inline rename: select the text, type, Enter
      await page.locator('#planner-task-list .rl-text').nth(1).click();
      await page.locator('#planner-task-list .rl-edit').fill('Old chore, renamed');
      await page.press('#planner-task-list .rl-edit', 'Enter');
      await page.waitForFunction(() => document.querySelectorAll('#planner-task-list .rl-text')[1]?.textContent === 'Old chore, renamed');
      assert.ok(calls.includes('PUT /planner/tasks/t3'));

      // inline add: New Reminder opens a row, Enter adds and opens the next, Escape closes
      await page.locator('#planner-task-new').click();
      await page.locator('#planner-task-list .rl-new-row .rl-edit').fill('Water plants');
      await page.press('#planner-task-list .rl-new-row .rl-edit', 'Enter');
      await page.waitForFunction(() => document.querySelectorAll('#planner-task-list .rl-row').length === 3 + 1);
      assert.ok(calls.includes('POST /planner/tasks'));
      assert.deepEqual(data.tasks.at(-1).text, 'Water plants');
      await page.press('#planner-task-list .rl-new-row .rl-edit', 'Escape');
      await page.waitForFunction(() => document.querySelectorAll('#planner-task-list .rl-new-row').length === 0);
      // delete
      await page.locator('#planner-task-list .rl-row').first().hover();
      await page.locator('#planner-task-list .rl-delete').first().click();
      await page.waitForFunction(() => document.querySelectorAll('#planner-task-list .rl-row').length === 2);
      assert.ok(calls.includes('DELETE /planner/tasks/t1'));

      // Reminders
      await page.locator('#reminders-tab').click();
      await page.waitForFunction(() => document.querySelectorAll('#planner-reminder-list .rl-row').length === 2);
      assert.equal(await page.textContent('#planner-reminder-title'), 'Reminders');
      const rows = page.locator('#planner-reminder-list .rl-row');
      assert.match(await rows.nth(0).textContent(), /Missed call/);     // earliest first
      assert.match(await rows.nth(0).locator('.rl-sub').textContent(), /^Yesterday, 9:30\s?AM · due$/);
      assert.equal(await rows.nth(0).locator('.rl-overdue').count(), 1);
      assert.match(await rows.nth(1).locator('.rl-sub').textContent(), /^Tomorrow, 4:00\s?PM$/);
      assert.equal(await rows.nth(1).locator('.rl-text').textContent(), 'Send <i>recipe</i>');
      assert.equal(await page.textContent('#planner-reminder-completed'), '1 Completed · Show');
      await page.locator('#planner-reminder-completed').click();
      assert.equal(await page.locator('#planner-reminder-done-list .rl-check').isDisabled(), true);   // the hub cannot reopen a reminder
      await rows.nth(0).locator('.rl-check').check();
      await page.waitForFunction(() => document.querySelectorAll('#planner-reminder-list .rl-row').length === 1);
      assert.ok(calls.includes('POST /planner/reminders/r2/complete'));

      // New Reminder sheet
      await page.locator('#planner-reminder-new').click();
      await page.waitForSelector('#reminder-dialog[open]');
      await page.fill('#reminder-text', 'Call Lisa');
      await page.fill('#reminder-date', '2030-03-04');
      await page.fill('#reminder-time', '17:30');
      await page.locator('#reminder-save').click();
      await page.waitForFunction(() => document.querySelectorAll('#planner-reminder-list .rl-row').length === 2);
      assert.ok(calls.includes('POST /planner/reminders'));
      assert.equal(data.reminders.at(-1).text, 'Call Lisa');
      assert.equal(new Date(data.reminders.at(-1).due_at).getTime(), new Date('2030-03-04T17:30').getTime());
      await page.locator('#planner-reminder-list .rl-row', {hasText: 'Call Lisa'}).hover();
      await page.locator('#planner-reminder-list .rl-row', {hasText: 'Call Lisa'}).locator('.rl-delete').click();
      await page.waitForFunction(() => document.querySelectorAll('#planner-reminder-list .rl-row').length === 1);
      assert.ok(calls.includes('DELETE /planner/reminders/r9'));

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
