// Real browser, fixture API: deleting saved chats from the history sidebar. Titles are hostile on purpose and render literally.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('chat history: delete asks first, removes the chat, and clears the view when the open chat goes', async () => {
  const now = Date.now();
  let chats = [
    {id: 'c1', title: '<img src=x onerror=boom()> newest', user_id: 'owner', updated_at: new Date(now).toISOString(), turns: [{id: 't1', text: 'hello', reply: 'hi there', status: 'complete'}]},
    {id: 'c2', title: 'Older chat', user_id: 'owner', updated_at: new Date(now - 86400000).toISOString(), turns: []},
  ];
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
    if (req.method !== 'GET') assert.equal(req.headers['x-reachy-csrf'], '1');
    if (route === '/auth/me') return json({username: 'owner'});
    if (route === '/status') return json({reachy_hub: {status: 'ok'}, companion_core: {status: 'ok'}, robots: [], owner_bound: true, default_user_id: 'owner', llm: {configured: true, usage: {data: null}}, telegram: {configured: false}});
    if (route.startsWith('/sessions/')) return json({interaction_mode: 'desk', active_channel: 'web', dnd: false});
    if (route === '/chats') return json(chats.map(({turns, ...record}) => record));
    const m = route.match(/^\/chats\/(c\d)$/);
    if (m && req.method === 'GET') return json(chats.find(c => c.id === m[1]));
    if (m && req.method === 'DELETE') { calls.push(`delete:${m[1]}:${url.searchParams.get('user_id')}`); chats = chats.filter(c => c.id !== m[1]); return json({deleted: true}); }
    return json([]);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    for (const [mount, width] of [['/hub/ui/', 1440], ['/ui/', 390]]) {
      chats = chats.length === 2 ? chats : [
        {id: 'c1', title: '<img src=x onerror=boom()> newest', user_id: 'owner', updated_at: new Date(now).toISOString(), turns: [{id: 't1', text: 'hello', reply: 'hi there', status: 'complete'}]},
        {id: 'c2', title: 'Older chat', user_id: 'owner', updated_at: new Date(now - 86400000).toISOString(), turns: []},
      ];
      calls.length = 0;
      const page = await browser.newPage({viewport: {width, height: 950}});
      const errors = []; page.on('pageerror', e => errors.push(e.message));
      await page.goto(`http://127.0.0.1:${server.address().port}${mount}`);
      await page.locator('#chat-tab').click();
      await page.waitForFunction(() => document.querySelectorAll('#chat-history li.history-item').length === 2);
      assert.equal(await page.locator('#chat-history img').count(), 0);
      await page.waitForFunction(() => document.getElementById('chat-title').textContent.includes('newest'));  // the newest chat opens by itself

      // cancelling keeps the chat
      await page.locator('#chat-history li').first().hover();
      await page.locator('#chat-history .history-delete').first().click();
      await page.waitForSelector('#confirm-dialog[open]');
      assert.match(await page.textContent('#confirm-text'), /<img src=x onerror=boom\(\)> newest/);
      await page.click('#confirm-cancel');
      assert.equal(calls.length, 0);
      assert.equal(await page.locator('#chat-history li.history-item').count(), 2);

      // deleting the open chat removes it and empties the view
      await page.locator('#chat-history .history-delete').first().click();
      await page.waitForSelector('#confirm-dialog[open]');
      await page.click('#confirm-ok');
      await page.waitForFunction(() => document.querySelectorAll('#chat-history li.history-item').length === 1);
      assert.deepEqual(calls, ['delete:c1:owner']);
      assert.equal(await page.textContent('#chat-title'), 'Chat with Reachy');
      assert.equal(await page.locator('#chat-transcript').textContent().then(t => t.includes('hi there')), false);
      assert.equal(await page.locator('#chat-history li.history-item').textContent().then(t => t.includes('Older chat')), true);

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
