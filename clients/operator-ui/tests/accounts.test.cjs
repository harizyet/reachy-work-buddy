const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('Accounts works at direct/proxied mounts, explains Google login, and renders provider text literally', async () => {
  let loggedIn = true;
  const requests = [];
  const malicious = '<img src=x onerror="window.injected=true"> private mail';
  const status = {
    configured: true, client_id: 'fixture', client_secret: '********',
    redirect_uri: 'http://localhost/hub/settings/accounts/google/callback',
    identity: {email: 'owner@example.org'}, scopes: ['https://www.googleapis.com/auth/gmail.readonly'],
    selected_calendars: ['one'],
    capabilities: {gmail: {enabled: true, status: 'connected'}, calendar: {enabled: true, status: 'connected'}},
  };
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://fixture');
    const route = decodeURIComponent(url.pathname).replace(/^\/hub/, '');
    const json = (body, code = 200) => {res.writeHead(code, {'Content-Type': 'application/json'}); res.end(JSON.stringify(body));};
    if (route.startsWith('/ui/')) {
      const file = route.slice(4) || 'index.html';
      if (!['index.html','app.js','chat.js','voice.js','accounts.js','style.css'].includes(file)) return json({}, 404);
      res.writeHead(200, {'Content-Type': file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'});
      return res.end(fs.readFileSync(path.join(__dirname, '..', file)));
    }
    if (route === '/auth/me') return json({username: 'owner'}, loggedIn ? 200 : 401);
    if (route === '/auth/logout') { loggedIn = false; return json({ok:true}); }
    if (route === '/status') return json({
      reachy_hub:{status:'ok'}, companion_core:{status:'ok'}, robots:[],
      default_user_id:'default-user', telegram:{configured:false}, llm:{configured:false, usage:{}},
    });
    if (route === '/settings/llm') return json({local:null});
    if (route.startsWith('/sessions/')) return json({},404);
    if (route.startsWith('/settings/accounts/google')) {
      requests.push({route, method:req.method, csrf:req.headers['x-reachy-csrf']});
      if (route.endsWith('/messages/google:abc')) return json({body: malicious});
      if (route.endsWith('/messages')) return json({messages:[{id:'google:abc', sender:'fixture',subject:malicious}]});
      if (route.endsWith('/calendars')) return json({calendars:[{id:'one',name:malicious,timezone:'UTC'}]});
      if (route.endsWith('/free-busy')) return json({busy:[{start:new Date().toISOString(),end:new Date().toISOString()}]});
      if (route.endsWith('/events')) return json({events:[{title:malicious,start:new Date().toISOString()}]});
      return json(status);
    }
    return json([]);
  });
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const browser = await chromium.launch({headless:true});
  try {
    for (const prefix of ['', '/hub']) {
      loggedIn = true;
      const page = await browser.newPage({viewport:{width:390,height:844}});
      const errors = []; page.on('pageerror', e => errors.push(e.message));
      await page.goto('http://127.0.0.1:' + server.address().port + prefix + '/ui/?google=return');
      await page.waitForFunction(() => document.querySelector('#accounts-pane').hidden === false);
      await page.waitForFunction(() => document.querySelector('#google-identity').textContent.includes('owner@example.org'));
      assert.match(await page.locator('#accounts-pane').textContent(), /never sees your Google password/);
      assert.equal(await page.locator('#google-callback').inputValue(),
        'http://127.0.0.1:' + server.address().port + prefix + '/settings/accounts/google/callback');
      await page.locator('#gmail-search button').click();
      await page.locator('#account-results button').click();
      assert.equal(await page.locator('#account-results pre').textContent(),malicious);
      assert.equal(await page.evaluate(() => window.injected),undefined);
      assert.equal(await page.evaluate(() => localStorage.length),0);
      await page.locator('#calendar-busy').click();
      await page.waitForFunction(() => document.getElementById('account-results').textContent.includes('Busy'));
      assert.equal(await page.locator('#accounts-pane input[type=password]').count(),0);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
      assert.equal(new URL(page.url()).search,'');
      await page.locator('#logout').click();
      await page.waitForFunction(() => document.getElementById('dashboard').hidden);
      assert.equal(await page.locator('#account-results').textContent(),'');
      assert.deepEqual(errors,[]);
      await page.close();
    }
    assert.ok(requests.some(r => r.route.endsWith('/complete') && r.method === 'POST' && r.csrf === '1'));
  } finally {
    await browser.close(); await new Promise(resolve => server.close(resolve));
  }
});

test('Desktop OAuth mode hides the return address and shows a helper command with no secret', async () => {
  const status = {
    configured: true, client_id: 'fixture-desktop-client', client_type: 'desktop', client_secret: '********',
    redirect_uri: '', identity: null, scopes: [], selected_calendars: [],
    capabilities: {gmail: {enabled: false, status: 'disconnected'}, calendar: {enabled: false, status: 'disconnected'}},
  };
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://fixture');
    const route = decodeURIComponent(url.pathname);
    const json = (body, code = 200) => {res.writeHead(code, {'Content-Type': 'application/json'}); res.end(JSON.stringify(body));};
    if (route.startsWith('/ui/')) {
      const file = route.slice(4) || 'index.html';
      if (!['index.html','app.js','chat.js','voice.js','accounts.js','style.css'].includes(file)) return json({}, 404);
      res.writeHead(200, {'Content-Type': file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'});
      return res.end(fs.readFileSync(path.join(__dirname, '..', file)));
    }
    if (route === '/auth/me') return json({username: 'owner'});
    if (route === '/status') return json({
      reachy_hub:{status:'ok'}, companion_core:{status:'ok'}, robots:[],
      default_user_id:'default-user', telegram:{configured:false}, llm:{configured:false, usage:{}},
    });
    if (route === '/settings/llm') return json({local:null});
    if (route.startsWith('/sessions/')) return json({},404);
    if (route === '/settings/accounts/google/desktop/start') {
      return json({
        state: 'fixture-state', binding: 'fixture-binding-returned-in-body',
        client_id: 'fixture-desktop-client', scope: 'openid email gmail.readonly',
        code_challenge: 'fixture-challenge', code_challenge_method: 'S256',
      });
    }
    if (route.startsWith('/settings/accounts/google')) return json(status);
    return json([]);
  });
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto('http://127.0.0.1:' + server.address().port + '/ui/?google=return');
    await page.waitForFunction(() => document.querySelector('#accounts-pane').hidden === false);
    await page.waitForFunction(() => document.querySelector('#google-setup-state').textContent.includes('saved'));
    assert.equal(await page.locator('#google-callback-label').isVisible(), false);
    await page.locator('#account-cards button:has-text("Connect")').first().click();
    await page.waitForFunction(() => document.getElementById('google-desktop-connect').hidden === false);
    const command = await page.locator('#google-desktop-command').textContent();
    assert.match(command, /google_auth_helper\.py/);
    assert.match(command, /fixture-desktop-client/);
    assert.match(command, /fixture-binding-returned-in-body/);
    assert.equal(command.includes('client_secret'), false);
    assert.equal(command.includes('verifier'), false);
    assert.equal(await page.evaluate(() => localStorage.length), 0);
    assert.deepEqual(errors, []);
    await page.close();
  } finally {
    await browser.close(); await new Promise(resolve => server.close(resolve));
  }
});
