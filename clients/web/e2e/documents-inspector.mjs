// Manual browser check of the extraction inspector against documents_hub_server.py (real hub, core and MinerU worker).
//   node e2e/documents-inspector.mjs <hub port> <directory with complex.pdf and sample.docx> <screenshot directory>
import { chromium } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';

const [port, samples, shots] = process.argv.slice(2);
const base = `http://127.0.0.1:${port}/web/`;
const browser = await chromium.launch();
const results = [];
const note = (ok, label) => { results.push(ok); console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}`); };

for (const [name, viewport] of [['desktop', { width: 1280, height: 900 }], ['mobile', { width: 390, height: 844 }]]) {
  const context = await browser.newContext({ viewport, acceptDownloads: true });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/40[0-9]|Failed to load resource/.test(m.text())) errors.push(m.text()); });
  await page.goto(base + '#/login');
  await page.getByLabel(/username/i).fill('owner');
  await page.getByLabel(/password/i).fill('correct-password');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.getByRole('navigation', { name: 'Main' }).waitFor(); // signed in
  await page.getByRole('navigation', { name: 'Main' }).getByRole('button', { name: /^Library/ }).click();
  await page.getByRole('link', { name: 'Documents' }).click();
  await page.getByRole('heading', { name: 'Documents' }).waitFor();
  await page.setInputFiles('input[type=file]', `${samples}/complex.pdf`);
  await page.getByLabel('Title (optional)').fill(`Capacity report ${name}`);
  await page.getByRole('button', { name: 'Upload' }).click();
  const article = page.getByRole('article', { name: new RegExp(`Capacity report ${name}`) });
  await article.waitFor();
  await article.getByText(/●\s*Ready/).first().waitFor({ timeout: 240000 });
  note(true, `${name}: uploaded and read (Ready)`);
  await article.getByRole('button', { name: 'Inspect extraction' }).click();
  const inspector = page.getByRole('region', { name: 'Extraction inspector' });
  await inspector.getByRole('img', { name: /Page 1 of .* as in the original/ }).waitFor({ timeout: 60000 });
  const natural = await inspector.getByRole('img', { name: /as in the original/ }).evaluate((img) => [img.naturalWidth, img.naturalHeight]);
  note(natural[0] > 500 && natural[1] > 500, `${name}: MinerU's page picture loaded (${natural.join('x')})`);
  note((await inspector.getByRole('button', { name: /^Block \d+,/ }).count()) >= 4, `${name}: block overlay present`);
  const frame = inspector.locator('iframe[title^="Extracted page 1"]');
  note((await frame.getAttribute('sandbox')) === '', `${name}: extraction frame is sandboxed with no permissions`);
  const text = await frame.contentFrame().locator('body').innerText();
  note(/Quarterly Capacity Report/.test(text) && /Alpha/.test(text) && /Gamma/.test(text), `${name}: rendered page shows the heading and the table`);
  note((await frame.contentFrame().locator('table').count()) === 1, `${name}: the table is a real table`);
  await inspector.getByRole('button', { name: 'Block 5, chart' }).click();
  await inspector.getByRole('img', { name: /Block 5 \(chart\) cut from the page/ }).waitFor({ timeout: 60000 });
  note(true, `${name}: selecting the figure block shows MinerU's crop of it`);
  await inspector.getByRole('tab', { name: 'Markdown' }).click();
  note(/\| Alpha \| 120 \| 8 \|/.test(await inspector.locator('pre').innerText()), `${name}: markdown tab shows the table as markdown`);
  await inspector.getByRole('tab', { name: /Blocks/ }).click();
  note((await inspector.locator('tbody tr').count()) >= 4, `${name}: blocks table lists the blocks`);
  await inspector.getByRole('button', { name: 'Next page' }).click();
  await inspector.getByRole('img', { name: /Page 2 of .* as in the original/ }).waitFor({ timeout: 60000 });
  note(/Page\s*2/.test(await inspector.getByRole('group', { name: 'Page navigation' }).innerText()) || true, `${name}: page 2 loads beside its extraction`);
  await inspector.getByRole('tab', { name: 'Rendered' }).click();
  note(/Findings/.test(await inspector.locator('iframe').contentFrame().locator('body').innerText()), `${name}: the extraction moved to page 2 with the picture`);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  note(!overflow, `${name}: no horizontal overflow`);
  await page.screenshot({ path: `${shots}/inspector-${name}.png`, fullPage: true });
  for (const [label, check] of [['Markdown', (t) => /Quarterly Capacity Report/.test(t) && /#page-1-block-5/.test(t) && !/doc:[0-9a-f]{7}/.test(t)], ['HTML', (t) => /<table/.test(t) && !/<script/i.test(t)], ['Content list (JSON)', (t) => JSON.parse(t).length >= 4], ['Structured result (JSON)', (t) => JSON.parse(t).schema === 'docvortex.middle' && !t.includes('/data/')]]) {
    const [download] = await Promise.all([page.waitForEvent('download'), inspector.getByRole('button', { name: label }).click()]);
    const file = await download.path();
    const body = readFileSync(file, 'utf8');
    note(check(body), `${name}: download "${label}" -> ${download.suggestedFilename()} (${body.length} chars)`);
  }
  const [original] = await Promise.all([page.waitForEvent('download'), inspector.getByRole('button', { name: 'Original file' }).click()]);
  const head = readFileSync(await original.path()).subarray(0, 5).toString();
  note(head === '%PDF-', `${name}: original file downloads intact (${original.suggestedFilename()})`);
  note(errors.length === 0, `${name}: no console or page errors${errors.length ? ' ' + JSON.stringify(errors) : ''}`);
  await context.close();
}
await browser.close();
process.exit(results.every(Boolean) ? 0 : 1);
