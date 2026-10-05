const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('Coding agent credentials: shows configured state, saves without echoing the secret, and never touches localStorage', async () => {
  let loggedIn = true;
  const requests = [];
  let stored = null;
  const server = http.createServer(async (req, res) => {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = chunks.length ? JSON.parse(Buffer.concat(chunks)) : null;
    const url = new URL(req.url, 'http://fixture');
    const route = decodeURIComponent(url.pathname);
    const json = (payload, code = 200) => {res.writeHead(code, {'Content-Type': 'application/json'}); res.end(JSON.stringify(payload));};
    if (route.startsWith('/ui/')) {
      const file = route.slice(4) || 'index.html';
      if (!['index.html','app.js','chat.js','voice.js','accounts.js','owner-recognition.js','meetings.js','coding_agents.js', 'alarms.js', 'planner.js', 'coding_monitor.js','style.css'].includes(file)) return json({}, 404);
      res.writeHead(200, {'Content-Type': file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'});
      return res.end(fs.readFileSync(path.join(__dirname, '..', file)));
    }
    if (route === '/auth/me') return json({username: 'owner'}, loggedIn ? 200 : 401);
    if (route === '/status') return json({
      reachy_hub:{status:'ok'}, companion_core:{status:'ok'}, robots:[],
      default_user_id:'default-user', telegram:{configured:false}, llm:{configured:false, usage:{}},
    });
    if (route === '/settings/llm') return json({local:null});
    if (route.startsWith('/sessions/')) return json({},404);
    if (route.startsWith('/settings/accounts/google')) return json({
      configured:false, identity:null, scopes:[], selected_calendars:[],
      capabilities:{gmail:{enabled:false,status:'disconnected'}, calendar:{enabled:false,status:'disconnected'}},
    });
    if (route === '/providers/credentials') return json(stored ? [stored] : []);
    if (route === '/providers/claude-code/credential') {
      requests.push({method: req.method, body});
      if (req.method === 'PUT') { stored = {provider:'claude-code', kind: body.kind, last_four: body.value.slice(-4), updated_at: new Date().toISOString()}; return json(stored); }
      if (req.method === 'DELETE') { stored = null; return json({status:'cleared'}); }
      return stored ? json(stored) : json({detail:'No credential configured'}, 404);
    }
    return json([]);
  });
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto('http://127.0.0.1:' + server.address().port + '/ui/');
    await page.locator('#settings-tab').click();
      await page.locator('#settings-accounts-tab').click();
    await page.waitForFunction(() => document.getElementById('coding-agent-cards').children.length > 0);
    assert.match(await page.locator('#coding-agent-cards').textContent(), /No credential configured yet/);

    const claudeCard = page.locator('#coding-agent-cards .card').first();
    await claudeCard.locator('input[type=password]').fill('sk-ant-abcd1234');
    await claudeCard.locator('button[type=submit], form button').first().click();
    await page.waitForFunction(() => document.getElementById('coding-agent-cards').textContent.includes('ending 1234'));
    assert.equal(await claudeCard.locator('input[type=password]').inputValue(), '');

    assert.ok(requests.some(r => r.method === 'PUT' && r.body.value === 'sk-ant-abcd1234'));
    assert.equal(await page.locator('#coding-agent-cards').textContent().then(t => t.includes('sk-ant-abcd1234')), false);

    page.once('dialog', d => d.accept());
    await claudeCard.locator('button:has-text("Remove credential")').click();
    await page.waitForFunction(() => document.getElementById('coding-agent-cards').textContent.includes('No credential configured yet'));
    assert.ok(requests.some(r => r.method === 'DELETE'));

    assert.equal(await page.evaluate(() => localStorage.length), 0);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    await page.close();
  } finally {
    await browser.close(); await new Promise(resolve => server.close(resolve));
  }
});
