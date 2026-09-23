// Browser regression with a local HTTP fixture. A separately installed Playwright
// is sufficient (NODE_PATH can point at its node_modules); no frontend build.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('web chat handles identities, replies, failures, login expiry, and fresh tabs', async () => {
  let loggedIn = true;
  let telegramHealthy = false;
  let delayReply = false;
  let failReply = false;
  let pendingReply;
  async function waitForPendingReply() {
    const deadline = Date.now() + 10000;
    while (!pendingReply && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
    assert.ok(pendingReply, 'expected a pending chat POST');
  }
  const messages = [];
  const sessions = new Map();
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://fixture');
    if (!url.pathname.startsWith('/hub/')) url.pathname = '/hub' + url.pathname;
    const json = (status, body) => { res.writeHead(status, {'Content-Type': 'application/json'}); res.end(JSON.stringify(body)); };
    if (url.pathname.startsWith('/hub/ui/')) {
      const name = url.pathname.substring('/hub/ui/'.length) || 'index.html';
      if (!['index.html', 'app.js', 'chat.js', 'accounts.js', 'style.css'].includes(name)) return json(404, {});
      res.writeHead(200, {'Content-Type': name.endsWith('.js') ? 'application/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      return res.end(fs.readFileSync(path.join(__dirname, '..', name)));
    }
    if (url.pathname === '/hub/auth/me') return json(loggedIn ? 200 : 401, loggedIn ? {username: 'owner'} : {detail: 'Login required'});
    if (url.pathname === '/hub/auth/login') { loggedIn = true; return json(200, {username: 'owner'}); }
    if (url.pathname === '/hub/auth/logout') { loggedIn = false; return json(200, {ok: true}); }
    if (url.pathname === '/hub/status') return json(200, {
      reachy_hub: {status: 'ok'}, companion_core: {status: 'ok'}, robots: [],
      default_user_id: 'telegram-owner', llm: {configured: false, usage: {data: {summary: {calls: 0, errors: 0, prompt_tokens: 0, completion_tokens: 0, avg_latency_ms: 0}, entries: []}}},
      telegram: {configured: true, healthy: telegramHealthy, last_poll_at: new Date().toISOString(), last_poll_error: telegramHealthy ? null : 'Telegram polling returned HTTP 401'},
    });
    if (url.pathname === '/hub/settings/llm') return json(200, {local: null});
    if (url.pathname.startsWith('/hub/sessions/')) {
      const user = decodeURIComponent(url.pathname.split('/').at(-1));
      return json(sessions.has(user) ? 200 : 404, sessions.get(user) || {detail: 'No session'});
    }
    if (url.pathname === '/hub/messages') {
      const chunks = []; for await (const chunk of req) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks)); messages.push(body);
      sessions.set(body.user_id, {interaction_mode: 'office', dnd: true, active_channel: 'web'});
      const respond = () => failReply ? json(502, {detail: 'Core unavailable'}) : json(200, {reply: '<img src=x onerror="window.injection=true">\nA plain-text reply', delivery_channel: 'phone'});
      if (delayReply) { pendingReply = respond; return; }
      return respond();
    }
    return json(200, []);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/hub/ui/`);
    await page.locator('#chat-tab').click();
    await page.waitForFunction(() => document.getElementById('chat-user').value === 'telegram-owner');
    assert.match(await page.locator('#chat-session').textContent(), /No session yet/);
    assert.match(await page.locator('#chat-telegram').textContent(), /HTTP 401/);
    await page.locator('#chat-text').fill('   ');
    await page.locator('#chat-send').click();
    assert.equal(messages.length, 0);

    delayReply = true;
    await page.locator('#chat-text').fill('<script>alert(1)</script>');
    await page.locator('#chat-text').press('Enter');
    await page.waitForFunction(() => document.getElementById('chat-send').disabled);
    await page.waitForFunction(() => document.querySelectorAll('.from-user').length === 1);
    assert.equal(await page.locator('#chat-user').isDisabled(), true);
    await page.locator('#chat-text').press('Enter');
    // Wait for the actual POST fixture; UI may render before fetch reaches us.
    await waitForPendingReply();
    assert.equal(messages.length, 1);
    assert.deepEqual(messages[0], {user_id: 'telegram-owner', channel: 'web', text: '<script>alert(1)</script>', input_modality: 'text'});
    pendingReply(); delayReply = false;
    await page.waitForFunction(() => document.querySelectorAll('.from-reachy').length === 1);
    assert.equal(await page.locator('#chat-transcript script, #chat-transcript img').count(), 0);
    assert.match(await page.locator('#chat-session').textContent(), /office.*DND: on.*web/);

    await page.locator('#force-frontier').check();
    failReply = true;
    await page.locator('#chat-text').fill('Failed turn'); await page.locator('#chat-send').click();
    await page.waitForFunction(() => document.getElementById('chat-status').textContent.includes('may have been processed'));
    assert.equal(messages.length, 2);
    assert.equal(messages[1].force_frontier, true);
    assert.equal(await page.locator('#force-frontier').isChecked(), false);
    assert.equal(await page.locator('#chat-text').inputValue(), 'Failed turn');
    assert.equal(await page.locator('.from-reachy').count(), 1);
    failReply = false;
    telegramHealthy = true;
    await page.evaluate(() => refresh());
    assert.match(await page.locator('#chat-telegram').textContent(), /polling is healthy/);

    await page.locator('#chat-user').fill('different-user');
    assert.equal(await page.locator('#chat-send').isDisabled(), true);
    await page.locator('#chat-use-user').click();
    assert.equal(await page.locator('.chat-message').count(), 0);
    assert.equal(await page.locator('#user-id').inputValue(), 'different-user');
    await page.locator('#chat-text').fill('First line');
    await page.locator('#chat-text').press('Shift+Enter');
    assert.equal(await page.locator('#chat-text').inputValue(), 'First line\n');
    await page.locator('#chat-send').click();
    await page.waitForFunction(() => document.querySelectorAll('.from-reachy').length === 1);
    assert.equal(messages.at(-1).user_id, 'different-user');
    assert.equal(messages.at(-1).force_frontier, undefined);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.locator('#clear-chat').click();
    assert.equal(await page.locator('.chat-message').count(), 0);
    assert.equal(sessions.size, 2);

    // A cookie expiring between poll ticks must prevent this UI from using the
    // intentionally still-open /messages endpoint without an owner check.
    loggedIn = false;
    await page.locator('#chat-text').fill('Must not send'); await page.locator('#chat-send').click();
    await page.locator('#login-panel').waitFor({state: 'visible'});
    assert.equal(messages.length, 3);
    assert.equal(await page.locator('#chat-text').inputValue(), '');
    loggedIn = true;
    await page.reload(); await page.locator('#chat-tab').click();
    assert.equal(await page.locator('.chat-message').count(), 0);
    assert.deepEqual(await page.evaluate(() => Object.keys(localStorage)), []);
    // Direct hub mount must work as well as the /hub reverse-proxy prefix.
    await page.goto(`http://127.0.0.1:${server.address().port}/ui/`);
    await page.locator('#chat-tab').click();
    await page.waitForFunction(() => !document.getElementById('chat-send').disabled);
    delayReply = true; pendingReply = null;
    await page.locator('#chat-text').fill('Reply arriving after logout');
    await page.locator('#chat-send').click();
    await waitForPendingReply();
    await page.locator('#logout').click();
    await page.locator('#login-panel').waitFor({state: 'visible'});
    pendingReply(); delayReply = false;
    await page.locator('#username').fill('owner');
    await page.locator('#password').fill('fixture-password');
    await page.locator('#login button').click();
    await page.locator('#chat-tab').click();
    assert.equal(await page.locator('.chat-message').count(), 0);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
});
