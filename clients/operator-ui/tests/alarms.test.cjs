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
    {id: 'a1', label: '<img src=x onerror=boom()> wake', due_at: '2030-01-02T07:00:00Z', station_id: 's1', status: 'scheduled', delivery: null},
    {id: 'a2', label: 'old', due_at: '2020-01-02T07:00:00Z', station_id: null, status: 'fired', delivery: 'telegram: privacy mode'},
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
    if (route === '/planner/alarms' && req.method === 'POST') { alarms.push({id: 'a3', status: 'scheduled', delivery: null, ...body}); return json(alarms.at(-1)); }
    if (route === '/planner/alarms/stop') return json({stopped: true});
    if (route === '/planner/alarms/a1' && req.method === 'DELETE') { alarms[0].status = 'cancelled'; return json(alarms[0]); }
    if (route === '/planner/stations' && req.method === 'GET') return json(stations);
    if (route === '/planner/stations' && req.method === 'POST') { stations.push({id: 's2', ...body}); return json(stations.at(-1)); }
    if (route === '/planner/stations/search') return json([{guide_id: 's222', name: '<i>Rock</i>', detail: 'hits'}]);
    return json([]);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    for (const [mount, width] of [['/hub/ui/', 1440], ['/ui/', 390]]) {
      calls.length = 0; alarms[0].status = 'scheduled';
      const page = await browser.newPage({viewport: {width, height: 950}});
      const errors = []; page.on('pageerror', e => errors.push(e.message));
      await page.goto(`http://127.0.0.1:${server.address().port}${mount}`);
      await page.locator('#alarms-tab').click();
      await page.waitForFunction(() => document.querySelectorAll('#alarm-list li').length === 2);
      assert.equal(await page.locator('#alarm-list img, #alarm-station-list b').count(), 0);
      assert.match(await page.locator('#alarm-list li').first().textContent(), /<img src=x onerror=boom\(\)> wake/);
      assert.match(await page.locator('#alarm-list li').first().textContent(), /<b>Jazz FM<\/b>/);
      assert.match(await page.locator('#alarm-list li').nth(1).textContent(), /telegram: privacy mode/);
      assert.equal(await page.locator('#alarm-station option').count(), 2);

      await page.locator('#alarm-label').fill('cake');
      await page.locator('#alarm-due').fill('2030-03-04T14:00');
      await page.locator('#alarm-station').selectOption('s1');
      await page.locator('#alarm-volume').evaluate(input => { input.value = '250'; input.dispatchEvent(new Event('input', {bubbles: true})); });
      assert.equal(await page.locator('#alarm-volume-value').textContent(), '250%');
      await page.locator('#alarm-form button').click();
      await page.waitForFunction(() => document.querySelectorAll('#alarm-list li').length === 3);
      assert.ok(calls.includes('POST /planner/alarms'));
      assert.equal(alarms.at(-1).volume, 250);

      await page.locator('#alarm-list li').first().getByText('Cancel', {exact: true}).click();
      await page.waitForFunction(() => !document.querySelector('#alarm-list li button') || document.querySelectorAll('#alarm-list li button').length === 1);
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
