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
  let webSearch = null;
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
      if (!['index.html', 'app.js', 'chat.js', 'voice.js', 'accounts.js', 'style.css'].includes(name)) return json(404, {});
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
      const respond = () => failReply ? json(502, {detail: 'Core unavailable'}) : json(200, {reply: '<img src=x onerror="window.injection=true">\nA plain-text reply', delivery_channel: 'phone', web_search: webSearch});
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

    assert.equal(await page.locator('.chat-search').count(), 0);
    webSearch = {query: '<script>query</script>', failed: false, results: [
      {title: '<img src=x onerror="window.injection=true">', url: 'https://example.com/source', snippet: '<script>snippet</script>', source_domain: 'example.com'},
      {title: 'Unsafe URL', url: 'javascript:alert(1)', snippet: 'Plain text only', source_domain: 'invalid'},
    ]};
    await page.locator('#chat-text').fill('Latest news');
    await page.locator('#chat-send').click();
    const details = page.locator('.chat-search');
    await details.waitFor();
    assert.equal(await details.getAttribute('open'), null);
    await details.locator('summary').focus();
    await page.keyboard.press('Enter');
    assert.equal(await details.locator('li').count(), 2);
    assert.equal(await details.locator('a').count(), 1);
    assert.equal(await details.locator('a').getAttribute('href'), 'https://example.com/source');
    assert.equal(await details.locator('a').getAttribute('rel'), 'noopener noreferrer');
    assert.equal(await details.locator('img, script').count(), 0);
    assert.match(await details.textContent(), /<script>snippet<\/script>/);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await details.locator('summary').click();
    assert.equal(await details.getAttribute('open'), null);
    // Voice replies use the same evidence presentation, including empty/failure states.
    await page.evaluate(() => {
      chat.appendVoiceTurn({outcome: 'spoken', reply: 'No sources', web_search: {query: 'empty', failed: false, results: []}});
      chat.appendVoiceTurn({outcome: 'withheld', reply: 'Unavailable', web_search: {query: 'failed', failed: true, results: []}});
    });
    await page.locator('.chat-search').nth(1).locator('summary').click();
    assert.match(await page.locator('.chat-search').nth(1).textContent(), /No results were found/);
    await page.locator('.chat-search').nth(2).locator('summary').click();
    assert.match(await page.locator('.chat-search').nth(2).textContent(), /The search failed/);
    // Restore the original fixture transcript/counts for the lifecycle checks below.
    await page.evaluate(() => [...document.querySelectorAll('.chat-message')].slice(2).forEach(item => item.remove()));
    messages.pop();
    webSearch = null;

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

test('web chat renders command autocomplete and dispatches suggested-command buttons', async () => {
  const messages = [];
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://fixture');
    if (!url.pathname.startsWith('/hub/')) url.pathname = '/hub' + url.pathname;
    const json = (status, body) => { res.writeHead(status, {'Content-Type': 'application/json'}); res.end(JSON.stringify(body)); };
    if (url.pathname.startsWith('/hub/ui/')) {
      const name = url.pathname.substring('/hub/ui/'.length) || 'index.html';
      if (!['index.html', 'app.js', 'chat.js', 'voice.js', 'accounts.js', 'style.css'].includes(name)) return json(404, {});
      res.writeHead(200, {'Content-Type': name.endsWith('.js') ? 'application/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      return res.end(fs.readFileSync(path.join(__dirname, '..', name)));
    }
    if (url.pathname === '/hub/auth/me') return json(200, {username: 'owner'});
    if (url.pathname === '/hub/status') return json(200, {
      reachy_hub: {status: 'ok'}, companion_core: {status: 'ok'}, robots: [],
      default_user_id: 'telegram-owner', llm: {configured: false, usage: {data: {summary: {calls: 0, errors: 0, prompt_tokens: 0, completion_tokens: 0, avg_latency_ms: 0}, entries: []}}},
      telegram: {configured: false, healthy: false},
    });
    if (url.pathname === '/hub/settings/llm') return json(200, {local: null});
    if (url.pathname.startsWith('/hub/sessions/')) return json(404, {detail: 'No session'});
    if (url.pathname === '/hub/messages') {
      const chunks = []; for await (const chunk of req) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks)); messages.push(body);
      return json(200, {reply: body.text === '/reachy standby'
        ? 'Reachy is now in standby — safe to move or put away.'
        : 'It sounds like you want to put Reachy into standby. Use /reachy standby.', delivery_channel: 'phone'});
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
    await page.waitForFunction(() => !document.getElementById('chat-send').disabled);

    await page.locator('#chat-text').fill('/reachy sta');
    await page.waitForFunction(() => !document.getElementById('chat-command-hints').hidden);
    assert.match(await page.locator('#chat-command-hints').textContent(), /\/reachy standby/);
    await page.locator('#chat-command-hints button').first().click();
    assert.equal(await page.locator('#chat-text').inputValue(), '/reachy standby');

    await page.locator('#chat-send').click();
    await page.waitForFunction(() => document.querySelectorAll('.from-reachy').length === 1);
    assert.equal(messages.at(-1).text, '/reachy standby');
    assert.equal(await page.locator('.chat-command-suggestion').count(), 0);

    await page.locator('#chat-text').fill('Could you put Reachy to sleep?');
    await page.locator('#chat-send').click();
    await page.waitForFunction(() => document.querySelectorAll('.from-reachy').length === 2);
    await page.locator('.chat-command-suggestion').click();
    await page.waitForFunction(() => document.querySelectorAll('.from-reachy').length === 3);
    assert.equal(messages.at(-1).text, '/reachy standby');
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
});
