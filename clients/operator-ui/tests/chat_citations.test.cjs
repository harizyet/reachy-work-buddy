// Real browser, fixture API: a chat answer's [S1] citations are clickable, a visible Sources list sits under it, unsafe
// links stay plain text, and hostile titles/answers render literally.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('chat shows clickable citations and a sources list', async () => {
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
    if (route === '/auth/me') return json({username: 'owner'});
    if (route === '/status') return json({reachy_hub: {status: 'ok'}, companion_core: {status: 'ok'}, robots: [], owner_bound: true, default_user_id: 'owner', llm: {configured: true, usage: {data: null}}, telegram: {configured: false}});
    if (route === '/chats' && req.method === 'POST') return json({id: 'c1', title: 't'});
    if (route === '/chats') return json([]);
    if (route === '/messages') return json({
      reply: 'ClickHouse is open source under Apache 2.0 [S1], with a paid cloud service [S2]. Unknown [S9] <img src=x onerror=boom()>.',
      session_id: 's', conversation_id: 'c', active_channel: 'web', delivery_channel: 'web', privacy: 'public',
      web_search: {query: 'is clickhouse free', failed: false, results: [
        {title: 'ClickHouse licence <b>FAQ</b>', url: 'https://clickhouse.com/docs/faq', snippet: 'Apache 2.0', source_domain: 'clickhouse.com'},
        {title: 'Pricing', url: 'https://clickhouse.com/pricing', snippet: 'Cloud pricing', source_domain: 'clickhouse.com'},
        {title: 'Sneaky', url: 'javascript:alert(1)', snippet: 'x', source_domain: 'evil'},
      ]},
    });
    if (route.startsWith('/sessions/')) return json({user_id: 'owner', interaction_mode: 'text', dnd: false, active_channel: 'web'});
    return json([]);
  });
  await new Promise(resolve => server.listen(0, resolve));
  const browser = await chromium.launch();
  try {
    const page = await (await browser.newContext()).newPage();
    let injected = false;
    page.on('dialog', () => { injected = true; });
    await page.goto(`http://127.0.0.1:${server.address().port}/hub/ui/`);
    await page.click('#chat-tab');
    await page.waitForFunction(() => !document.getElementById('chat-text').disabled);
    await page.fill('#chat-text', 'is clickhouse free?'); await page.click('#chat-send');
    await page.waitForSelector('.chat-from-reachy, .from-reachy .chat-sources, .chat-sources');

    const message = page.locator('.chat-message.from-reachy').last();
    // inline citations: the first two are real links, the unknown id is plain text
    const cites = message.locator('p a.chat-cite');
    assert.equal(await cites.count(), 2);
    assert.equal(await cites.nth(0).getAttribute('href'), 'https://clickhouse.com/docs/faq');
    assert.equal(await cites.nth(1).getAttribute('href'), 'https://clickhouse.com/pricing');
    assert.equal(await cites.nth(0).getAttribute('target'), '_blank');
    assert.match(await cites.nth(0).getAttribute('rel'), /noopener/);
    assert.match(await message.locator('p').first().textContent(), /Unknown \[S9\]/);

    // visible sources list: links for safe urls, plain text for the javascript: one, titles literal
    const sources = message.locator('.chat-sources li');
    assert.equal(await sources.count(), 3);
    assert.equal(await sources.nth(0).locator('a').getAttribute('href'), 'https://clickhouse.com/docs/faq');
    assert.match(await sources.nth(0).textContent(), /clickhouse\.com: ClickHouse licence <b>FAQ<\/b>/);
    assert.equal(await sources.nth(2).locator('a').count(), 0);
    assert.equal(await message.locator('.chat-sources b').count(), 0);
    assert.equal(await message.locator('img').count(), 0);
    assert.equal(injected, false);
  } finally { await browser.close(); server.close(); }
});
