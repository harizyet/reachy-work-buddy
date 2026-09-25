// Browser regression for the "Web search" settings card (Phase 24a),
// exercised for the first time in this session — same fixture-server
// pattern as chat.test.cjs, no mocks of the operator UI's own code.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('web search settings card configures hosted rotation and the SearXNG fallback', async () => {
  const hostedDefault = {enabled: false, api_key: null, monthly_limit: 900};
  let searchConfig = {
    policy: 'off', fallback: 'builtin_searxng', base_url: null, api_key: null, result_count: 5,
    hosted: {brave: {...hostedDefault}, exa: {...hostedDefault}, tavily: {...hostedDefault}},
    usage: {period: '2026-09', used: {brave: 12, exa: 0, tavily: 3}},
  };
  const puts = [];
  const personaPuts = [];
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
    if (url.pathname === '/hub/settings/persona') {
      if (req.method === 'PUT') {
        const chunks = []; for await (const chunk of req) chunks.push(chunk);
        personaPuts.push(JSON.parse(Buffer.concat(chunks)));
        return json(200, {name: 'Reachy', system_prompt: 'p', ...personaPuts.at(-1)});
      }
      return json(200, {name: 'Reachy', system_prompt: 'p', location: null, timezone: 'UTC'});
    }
    if (url.pathname.startsWith('/hub/sessions/')) return json(404, {detail: 'No session'});
    if (url.pathname === '/hub/websearch/log') return json(200, {
      usage: {period: '2026-09', used: {brave: 12, exa: 0, tavily: 3},
        limits: {brave: 900, exa: 900, tavily: 500}, enabled: {brave: true, exa: false, tavily: true}},
      entries: [{
        at: '2026-09-25T01:00:00+00:00', query: 'latest <b>python</b>', policy: 'auto', served_by: 'exa', total_ms: 812,
        attempts: [{provider: 'brave', outcome: 'error', ms: 400}, {provider: 'exa', outcome: 'ok', ms: 412}],
        results: [
          {title: '<img src=x onerror=alert(1)>', url: 'javascript:alert(1)', snippet: 'hostile', source_domain: 'evil.example'},
          {title: 'Python 3.14', url: 'https://python.org/', snippet: 'Released.', source_domain: 'python.org'},
        ],
      }],
    });
    if (url.pathname === '/hub/settings/websearch') {
      if (req.method === 'GET') return json(200, searchConfig);
      const chunks = []; for await (const chunk of req) chunks.push(chunk);
      const patch = JSON.parse(Buffer.concat(chunks)); puts.push(patch);
      const hosted = {...searchConfig.hosted};
      for (const [name, change] of Object.entries(patch.hosted || {})) {
        hosted[name] = {...hosted[name], ...change};
        if (hosted[name].api_key) hosted[name].api_key = '********' + hosted[name].api_key.slice(-4);
      }
      searchConfig = {...searchConfig, ...patch, hosted};
      return json(200, searchConfig);
    }
    return json(200, []);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}, timezoneId: 'Asia/Singapore'});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}/hub/ui/`);
    await page.waitForFunction(() => !document.getElementById('websearch-fields').disabled);

    const save = () => Promise.all([
      page.waitForResponse(r => r.url().includes('/settings/websearch') && r.request().method() === 'PUT'),
      page.locator('#websearch').locator('button', {hasText: 'Save web search'}).click(),
    ]);

    // Zero-config default: Built-in SearXNG fallback, no base URL/API key
    // fields, no hosted provider enabled, and this month's usage shown.
    assert.equal(await page.locator('#websearch-fallback').inputValue(), 'builtin_searxng');
    assert.equal(await page.locator('#websearch-base-url-field').isHidden(), true);
    assert.equal(await page.locator('#websearch-key-fields').isHidden(), true);
    assert.equal(await page.locator('#websearch-brave-enabled').isChecked(), false);
    assert.equal(await page.locator('#websearch-brave-usage').textContent(), 'Used 12 of 900 in 2026-09 (UTC)');

    await page.locator('#websearch-policy').selectOption('auto');
    await save();
    assert.equal(puts.at(-1).fallback, 'builtin_searxng');
    assert.equal(puts.at(-1).base_url, null);
    assert.deepEqual(puts.at(-1).hosted.brave, {enabled: false, monthly_limit: 900});

    // Enabling two hosted providers sends each key and limit; keys are
    // never rendered back in full and the inputs are cleared.
    await page.locator('#websearch-brave-enabled').check();
    await page.locator('#websearch-brave-api-key').fill('brave-test-key-1234');
    await page.locator('#websearch-tavily-enabled').check();
    await page.locator('#websearch-tavily-api-key').fill('tvly-test-key-5678');
    await page.locator('#websearch-tavily-limit').fill('500');
    await save();
    assert.deepEqual(puts.at(-1).hosted.brave, {enabled: true, monthly_limit: 900, api_key: 'brave-test-key-1234'});
    assert.deepEqual(puts.at(-1).hosted.tavily, {enabled: true, monthly_limit: 500, api_key: 'tvly-test-key-5678'});
    assert.deepEqual(puts.at(-1).hosted.exa, {enabled: false, monthly_limit: 900});
    assert.equal(await page.locator('#websearch-brave-api-key').inputValue(), '');
    assert.equal(await page.locator('#websearch-brave-key-state').textContent(), 'Saved key: ********1234');

    // A later save without retyping keeps the saved key (no api_key sent);
    // "Remove saved key" sends an explicit null.
    await page.locator('#websearch-tavily-clear-key').check();
    await save();
    assert.equal('api_key' in puts.at(-1).hosted.brave, false);
    assert.equal(puts.at(-1).hosted.tavily.api_key, null);

    // Switching the fallback to External SearXNG reveals its URL/key fields.
    await page.locator('#websearch-fallback').selectOption('searxng');
    assert.equal(await page.locator('#websearch-base-url-field').isHidden(), false);
    assert.equal(await page.locator('#websearch-key-fields').isHidden(), false);
    await page.locator('#websearch-base-url').fill('http://searxng-host:8080');
    await save();
    assert.equal(puts.at(-1).fallback, 'searxng');
    assert.equal(puts.at(-1).base_url, 'http://searxng-host:8080');
    // Usage card and pop-out debug log (Phase 24d). Provider-supplied text
    // renders literally and a non-http(s) result URL never becomes a link.
    assert.equal(await page.locator('#search-usage-period').textContent(), 'This month (2026-09, UTC)');
    assert.equal(await page.locator('.search-usage-row').nth(1).textContent(), 'exa (off)0 / 900');
    assert.equal(await page.locator('.search-usage-row meter').first().evaluate(m => [m.value, m.max].join('/')), '12/900');
    await page.locator('#open-search-log').click();
    await page.locator('#search-log-dialog .search-entry').waitFor();
    assert.equal(await page.locator('#search-log-dialog').evaluate(d => d.open), true);
    const entry = page.locator('#search-log-dialog .search-entry');
    assert.match(await entry.textContent(), /served by exa · 812 ms · policy auto/);
    assert.equal(await entry.locator('strong').textContent(), 'latest <b>python</b>');
    assert.match(await entry.textContent(), /brave error \(400 ms\) → exa ok \(412 ms\)/);
    assert.equal(await entry.locator('img').count(), 0);
    assert.equal(await entry.locator('li').first().locator('a').count(), 0);
    assert.equal(await entry.locator('li').nth(1).locator('a').getAttribute('href'), 'https://python.org/');
    assert.equal(await entry.locator('li').nth(1).locator('a').getAttribute('rel'), 'noopener noreferrer');
    await page.locator('#close-search-log').click();

    // Owner location and time zone (Phase 24d) for the model's context.
    assert.equal(await page.locator('#persona-timezone').inputValue(), 'UTC');
    await page.locator('#persona-location').fill('Singapore');
    await page.locator('#persona-browser-timezone').click();
    assert.equal(await page.locator('#persona-timezone').inputValue(), 'Asia/Singapore');
    await Promise.all([
      page.waitForResponse(r => r.url().includes('/settings/persona') && r.request().method() === 'PUT'),
      page.locator('#persona').locator('button', {hasText: 'Save persona'}).click(),
    ]);
    assert.deepEqual(personaPuts.at(-1), {name: 'Reachy', system_prompt: 'p', location: 'Singapore', timezone: 'Asia/Singapore'});
    assert.equal(await page.locator('#persona-location').inputValue(), 'Singapore');
    assert.equal(await page.locator('#search-log-dialog').evaluate(d => d.open), false);
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
});
