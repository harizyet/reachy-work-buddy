// Phase 53 UAT rehearsal (not part of the CI suite). Needs the disposable stack described in docs/verification/phase-53-uat-rehearsal-2026-10-14.md; run from clients/web: node e2e/multimodal-rehearsal-restart.mjs <scratch dir holding deck.pdf>
import { chromium } from '@playwright/test';
const SP = process.argv[2];
const BASE = 'http://127.0.0.1:' + (process.env.MM_PORT ?? '18060') + '/web/';
const log = [];
const note = (k, v) => { log.push([k, v]); console.log(k, JSON.stringify(v)); };
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
const posts = [];
page.on('request', (r) => { if (r.method() !== 'GET') posts.push(`${r.method()} ${new URL(r.url()).pathname}`); });
page.on('pageerror', (e) => note('PAGEERROR', String(e)));
page.on('console', (m) => { if (m.type() === 'error') note('CONSOLE', m.text().slice(0, 200)); });
await page.goto(BASE + '#/meetings/uat-meeting');
await page.getByLabel('Username').fill('owner'); await page.getByLabel('Password').fill('correct-password'); await page.getByRole('button', { name: 'Sign in' }).click();
await page.getByRole('navigation', { name: 'Main' }).waitFor();
await page.goto(BASE + '#/meetings/uat-meeting');
await page.getByRole('button', { name: 'Documents' }).click();
// 1. attach by uploading the PDF export; a PPTX is refused first
await page.getByLabel('Upload a document').setInputFiles({ name: 'deck.pptx', mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', buffer: Buffer.from('x') });
await page.getByRole('button', { name: 'Upload and attach' }).click();
note('pptx_refused', await page.getByText(/Export the presentation as a PDF/).isVisible());
await page.getByLabel('Upload a document').setInputFiles(`${SP}/deck.pdf`);
await page.getByRole('button', { name: 'Upload and attach' }).click();
const list = page.getByRole('list', { name: 'Attached documents list' });
await list.getByText('deck').first().waitFor({ timeout: 30000 });
const t0 = Date.now();
await list.getByText('Ready').waitFor({ timeout: 120000 });
note('document_ready_s', (Date.now() - t0) / 1000);
note('attached_text', (await list.innerText()).replace(/\s+/g, ' '));
await page.screenshot({ path: `${SP}/shots/1-attached.png` });
// 2. estimate with progress
const t1 = Date.now();
await page.getByRole('button', { name: 'Estimate the pages' }).click();
const prog = page.getByRole('status', { name: 'Estimating the pages progress' });
await prog.waitFor({ timeout: 10000 });
note('progress_text', await prog.innerText());
await page.screenshot({ path: `${SP}/shots/2-progress.png` });
await page.getByText('Pages: Done').waitFor({ timeout: 180000 });
note('estimate_s', (Date.now() - t1) / 1000);
note('summary', await page.getByLabel('Page estimates').innerText());
await page.screenshot({ path: `${SP}/shots/3-estimated.png`, fullPage: true });
// 3. transcript cards
await page.getByRole('button', { name: 'Transcript' }).click();
await page.getByText(/Suggested pages are estimates/).waitFor();
const cards = await page.locator('[data-window]').evaluateAll((els) => els.map((e) => ({ low: e.getAttribute('data-certainty') === 'low', text: e.textContent.replace(/\s+/g, ' ').slice(0, 110) })));
note('cards', cards.length); note('card_kinds', { low: cards.filter((c) => c.low).length, none: cards.filter((c) => /No confident|Not checked/.test(c.text)).length, boxed: cards.filter((c) => /Certainty:/.test(c.text)).length });
await page.screenshot({ path: `${SP}/shots/4-transcript.png`, fullPage: false });
// 4. one boxed card: details, thumbnail, open the page
const boxed = page.locator('[data-window]', { hasText: 'Certainty:' }).first();
await boxed.getByRole('button', { name: /^Details for slide/ }).click();
await page.waitForTimeout(1500);
note('thumbnail', await boxed.locator('img').count());
note('details', (await boxed.innerText()).replace(/\s+/g, ' ').slice(0, 400));
await page.screenshot({ path: `${SP}/shots/5-details.png` });
const shownPage = (await boxed.innerText()).match(/slide (\d+)/i)?.[1];
await boxed.getByRole('link', { name: 'Open the page' }).click();
await page.getByLabel('Extraction inspector').waitFor({ timeout: 30000 });
await page.waitForTimeout(1500);
note('inspector_page_input', await page.getByLabel('Page', { exact: false }).first().inputValue().catch(() => 'n/a'));
note('expected_page', shownPage);
note('inspector_image', await page.locator('img').count());
await page.screenshot({ path: `${SP}/shots/6-inspector.png` });
await page.goBack();
await page.getByRole('button', { name: 'Transcript' }).click().catch(() => {});
// 5. corrections persist across a reload
const first = page.locator('[data-window]', { hasText: 'Certainty:' }).first();
await first.getByRole('button', { name: /^Details for slide/ }).click();
await first.getByRole('button', { name: 'Confirm', exact: true }).click();
await page.waitForTimeout(1200);
note('after_confirm', (await first.innerText()).replace(/\s+/g, ' ').slice(0, 120));
const second = page.locator('[data-window]', { hasText: 'Certainty:' }).nth(1);
if (await second.count()) {
  await second.getByRole('button', { name: /^Details for slide/ }).click();
  await second.getByRole('button', { name: 'Not about a slide' }).click();
  await page.waitForTimeout(1200);
}
await page.reload();
await page.getByRole('button', { name: 'Transcript' }).click();
await page.getByText(/Suggested pages are estimates/).waitFor();
note('after_reload', { confirmed: await page.getByText('Confirmed by you').count(), notSlide: await page.getByText(/Marked by you as not about a slide/).count() });
await page.screenshot({ path: `${SP}/shots/7-corrected.png` });
// 6. combined Q&A
await page.getByRole('button', { name: 'Documents' }).click();
await page.getByLabel('Question').fill('What was said about the DHCP pools and what does the deck say about them?');
const tq = Date.now();
await page.getByRole('button', { name: 'Ask', exact: true }).click();
const ans = page.getByLabel('Answer');
await ans.waitFor({ timeout: 120000 });
note('qa_s', (Date.now() - tq) / 1000);
note('answer', (await ans.innerText()).replace(/\s+/g, ' ').slice(0, 700));
note('answer_links', await ans.locator('a, button').evaluateAll((els) => els.map((e) => e.textContent + (e.getAttribute('href') ? ' -> ' + e.getAttribute('href') : ''))));
await page.screenshot({ path: `${SP}/shots/8-answer.png`, fullPage: true });
// citation navigation: the transcript citation switches to the transcript tab and seeks
const tbtn = ans.getByRole('button', { name: /transcript/ }).first();
if (await tbtn.count()) { await tbtn.click(); await page.waitForTimeout(800); note('after_transcript_citation_tab_has_transcript', await page.getByText(/Suggested pages are estimates/).isVisible()); }
await page.getByRole('button', { name: 'Documents' }).click();
// 7. analysis: double click, progress, completion
const ta = Date.now();
const btn = page.getByRole('button', { name: 'Analyse with documents' });
await btn.dblclick();
await page.getByRole('status', { name: 'Analysing with the documents progress' }).waitFor({ timeout: 15000 });
note('analysis_button_disabled_while_running', await btn.isDisabled());
await page.waitForTimeout(8000);
note('analysis_progress_text', await page.getByRole('status', { name: 'Analysing with the documents progress' }).innerText());
await page.screenshot({ path: `${SP}/shots/9-analysis-progress.png` });
await page.getByText('Analysis: Done').waitFor({ timeout: 400000 });
note('analysis_s', (Date.now() - ta) / 1000);
note('partial_notes', await page.getByText(/Partial result/).allInnerTexts());
note('finding_headings', await page.getByLabel('Combined findings').locator('h4').allInnerTexts());
await page.screenshot({ path: `${SP}/shots/10-findings.png`, fullPage: true });
note('analysis_posts', posts.filter((p) => /multimodal\/analysis$/.test(p)).length);
note('accept_or_dismiss_posts_before_any_click', posts.filter((p) => /accept|dismiss/.test(p)).length);
note('tasks_after_analysis', await page.evaluate(async () => (await (await fetch('/planner/tasks')).json()).length));
note('localStorage_keys', await page.evaluate(() => Object.keys(localStorage)));
note('all_mutating_requests', [...new Set(posts)]);
await browser.close();
import fs from 'node:fs'; fs.writeFileSync(`${SP}/uat1.json`, JSON.stringify(log, null, 1));
