// Browser regression for the "Web search" settings card (Phase 24a),
// exercised for the first time in this session — same fixture-server
// pattern as chat.test.cjs, no mocks of the operator UI's own code.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('web search settings card configures built-in and external SearXNG with zero-config default', async () => {
  let searchConfig = {policy: 'off', provider: 'builtin_searxng', base_url: null, api_key: null, result_count: 5};
  const puts = [];
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
      default_user_id: 'owner', llm: {configured: false, usage: {data: null}},
      telegram: {configured: false, healthy: false},
    });
    if (url.pathname === '/hub/settings/llm') return json(200, {local: null});
    if (url.pathname === '/hub/settings/persona') return json(200, {name: 'Reachy', system_prompt: ''});
    if (url.pathname.startsWith('/hub/sessions/')) return json(404, {detail: 'No session'});
    if (url.pathname === '/hub/settings/websearch') {
      if (req.method === 'GET') return json(200, searchConfig);
      const chunks = []; for await (const chunk of req) chunks.push(chunk);
      const patch = JSON.parse(Buffer.concat(chunks)); puts.push(patch);
      searchConfig = {...searchConfig, ...patch};
      return json(200, searchConfig);
    }
    return json(200, []);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/hub/ui/`);
    await page.waitForFunction(() => !document.getElementById('websearch-fields').disabled);

    // Zero-config default: Built-in SearXNG, no base URL/API key fields shown.
    assert.equal(await page.locator('#websearch-provider').inputValue(), 'builtin_searxng');
    assert.equal(await page.locator('#websearch-external-fields').isHidden(), true);

    await page.locator('#websearch-policy').selectOption('auto');
    await Promise.all([
      page.waitForResponse(r => r.url().includes('/settings/websearch') && r.request().method() === 'PUT'),
      page.locator('#websearch').locator('button', {hasText: 'Save web search'}).click(),
    ]);
    assert.equal(puts.at(-1).provider, 'builtin_searxng');
    assert.equal(puts.at(-1).base_url, null);

    // Switching to External SearXNG reveals the base URL/API key fields.
    await page.locator('#websearch-provider').selectOption('searxng');
    assert.equal(await page.locator('#websearch-external-fields').isHidden(), false);
    await page.locator('#websearch-base-url').fill('http://searxng-host:8080');
    await Promise.all([
      page.waitForResponse(r => r.url().includes('/settings/websearch') && r.request().method() === 'PUT'),
      page.locator('#websearch').locator('button', {hasText: 'Save web search'}).click(),
    ]);
    assert.equal(puts.at(-1).provider, 'searxng');
    assert.equal(puts.at(-1).base_url, 'http://searxng-host:8080');
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
});
