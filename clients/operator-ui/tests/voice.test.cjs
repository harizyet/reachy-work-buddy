// Phase 24c browser regression: robot microphone controls against a local
// HTTP fixture (no hub, no robot). Checks start/renew/stop wiring, CSRF,
// proxied-mount paths, literal rendering of spoken/withheld turns, and that
// polling ends on stop and logout.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('robot microphone controls start, show turns literally, and stop', async () => {
  let loggedIn = true;
  let capable = true;
  let session = null;
  const calls = [];
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://fixture');
    const json = (status, body) => { res.writeHead(status, {'Content-Type': 'application/json'}); res.end(JSON.stringify(body)); };
    if (url.pathname.startsWith('/hub/ui/')) {
      const name = url.pathname.substring('/hub/ui/'.length) || 'index.html';
      if (!['index.html', 'app.js', 'chat.js', 'voice.js', 'accounts.js', 'style.css'].includes(name)) return json(404, {});
      res.writeHead(200, {'Content-Type': name.endsWith('.js') ? 'application/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      return res.end(fs.readFileSync(path.join(__dirname, '..', name)));
    }
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    const body = chunks.length ? JSON.parse(Buffer.concat(chunks)) : null;
    if (url.pathname.startsWith('/hub/robot-voice')) calls.push({path: url.pathname, csrf: req.headers['x-reachy-csrf'], body});
    if (url.pathname === '/hub/auth/me') return json(loggedIn ? 200 : 401, loggedIn ? {username: 'owner'} : {detail: 'Login required'});
    if (url.pathname === '/hub/auth/logout') { loggedIn = false; return json(200, {ok: true}); }
    if (url.pathname === '/hub/status') return json(200, {
      reachy_hub: {status: 'ok'}, companion_core: {status: 'ok'}, robots: [], default_user_id: 'owner-user', owner_bound: true,
      llm: {configured: false, usage: {data: {summary: {calls: 0, errors: 0, prompt_tokens: 0, completion_tokens: 0, avg_latency_ms: 0}, entries: []}}},
      telegram: {configured: false, healthy: false},
    });
    if (url.pathname === '/hub/robot-voice') return json(200, {
      robots: [{robot_id: 'nano-1', online: true, voice_capable: capable}], session,
    });
    if (url.pathname === '/hub/robot-voice/start') {
      session = {voice_session_id: 'vs-1', robot_id: body.robot_id, user_id: body.user_id, state: 'listening',
        stop_reason: null, last_error: null, next_turn: 1, lease_seconds_remaining: 15, session_seconds_remaining: 600, turns: []};
      return json(200, session);
    }
    if (url.pathname === '/hub/robot-voice/renew') return json(200, session);
    if (url.pathname === '/hub/robot-voice/stop') {
      session = {...session, state: 'stopped', stop_reason: 'Stopped by owner'};
      return json(200, session);
    }
    if (url.pathname.startsWith('/hub/sessions/')) return json(200, {interaction_mode: 'desk', dnd: false, active_channel: 'reachy'});
    if (url.pathname === '/hub/settings/llm') return json(200, {local: null});
    return json(200, {});
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/hub/ui/`);
    await page.locator('#chat-tab').click();
    await page.waitForFunction(() => !document.getElementById('voice-start').disabled);
    assert.match(await page.locator('#voice-panel').textContent(), /does not recognise who is speaking/);
    assert.equal(await page.locator('#voice-state').textContent(), 'Off');

    await page.locator('#voice-start').click();
    await page.waitForFunction(() => document.getElementById('voice-state').textContent.startsWith('Listening'));
    const start = calls.find(call => call.path === '/hub/robot-voice/start');
    assert.deepEqual(start.body, {robot_id: 'nano-1', user_id: 'owner-user'});
    assert.equal(start.csrf, '1');
    assert.equal(await page.locator('#voice-start').isDisabled(), true);
    assert.equal(await page.locator('#voice-robot').isDisabled(), true);

    // The lease is renewed while the tab is open.
    await page.waitForFunction(() => true, null, {timeout: 100});
    const deadline = Date.now() + 5000;
    while (!calls.some(call => call.path === '/hub/robot-voice/renew') && Date.now() < deadline) await new Promise(r => setTimeout(r, 50));
    assert.ok(calls.some(call => call.path === '/hub/robot-voice/renew' && call.csrf === '1'));

    session = {...session, state: 'speaking', turns: [
      {turn: 1, transcript: 'hello <b>there</b>', reply: '<img src=x onerror="window.injected=true">hi', outcome: 'spoken', reason: null},
      {turn: 2, transcript: "what's on my calendar", reply: 'Standup at 10', outcome: 'withheld', reason: 'Routing sends this reply to web, not the robot speaker'},
    ]};
    await page.waitForFunction(() => document.querySelectorAll('.chat-message').length === 4);
    const messages = await page.locator('.chat-message').allTextContents();
    assert.match(messages[0], /spoken to Reachy.*hello <b>there<\/b>/s);
    assert.match(messages[1], /said aloud.*<img src=x/s);
    assert.match(messages[3], /not spoken \(Routing sends this reply to web.*Standup at 10/s);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    assert.equal(await page.locator('#voice-state').textContent(), 'Speaking');

    await page.locator('#voice-stop').click();
    await page.waitForFunction(() => document.getElementById('voice-state').textContent === 'Off');
    assert.match(await page.locator('#voice-detail').textContent(), /Stopped: Stopped by owner/);
    const renewsAfterStop = calls.filter(call => call.path === '/hub/robot-voice/renew').length;
    await new Promise(r => setTimeout(r, 2000));
    assert.equal(calls.filter(call => call.path === '/hub/robot-voice/renew').length, renewsAfterStop);

    // A robot that hasn't opted in cannot be started.
    capable = false;
    await page.evaluate(() => document.getElementById('overview-tab').click());
    await page.locator('#chat-tab').click();
    await page.waitForFunction(() => document.getElementById('voice-robot').textContent.includes('voice not enabled'), null, {timeout: 15000});
    assert.equal(await page.locator('#voice-start').isDisabled(), true);

    // Logout resets the panel and stops any polling.
    capable = true; session = null;
    await page.waitForFunction(() => !document.getElementById('voice-start').disabled, null, {timeout: 15000});
    await page.locator('#voice-start').click();
    await page.waitForFunction(() => document.getElementById('voice-state').textContent.startsWith('Listening'));
    await page.locator('#logout').click();
    await page.waitForFunction(() => !document.getElementById('login-panel').hidden);
    const renewsAfterLogout = calls.filter(call => call.path === '/hub/robot-voice/renew').length;
    await new Promise(r => setTimeout(r, 2000));
    assert.equal(calls.filter(call => call.path === '/hub/robot-voice/renew').length, renewsAfterLogout);
    assert.equal(await page.locator('#voice-state').textContent(), 'Off');
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    server.close();
  }
});
