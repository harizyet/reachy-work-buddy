// Real browser, fixture API: the Alarms tab at both mounts. Station and alarm
// text is hostile on purpose and must render literally.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('alarms tab lists, adds, cancels, stops and picks stations with literal text', async () => {
  const alarms = [
    {id: 'a1', label: '<img src=x onerror=boom()> wake', due_at: '2030-01-02T07:00:00Z', station_id: 's1', status: 'scheduled', enabled: true, repeat: [0, 1, 2, 3, 4], volume: 100, delivery: null},
    {id: 'a2', label: 'old', due_at: '2020-01-02T06:15:00Z', station_id: null, status: 'fired', enabled: true, repeat: [], volume: 100, delivery: 'telegram: privacy mode'},
  ];
  const stations = [{id: 's1', name: '<b>Jazz FM</b>', guide_id: 's111'}];
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
    if (route.startsWith('/planner/')) calls.push(`${req.method} ${route}${url.search}`);
    if (route === '/planner/alarms' && req.method === 'GET') return json(alarms);
    if (route === '/planner/alarms' && req.method === 'POST') { alarms.push({id: 'a3', status: 'scheduled', enabled: true, delivery: null, due_at: '2030-01-03T17:30:00Z', ...body}); return json(alarms.at(-1)); }
    let am = route.match(/^\/planner\/alarms\/(a\d)$/);
    if (am && req.method === 'PATCH') { const alarm = alarms.find(a => a.id === am[1]); Object.assign(alarm, body); if (body.enabled) alarm.status = 'scheduled'; return json(alarm); }
    if (route === '/planner/alarms/stop') return json({stopped: true});
    if (am && req.method === 'DELETE') { alarms.find(a => a.id === am[1]).status = 'cancelled'; return json({}); }
    if (route === '/planner/stations' && req.method === 'GET') return json(stations);
    if (route === '/planner/stations' && req.method === 'POST') { stations.push({id: 's2', ...body}); return json(stations.at(-1)); }
    if (route === '/planner/stations/search') return json([{guide_id: 's222', name: '<i>Rock</i>', detail: 'hits'}]);
    return json([]);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    for (const [mount, width] of [['/hub/ui/', 1440], ['/ui/', 390]]) {
      calls.length = 0;
      for (const a of alarms) { a.status = a.id === 'a2' ? 'fired' : 'scheduled'; a.enabled = true; }
      const page = await browser.newPage({viewport: {width, height: 950}, timezoneId: 'UTC'});
      const errors = []; page.on('pageerror', e => errors.push(e.message));
      await page.goto(`http://127.0.0.1:${server.address().port}${mount}`);
      await page.locator('#alarms-tab').click();
      const rows = page.locator('#alarm-list li');
      await page.waitForFunction(() => document.querySelectorAll('#alarm-list li').length === 2);
      // iPhone-Clock list: big time, label and repeat, an on/off switch; finished one-time alarms show off
      assert.match(await rows.nth(0).textContent(), /6:15\s*AM/);
      assert.match(await rows.nth(1).textContent(), /7:00\s*AM/);
      assert.match(await rows.nth(1).textContent(), /<img src=x onerror=boom\(\)> wake, Weekdays/);
      assert.match(await rows.nth(1).textContent(), /<b>Jazz FM<\/b>/);
      assert.match(await rows.nth(0).textContent(), /telegram: privacy mode/);
      assert.equal(await page.locator('#alarm-list img, #alarm-station-list b').count(), 0);
      assert.equal(await rows.nth(1).getByRole('switch').isChecked(), true);
      assert.equal(await rows.nth(0).getByRole('switch').isChecked(), false);
      await rows.nth(0).getByRole('switch').click();
      await page.waitForFunction(() => document.querySelectorAll('#alarm-list .alarm-switch')[0].checked);
      assert.ok(calls.includes('PATCH /planner/alarms/a2'));
      await rows.nth(1).getByRole('switch').click();
      await page.waitForFunction(() => !document.querySelectorAll('#alarm-list .alarm-switch')[1].checked);
      assert.equal(alarms[0].enabled, false);

      // Add Alarm sheet: wheels, repeat days, label, sound, volume
      await page.locator('#alarm-add').click();
      await page.waitForSelector('#alarm-dialog[open]');
      assert.equal(await page.textContent('#alarm-dialog-title'), 'Add Alarm');
      assert.equal(await page.locator('#alarm-form #alarm-volume').count(), 1);
      assert.equal(await page.locator('#planner-task-form #alarm-volume').count(), 0);
      await page.locator('#alarm-hour').selectOption('5');
      await page.locator('#alarm-minute').selectOption('30');
      await page.locator('#alarm-ampm').selectOption('PM');
      await page.locator('#alarm-days [data-day="0"]').click();
      await page.locator('#alarm-days [data-day="2"]').click();
      assert.equal(await page.textContent('#alarm-repeat-text'), 'Mon, Wed');
      await page.locator('#alarm-label').fill('cake');
      await page.locator('#alarm-station').selectOption('s1');
      await page.locator('#alarm-volume').evaluate(input => { input.value = '250'; input.dispatchEvent(new Event('input', {bubbles: true})); });
      assert.equal(await page.locator('#alarm-volume-value').textContent(), '250%');
      await page.locator('#alarm-save').click();
      await page.waitForFunction(() => document.querySelectorAll('#alarm-list li').length === 3);
      assert.ok(calls.includes('POST /planner/alarms'));
      assert.deepEqual(
        {...alarms.at(-1), id: undefined, status: undefined, enabled: undefined, delivery: undefined, due_at: undefined},
        {label: 'cake', time: '17:30', repeat: [0, 2], station_id: 's1', volume: 250, id: undefined, status: undefined, enabled: undefined, delivery: undefined, due_at: undefined});

      // open an existing alarm: the sheet shows its time and repeat; changes are patched; it can be deleted from the sheet
      await page.locator('#alarm-list li').nth(1).locator('.alarm-open').click();
      await page.waitForSelector('#alarm-dialog[open]');
      assert.equal(await page.textContent('#alarm-dialog-title'), 'Edit Alarm');
      assert.equal(await page.locator('#alarm-hour').inputValue(), '7');
      assert.equal(await page.locator('#alarm-ampm').inputValue(), 'AM');
      assert.equal(await page.textContent('#alarm-repeat-text'), 'Weekdays');
      await page.locator('#alarm-minute').selectOption('45');
      await page.locator('#alarm-save').click();
      await page.waitForFunction(() => document.getElementById('alarm-dialog').open === false);
      assert.ok(calls.includes('PATCH /planner/alarms/a1'));
      await page.locator('#alarm-list li').nth(1).locator('.alarm-open').click();
      await page.waitForSelector('#alarm-dialog[open]');
      await page.locator('#alarm-delete').click();
      await page.waitForFunction(() => document.querySelectorAll('#alarm-list li').length === 2);
      assert.ok(calls.includes('DELETE /planner/alarms/a1'));

      // list Edit mode shows a delete control on each row
      await page.locator('#alarm-edit').click();
      assert.equal(await page.locator('#alarm-list .alarm-remove').count(), 2);
      assert.equal(await page.textContent('#alarm-edit'), 'Done');
      await page.locator('#alarm-list .alarm-remove').first().click();
      await page.waitForFunction(() => document.querySelectorAll('#alarm-list li').length === 1);
      await page.locator('#alarm-edit').click();
      assert.equal(await page.locator('#alarm-list .alarm-remove').count(), 0);

      await page.locator('#alarm-stop').click();
      await page.waitForFunction(() => document.getElementById('alarm-status').textContent === 'Alarm stopped.');

      await page.locator('#alarm-search').fill('rock');
      await page.locator('#alarm-search-form button').click();
      await page.locator('#alarm-search-results li').waitFor();
      assert.equal(await page.locator('#alarm-search-results i').count(), 0);
      await page.locator('#alarm-search-results').getByText('Save', {exact: true}).click();
      await page.waitForFunction(() => document.querySelectorAll('#alarm-station-list li').length === 2);

      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
      assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
      assert.deepEqual(errors, []);
      await page.close();
      stations.length = 1; alarms.length = 2;
    }
  } finally {
    await browser.close();
    server.close();
  }
});
