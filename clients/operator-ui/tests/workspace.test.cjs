// Real browser, fixture API: navigation, persisted records and stale detail reads.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('dashboard, feature settings and saved chat/meeting workspaces at both mounts', async () => {
  const chats = [];
  let sends = 0, loggedIn = true, delayedMeeting;
  const meetings = [
    {id: 'one', title: '<script>Planning</script>', status: 'aligning', created_at: '2026-10-01T01:00:00Z', transcript_segments: [{start: 0, end: 2, text: '<img src=x> Notes'}]},
    {id: 'two', title: 'Design review', status: 'failed', created_at: '2026-10-01T02:00:00Z', error_detail: 'Fixture failure'},
  ];
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
    if (route === '/auth/me') return json({username: 'owner'}, loggedIn ? 200 : 401);
    if (route === '/auth/logout') {loggedIn = false; return json({});}
    if (route === '/status') return json({reachy_hub: {status: 'ok'}, companion_core: {status: 'ok'}, robots: [], owner_bound: true, default_user_id: 'owner', llm: {configured: true, usage: {data: null}}, telegram: {configured: false}});
    if (route.startsWith('/sessions/')) return json({interaction_mode: 'desk', active_channel: 'web', dnd: false});
    if (route === '/settings/llm') return json({local: null});
    if (route === '/settings/persona') return json({name: 'Reachy', system_prompt: 'Assistant'});
    if (route === '/settings/websearch') return json({policy: 'off'});
    if (route === '/websearch/log') return json({entries: []});
    if (route === '/robot-voice') return json({robots: [], session: null});
    if (route === '/chats') {
      if (req.method === 'POST') {
        assert.equal(req.headers['x-reachy-csrf'], '1');
        const record = {...body, id: String(chats.length + 1), turns: [], updated_at: new Date().toISOString()};
        chats.unshift(record); return json(record);
      }
      return json(chats.map(({turns, ...record}) => record));
    }
    if (route.startsWith('/chats/')) return json(chats.find(c => c.id === route.split('/').at(-1)));
    if (route === '/messages') {
      sends++;
      assert.equal(req.headers['x-reachy-csrf'], '1');
      chats.find(c => c.id === body.chat_id).turns.push({text: body.text, reply: '<b>Saved reply</b>', status: 'complete'});
      return json({reply: '<b>Saved reply</b>'});
    }
    if (route === '/meetings') return json(meetings);
    if (route === '/meetings/one') { delayedMeeting = () => json(meetings[0]); return; }
    if (route === '/meetings/two') return json(meetings[1]);
    if (route === '/meetings/two/cancel') return json({});
    return json([]);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']});
  try {
    for (const [mount, width] of [['/hub/ui/', 1440], ['/ui/', 390]]) {
      loggedIn = true; chats.length = 0;
      const page = await browser.newPage({viewport: {width, height: 950}});
      const errors = []; page.on('pageerror', e => errors.push(e.message));
      await page.goto(`http://127.0.0.1:${server.address().port}${mount}`);
      await page.locator('#dashboard').waitFor({state: 'visible'});
      assert.equal(await page.locator('#overview-pane form').count(), 0);
      assert.equal(await page.locator('#overview-pane #audit').count(), 1);
      await page.locator('#settings-tab').click();
      for (const feature of ['assistant', 'models', 'search', 'voice', 'accounts', 'recognition']) {
        await page.locator(`#settings-${feature}-tab`).click();
        assert.equal(await page.locator(`#settings-${feature}`).isVisible(), true);
        assert.equal(await page.locator('.settings-panel:visible').count(), 1);
      }
      await page.locator('#settings-recognition-tab').press('Home');
      assert.equal(await page.locator('#settings-assistant-tab').getAttribute('aria-selected'), 'true');
      await page.locator('#persona-name').fill('Draft name');
      await page.locator('#settings-models-tab').click();
      await page.locator('#settings-assistant-tab').click();
      assert.equal(await page.locator('#persona-name').inputValue(), 'Draft name');
      await page.locator('#chat-tab').click();
      await page.locator('#chat-text').fill('<script>First chat</script>');
      await page.locator('#chat-send').click();
      await page.waitForFunction(() => document.querySelectorAll('.from-reachy').length === 1);
      await page.locator('#new-chat').click();
      await page.locator('#chat-text').fill('Second chat');
      await page.locator('#chat-send').click();
      await page.waitForFunction(() => document.querySelectorAll('#chat-history .history-button').length === 2);
      const before = sends;
      await page.reload();
      await page.locator('#chat-tab').click();
      await page.waitForFunction(() => document.getElementById('chat-title').textContent === 'Second chat');
      assert.equal(await page.locator('.from-reachy').textContent(), 'Reachy<b>Saved reply</b>');
      await page.locator('#chat-history-search').fill('First');
      await page.locator('#chat-history .history-button').click();
      await page.waitForFunction(() => document.getElementById('chat-title').textContent.includes('First'));
      assert.equal(await page.locator('#chat-transcript script, #chat-transcript b').count(), 0);
      assert.equal(sends, before, 'reading history must not replay a message');
      assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
      await page.locator('#meetings-tab').click();
      await page.locator('#meeting-record-start').click();
      await page.locator('#meeting-record-stop').waitFor({state: 'visible'});
      await page.locator('#meeting-list .meeting-item').first().getByText('View details', {exact: true}).click();
      await page.locator('#meeting-list .meeting-item').nth(1).getByText('View details', {exact: true}).click();
      await page.waitForFunction(() => document.getElementById('meeting-detail-title').textContent === 'Design review');
      delayedMeeting();
      await page.waitForTimeout(80);
      assert.equal(await page.locator('#meeting-detail-title').textContent(), 'Design review');
      assert.equal(await page.locator('#meeting-detail-error').getAttribute('open'), null);
      assert.equal(await page.locator('#meeting-create').isVisible(), false);
      assert.equal(await page.locator('#meeting-list script').count(), 0);
      await page.locator('#meeting-new').click();
      assert.equal(await page.locator('#meeting-create').isVisible(), true);
      await page.locator('#meeting-record-discard').waitFor({state: 'visible'});
      assert.equal(await page.locator('#meeting-record-stop').isVisible(), false);
      await page.locator('#meeting-search').fill('Design');
      assert.equal(await page.locator('.meeting-item').count(), 1);
      if (width > 800) {
        const side = await page.locator('.meeting-workspace .record-sidebar').boundingBox();
        const main = await page.locator('.meeting-main').boundingBox();
        assert.ok(side.x + side.width <= main.x + 1);
      }
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.locator('#logout').click();
      await page.locator('#login-panel').waitFor({state: 'visible'});
      assert.equal(await page.locator('.chat-message').count(), 0);
      assert.equal(await page.locator('#chat-history .history-button').count(), 0);
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally {await browser.close(); await new Promise(resolve => server.close(resolve));}
});
