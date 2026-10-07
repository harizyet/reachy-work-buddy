// Real browser, fixture API: delete meetings (single and failed/cancelled bulk) with confirmation, summary and minutes
// with a rerun on a higher tier, the deep-local warning, and a meeting attached as chat context. Text is hostile on
// purpose and must render literally.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

test('meetings: delete, summary and minutes with rerun tiers, and use as context', async () => {
  const segments = [{start: 0, end: 6, text: 'We compare ClickHouse and InfluxDB.'}, {start: 6, end: 12, text: 'ClickHouse is open source <img src=x onerror=boom()>.'}];
  const meetings = new Map();
  const add = (id, title, status, extra = {}) => meetings.set(id, {id, title, status, participants: [], created_at: '2026-10-07T00:00:00Z', transcript_segments: null, diarization_segments: null, transcript_corrections: {}, summary: null, minutes: null, ...extra});
  add('ready', 'Database choice', 'aligning', {transcript_segments: segments, diarization_segments: [{start: 0, end: 12, speaker: 'SPEAKER_00'}]});
  add('failed', 'Old failed test', 'failed', {error_detail: 'boom'});
  add('cancelled', 'Cancelled upload', 'cancelled');
  add('busy', 'Stuck upload', 'transcribing');
  const calls = []; const messages = []; let jobPolls = 0;
  const output = (tier, text) => ({text, tier, generated_at: '2026-10-07T10:00:00Z'});
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
    if (route === '/meetings' && req.method === 'GET') return json([...meetings.values()]);
    let m = route.match(/^\/meetings\/([a-z]+)$/);
    if (m && req.method === 'GET') return meetings.has(m[1]) ? json(meetings.get(m[1])) : json({detail: 'no'}, 404);
    if (m && req.method === 'DELETE') { calls.push(`delete:${m[1]}`); meetings.delete(m[1]); return json({deleted: true}); }
    m = route.match(/^\/meetings\/([a-z]+)\/outputs\/(summary|minutes)(\/deep)?$/);
    if (m && req.method === 'POST' && !m[3]) {
      calls.push(`output:${m[2]}:${body.model}`);
      meetings.get(m[1])[m[2]] = output(body.model, body.model === 'local' ? 'Local <b>summary</b> of the ClickHouse talk.' : `Better ${m[2]} from ${body.model}.`);
      return json(meetings.get(m[1]));
    }
    if (m && req.method === 'POST' && m[3]) { calls.push(`deep-output:${m[2]}`); return json({id: 'j1', meeting_id: m[1], meeting_title: 'Database choice', task: m[2], status: 'switching', stage: 'Loading the larger model', reachy_unavailable: true, reachy_online: false}, 202); }
    if (route === '/deep-review/info') return json({configured: true, available: true, eta_seconds: 330});
    if (route === '/deep-review/current') return json(null);
    if (route === '/deep-review/j1') {
      const status = ['switching', 'reviewing', 'done'][Math.min(jobPolls++, 2)];
      if (status !== 'switching') meetings.get('ready').summary = output('deep', 'Deep summary from the larger model.');
      return json({id: 'j1', meeting_id: 'ready', meeting_title: 'Database choice', task: 'summary', status, stage: 'working', reachy_unavailable: status !== 'done', reachy_online: status === 'done', result: status === 'switching' ? null : {kind: 'summary', tier: 'deep', text: 'x'}});
    }
    if (route === '/chats' && req.method === 'POST') return json({id: 'c1', title: body.title});
    if (route === '/chats') return json([]);
    if (route === '/messages') { messages.push(body); return json({reply: 'ClickHouse is open source, per the meeting.', context_meeting: body.context_meeting_id ? 'Database choice' : null, session_id: 's', conversation_id: 'c', active_channel: 'web', delivery_channel: 'web', privacy: 'work-private'}); }
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
    await page.click('#meetings-tab');
    await page.waitForSelector('#meeting-list li');

    // list: delete only where nothing is processing; bulk clear counts failed and cancelled
    const row = title => page.locator('#meeting-list li', {hasText: title});
    assert.equal(await row('Old failed test').getByRole('button', {name: /Delete/}).count(), 1);
    assert.equal(await row('Stuck upload').getByRole('button', {name: /Delete/}).count(), 0);
    assert.match(await page.textContent('#meeting-clear-failed'), /\(2\)/);

    // single delete asks first; cancel does nothing, confirm deletes
    await row('Old failed test').getByRole('button', {name: /Delete/}).click();
    await page.waitForSelector('#confirm-dialog[open]');
    assert.match(await page.textContent('#confirm-text'), /cannot be undone/);
    await page.click('#confirm-cancel');
    assert.deepEqual(calls, []);
    await row('Old failed test').getByRole('button', {name: /Delete/}).click();
    await page.click('#confirm-ok');
    await page.waitForFunction(() => !document.getElementById('meeting-list').textContent.includes('Old failed test'));
    assert.deepEqual(calls, ['delete:failed']);

    // bulk delete the remaining cancelled one
    await page.click('#meeting-clear-failed'); await page.click('#confirm-ok');
    await page.waitForFunction(() => !document.getElementById('meeting-list').textContent.includes('Cancelled upload'));
    assert.ok(calls.includes('delete:cancelled'));

    // detail of a processed meeting: toolbar, summary auto-written locally, shown literally
    await row('Database choice').getByRole('button', {name: 'View details'}).click();
    await page.waitForSelector('#meeting-toolbar:not([hidden])');
    await page.click('#meeting-tab-summary');
    await page.waitForFunction(() => document.getElementById('meeting-output-text').textContent.includes('Local <b>summary</b>'));
    assert.equal(await page.locator('#meeting-output-text b').count(), 0);
    assert.match(await page.textContent('#meeting-output-meta'), /Written by the local model/);
    assert.ok(calls.includes('output:summary:local'));

    // rerun on the cloud, then minutes
    await page.selectOption('#meeting-output-model', 'cloud'); await page.click('#meeting-output-run');
    await page.waitForFunction(() => document.getElementById('meeting-output-text').textContent.includes('Better summary from cloud'));
    assert.match(await page.textContent('#meeting-output-meta'), /cloud model/);
    await page.click('#meeting-tab-minutes');
    await page.waitForFunction(() => document.getElementById('meeting-output-text').textContent.length > 0);
    assert.ok(calls.some(c => c.startsWith('output:minutes')));

    // deep rerun: warns first, starts the job, banner, then the stored deep summary appears
    await page.click('#meeting-tab-summary');
    await page.selectOption('#meeting-output-model', 'deep'); await page.click('#meeting-output-run');
    await page.waitForSelector('#deep-warning[open]');
    assert.match(await page.textContent('#deep-warning-text'), /Reachy will be unavailable/);
    await page.click('#deep-warning-cancel');
    assert.ok(!calls.includes('deep-output:summary'));
    await page.click('#meeting-output-run'); await page.waitForSelector('#deep-warning[open]'); await page.click('#deep-warning-start');
    await page.waitForSelector('#deep-banner:not([hidden])');
    await page.waitForSelector('#deep-banner', {state: 'hidden', timeout: 30000});
    await page.waitForFunction(() => document.getElementById('meeting-output-text').textContent.includes('Deep summary from the larger model'));
    assert.match(await page.textContent('#meeting-output-meta'), /larger local model/);
    assert.match(await page.textContent('#notice'), /deep summary/);

    // use as context: lands in chat with a chip; the next question carries the meeting id and the answer says where it came from
    await page.click('#meeting-use-context');
    await page.waitForSelector('#chat-context:not([hidden])');
    assert.match(await page.textContent('#chat-context-title'), /Database choice/);
    await page.waitForFunction(() => !document.getElementById('chat-text').disabled);
    await page.fill('#chat-text', 'is clickhouse free?'); await page.click('#chat-send');
    await page.waitForFunction(() => document.getElementById('chat-transcript').textContent.includes('per the meeting'));
    assert.equal(messages.at(-1).context_meeting_id, 'ready');
    assert.match(await page.textContent('#chat-transcript'), /From the meeting “Database choice”/);
    await page.click('#chat-context-clear');
    assert.equal(await page.isHidden('#chat-context'), true);

    // delete from the detail
    await page.click('#meetings-tab');
    await row('Database choice').getByRole('button', {name: 'View details'}).click();
    await page.click('#meeting-delete'); await page.click('#confirm-ok');
    await page.waitForFunction(() => !document.getElementById('meeting-list').textContent.includes('Database choice'));
    assert.ok(calls.includes('delete:ready') && injected === false);
  } finally { await browser.close(); server.close(); }
});
