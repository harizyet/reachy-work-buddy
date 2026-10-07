// Real browser, fixture API: suggest corrections with a model choice, the Deep local warning, the unavailable banner
// that follows the owner across tabs, results arriving when the review finishes, and literal rendering of hostile text.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('deep local review: warning, banner on every tab, results, change all', async () => {
  const meeting = {id: 'm1', title: 'AI tools', status: 'complete', participants: [], created_at: '2026-10-07T00:00:00Z',
    transcript_segments: [{start: 0, end: 3, text: 'And germanite.'}, {start: 3, end: 6, text: 'I will test germanite <img src=x onerror=boom()>.'}],
    diarization_segments: [], transcript_corrections: {}};
  const suggestion = {segment: 0, original: 'germanite', suggested: 'Gemini', reason: 'Gemini is an AI model <b>name</b>', corrected_text: 'And Gemini.', confidence: 'likely', source: 'terms'};
  const phases = ['switching', 'reviewing', 'restoring', 'done'];
  let polls = 0; let started = 0; const calls = [];
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
    if (req.method !== 'GET') assert.equal(req.headers['x-reachy-csrf'], '1');
    if (route === '/auth/me') return json({username: 'owner'});
    if (route === '/status') return json({reachy_hub: {status: 'ok'}, companion_core: {status: 'ok'}, robots: [], owner_bound: true, default_user_id: 'owner', llm: {configured: true, usage: {data: null}}, telegram: {configured: false}});
    if (route === '/meetings' && req.method === 'GET') return json([meeting]);
    if (route === '/meetings/m1' && req.method === 'GET') return json(meeting);
    if (route === '/deep-review/info') return json({configured: true, available: started === 0, reason: started ? 'a deep review is already running' : null, eta_seconds: 330});
    if (route === '/deep-review/current') return json(null);
    if (route === '/meetings/m1/corrections/deep-review') { started += 1; calls.push('deep-start'); return json({id: 'j1', meeting_id: 'm1', meeting_title: 'AI tools', status: 'switching', stage: 'Loading the larger model', reachy_unavailable: true, reachy_online: false}, 202); }
    if (route === '/deep-review/j1') {
      const status = phases[Math.min(polls++, phases.length - 1)];
      const done = status === 'done';
      return json({id: 'j1', meeting_id: 'm1', meeting_title: 'AI tools', status, stage: status === 'reviewing' ? 'Reviewing the transcript with the larger model' : status === 'restoring' ? 'Reloading the standard model' : status === 'done' ? 'Reachy is back online' : 'Loading the larger model',
        reachy_unavailable: !done, reachy_online: done, result: ['restoring', 'done'].includes(status) ? {suggestions: [suggestion, {...suggestion, segment: 1}], checked_segments: 2, truncated: false, terms_used: 3, candidates_checked: 2} : null});
    }
    if (route === '/meetings/m1/corrections/suggest') { calls.push(`suggest:${body.model}`); return json({suggestions: [], checked_segments: 2, truncated: false, terms_used: 0, candidates_checked: 0}); }
    if (route === '/meetings/m1/corrections/replace') { calls.push(`replace:${body.find}->${body.replace}`); meeting.transcript_corrections = {0: 'And Gemini.', 1: 'I will test Gemini <img src=x onerror=boom()>.'}; return json({meeting, replaced_segments: 2}); }
    return json([]);
  });
  await new Promise(resolve => server.listen(0, resolve));
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext();
    await context.grantPermissions([]);
    const page = await context.newPage();
    let injected = false;
    page.on('dialog', () => { injected = true; });
    await page.goto(`http://127.0.0.1:${server.address().port}/hub/ui/`);
    await page.click('#meetings-tab');
    await page.click('text=View details');
    await page.waitForSelector('#meeting-suggest:not([hidden])');

    // ordinary local suggestion: no warning, a plain call
    await page.selectOption('#meeting-suggest-model', 'local');
    await page.click('#meeting-suggest-go');
    await page.waitForFunction(() => document.getElementById('meeting-suggest-status').textContent.includes('No likely mistakes'));
    assert.deepEqual(calls, ['suggest:local']);
    assert.equal(await page.isVisible('#deep-warning'), false);

    // deep local: a warning first; cancelling starts nothing
    await page.selectOption('#meeting-suggest-model', 'deep');
    await page.click('#meeting-suggest-go');
    await page.waitForSelector('#deep-warning[open]');
    const warning = await page.textContent('#deep-warning-text');
    assert.match(warning, /unavailable/i); assert.match(warning, /6 minutes/); assert.match(warning, /Telegram/);
    await page.click('#deep-warning-cancel');
    assert.equal(started, 0);

    // confirm: banner appears and follows the owner to another tab
    await page.click('#meeting-suggest-go');
    await page.waitForSelector('#deep-warning[open]');
    await page.click('#deep-warning-start');
    await page.waitForSelector('#deep-banner:not([hidden])');
    assert.match(await page.textContent('#deep-banner'), /Reachy is unavailable/);
    await page.click('#todo-tab');
    assert.equal(await page.isVisible('#deep-banner'), true);
    assert.equal(await page.isDisabled('#meeting-suggest-go'), true);

    // finishing: banner clears, an in-page notice says Reachy is back, and the results are on the meeting
    await page.waitForSelector('#deep-banner', {state: 'hidden', timeout: 30000});
    assert.match(await page.textContent('#notice'), /Reachy is back online/);
    await page.click('#meetings-tab');
    await page.waitForSelector('#meeting-suggestions li');
    const card = await page.locator('#meeting-suggestions').innerText();
    assert.match(card, /germanite → Gemini/); assert.match(card, /Matches your term/); assert.match(card, /Change all 2/);
    assert.match(card, /<b>name<\/b>/);  // literal, not markup
    assert.equal(await page.locator('#meeting-suggestions b').count(), 0);

    // change all
    await page.click('text=Change all 2');
    await page.waitForFunction(() => document.getElementById('meeting-detail-transcript').textContent.includes('(edited)'));
    assert.ok(calls.includes('replace:germanite->Gemini'));
    const transcript = await page.locator('#meeting-detail-transcript').innerText();
    assert.match(transcript, /And Gemini\./);
    assert.equal(await page.locator('#meeting-detail-transcript img').count(), 0);
    assert.equal(injected, false);
  } finally { await browser.close(); server.close(); }
});
