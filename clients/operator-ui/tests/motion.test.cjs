// Real Chromium against a local HTTP fixture; no physical robot motion.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('animation settings load, apply, reject stale active sessions and reset on logout', async () => {
  let settings = {conversation_motion: false, speech_wobble: true, conversation_active: false};
  let fail = false;
  let robots = [{robot_id: 'nano', base_url: 'http://robot'}];
  const writes = [];
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://fixture');
    const route = url.pathname.replace(/^\/hub/, '');
    const json = (status, body) => { res.writeHead(status, {'Content-Type': 'application/json'}); res.end(JSON.stringify(body)); };
    if (route.startsWith('/ui/')) {
      const name = route.slice(4) || 'index.html';
      if (!['index.html', 'app.js', 'chat.js', 'voice.js', 'accounts.js', 'style.css'].includes(name)) return json(404, {});
      res.writeHead(200, {'Content-Type': name.endsWith('.js') ? 'application/javascript' : name.endsWith('.css') ? 'text/css' : 'text/html'});
      return res.end(fs.readFileSync(path.join(__dirname, '..', name)));
    }
    if (route === '/auth/me') return json(200, {username: 'owner'});
    if (route === '/auth/logout') return json(200, {});
    if (route === '/status') return json(200, {reachy_hub: {status: 'ok'}, companion_core: {status: 'ok'}, robots: [], default_user_id: 'owner', llm: {configured: false, usage: {data: null}}, telegram: {configured: false}});
    if (route === '/robot-voice') return json(200, {robots: [], session: null});
    if (route === '/robots') return json(200, robots);
    if (route === '/robots/nano/settings/motion') {
      if (req.method === 'PUT') {
        const chunks = []; for await (const chunk of req) chunks.push(chunk);
        const body = JSON.parse(Buffer.concat(chunks));
        writes.push(body);
        assert.equal(req.headers['x-reachy-csrf'], '1');
        if (settings.conversation_active) return json(409, {detail: 'Stop the robot conversation before changing animations'});
        settings = {...settings, ...body};
      }
      return fail ? json(502, {detail: 'Robot unavailable'}) : json(200, settings);
    }
    return json(404, {detail: 'Unavailable in fixture'});
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    for (const mount of ['/hub/ui/', '/ui/']) {
      await page.goto(`http://127.0.0.1:${server.address().port}${mount}`);
      await page.locator('#accounts-tab').click();
      await page.waitForFunction(() => !document.getElementById('motion-fields').disabled);
      assert.equal(await page.locator('#motion-wobble').isChecked(), settings.speech_wobble);
      await page.locator('#motion-gestures').check();
      await page.locator('#motion-wobble').uncheck();
      await page.locator('#motion-form button').click();
      await page.waitForFunction(() => document.getElementById('motion-status').textContent.includes('applied'));
      assert.deepEqual(writes.at(-1), {conversation_motion: true, speech_wobble: false});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    // A conversation starts after GET; the server must still reject PUT.
    settings.conversation_active = true;
    await page.locator('#motion-gestures').uncheck();
    await page.locator('#motion-form button').click();
    await page.waitForFunction(() => document.getElementById('motion-status').textContent.includes('Refresh to check'));
    assert.equal(settings.conversation_motion, true);
    assert.equal(await page.locator('#motion-gestures').isDisabled(), true);
    await page.locator('#motion-refresh').click();
    await page.waitForFunction(() => document.getElementById('motion-status').textContent.includes('Stop listening'));
    assert.equal(await page.locator('#motion-gestures').isDisabled(), true);
    settings.conversation_active = false; fail = true;
    await page.locator('#motion-refresh').click();
    await page.waitForFunction(() => document.getElementById('motion-status').textContent.includes('unavailable'));
    assert.equal(await page.locator('#motion-gestures').isDisabled(), true);
    fail = false; robots = [];
    await page.locator('#motion-refresh').click();
    await page.waitForFunction(() => document.getElementById('motion-status').textContent === 'No robots registered.');
    await page.locator('#logout').click();
    await page.locator('#login-panel').waitFor({state: 'visible'});
    assert.equal(await page.locator('#motion-robot option').count(), 0);
    assert.deepEqual(await page.evaluate(() => Object.keys(localStorage)), []);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
});
