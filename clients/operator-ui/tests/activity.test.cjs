// Real browser, fixture API: the Activity tab renders receipts literally.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('activity tab lists receipts with literal text and failure reasons', async () => {
  const receipts = [
    {id: 'r1', action_type: 'task.created', status: 'success', at: '2030-01-02T07:00:00Z', source_channel: 'web', fields: {Task: '<img src=x onerror=boom()>'}},
    {id: 'r2', action_type: 'alarm.delivered', status: 'failed', at: '2030-01-02T06:00:00Z', source_channel: 'system', fields: {}, failure_reason: 'failed: no audio'},
  ];
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://fixture');
    const route = url.pathname.replace(/^\/hub/, '');
    const json = body => { res.writeHead(200, {'Content-Type': 'application/json'}); res.end(JSON.stringify(body)); };
    if (route.startsWith('/ui/')) {
      const file = route.slice(4) || 'index.html';
      if (!/^[a-z_.-]+\.(html|js|css)$/.test(file)) { res.writeHead(404); return res.end(); }
      res.setHeader('Content-Type', file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html');
      return res.end(fs.readFileSync(path.join(__dirname, '..', file)));
    }
    if (route === '/auth/me') return json({username: 'owner'});
    if (route === '/status') return json({reachy_hub: {status: 'ok'}, companion_core: {status: 'ok'}, robots: [], owner_bound: true, default_user_id: 'owner', llm: {configured: true, usage: {data: null}}, telegram: {configured: false}});
    if (route === '/planner/receipts') return json(receipts);
    return json([]);
  });
  await new Promise(resolve => server.listen(0, resolve));
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    let injected = false;
    page.on('dialog', () => { injected = true; });
    await page.goto(`http://127.0.0.1:${server.address().port}/hub/ui/`);
    await page.click('#activity-tab');
    await page.waitForSelector('#activity-list li');
    const text = await page.locator('#activity-list').innerText();
    assert.match(text, /Task: <img src=x onerror=boom\(\)>/);
    assert.match(text, /failed: failed: no audio/);
    assert.equal(await page.locator('#activity-list img').count(), 0);
    assert.equal(injected, false);
  } finally { await browser.close(); server.close(); }
});
