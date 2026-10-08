import { expect, test, type Page } from '@playwright/test';
import { HUB_PORT, PROXY_PORT } from './global';

// Phase 47B against the real hub (in-memory stores): To Do, Reminders, Notes, Activity at both mounts and widths.
const MOUNTS = [
  { name: 'direct /web/', url: `http://127.0.0.1:${HUB_PORT}/web/` },
  { name: 'proxied /hub/web/', url: `http://127.0.0.1:${PROXY_PORT}/hub/web/` },
];
const run = Date.now().toString(36); // the hub keeps state across tests; every record name carries this

async function signIn(page: Page, url: string, hash = '') {
  await page.goto(url + hash);
  // The browser context may already hold the owner session (the legacy UI shares the cookie), so wait for
  // whichever the app settles on before acting.
  const loginHeading = page.getByRole('heading', { name: 'Sign in to Reachy' });
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(loginHeading.or(nav)).toBeVisible();
  if (await loginHeading.isVisible()) {
    await page.getByLabel('Username').fill('owner');
    await page.getByLabel('Password').fill('correct-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
  }
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
  if (hash) await page.goto(url + hash);
}

for (const mount of MOUNTS) {
  test.describe(`planner · ${mount.name}`, () => {
    test('To Do: add, persist across reload, complete, reopen, rename, delete; text stays literal', async ({ page }) => {
      const text = `<b>task ${run}</b>`;
      await signIn(page, mount.url, '#/todo');
      await expect(page.getByRole('heading', { name: 'To Do' })).toBeVisible();
      await page.getByRole('button', { name: /New Reminder/ }).click();
      await page.getByRole('textbox', { name: 'New to-do' }).fill(text);
      await page.keyboard.press('Enter');
      await page.keyboard.press('Escape');
      await expect(page.getByText(text, { exact: true })).toBeVisible();
      expect(await page.locator('b').count()).toBe(0);

      await page.reload();
      await expect(page.getByText(text, { exact: true })).toBeVisible();

      await page.getByRole('checkbox', { name: `Complete: ${text}` }).click();
      await expect(page.getByText(text, { exact: true })).toHaveCount(0);
      await page.getByRole('button', { name: /\d+ Completed · Show/ }).click();
      await expect(page.getByText(text, { exact: true })).toBeVisible();
      await page.getByRole('checkbox', { name: `Reopen: ${text}` }).click();
      await expect(page.getByRole('checkbox', { name: `Complete: ${text}` })).toBeVisible();

      await page.getByRole('button', { name: `Edit: ${text}` }).click();
      await page.getByRole('textbox', { name: 'Edit to-do' }).fill(`renamed ${run}`);
      await page.keyboard.press('Enter');
      await expect(page.getByText(`renamed ${run}`, { exact: true })).toBeVisible();

      await page.getByRole('button', { name: `Delete: renamed ${run}` }).click();
      await expect(page.getByText(`renamed ${run}`, { exact: true })).toHaveCount(0);
      expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
    });

    test('Reminders: new reminder sheet, due text, complete (stays ticked), delete', async ({ page }) => {
      const text = `call ${run}`;
      await signIn(page, mount.url, '#/reminders');
      await page.getByRole('button', { name: /New Reminder/ }).click();
      const sheet = page.getByRole('dialog', { name: 'New Reminder' });
      await sheet.getByLabel('Title').fill(text);
      await sheet.getByLabel('Date').fill('2031-05-06');
      await sheet.getByLabel('Time').fill('17:30');
      await sheet.getByRole('button', { name: 'Add' }).click();
      const row = page.getByRole('listitem').filter({ hasText: text });
      await expect(row).toBeVisible();
      await expect(row).toContainText(/5\/6\/31|6\/5\/31|06\/05\/2031|05\/06\/2031|2031/); // locale short date
      await expect(row).toContainText(/5:30\s?PM/);
      await page.reload();
      await expect(row).toBeVisible();

      await page.getByRole('checkbox', { name: `Complete: ${text}` }).click();
      await expect(row).toHaveCount(0);
      await page.getByRole('button', { name: /\d+ Completed · Show/ }).click();
      const done = page.getByRole('checkbox', { name: `Completed: ${text}` });
      await expect(done).toBeChecked();
      await expect(done).toBeDisabled(); // the hub cannot reopen a reminder
      await page.getByRole('button', { name: `Delete: ${text}` }).click();
      await expect(page.getByText(text)).toHaveCount(0);
    });

    test('Notes: create autosaves, survives reload, is searchable, edits, and deletes after confirmation', async ({ page }) => {
      const title = `<i>note ${run}</i>`;
      await signIn(page, mount.url, '#/notes');
      await page.getByRole('button', { name: 'New note' }).click();
      await page.getByLabel('Title').fill(title);
      await page.getByRole('textbox', { name: 'Note' }).fill('first line\nsecond line');
      await expect(page.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible({ timeout: 5000 });
      expect(await page.locator('i').count()).toBe(0);

      await page.reload();
      const rowButton = page.getByRole('button', { name: new RegExp(`note ${run}`) });
      await expect(rowButton).toBeVisible();

      await page.getByLabel('Search all notes').fill(`zzz-none-${run}`);
      await expect(page.getByText('No notes.')).toBeVisible();
      await page.getByLabel('Search all notes').fill(`second line`);
      await expect(rowButton).toBeVisible();
      await page.getByLabel('Search all notes').fill('');

      await rowButton.click();
      await page.getByRole('textbox', { name: 'Note' }).fill('first line\nsecond line\nthird');
      await expect(page.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible({ timeout: 5000 });
      await page.reload();
      await rowButton.click();
      await expect(page.getByRole('textbox', { name: 'Note' })).toHaveValue('first line\nsecond line\nthird');

      await page.getByRole('button', { name: 'Delete note' }).click();
      const dialog = page.getByRole('dialog');
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      await expect(page.getByRole('button', { name: new RegExp(`note ${run}`), includeHidden: true })).toBeAttached(); // on a narrow screen the list is hidden behind the open editor
      await expect(page.getByRole('textbox', { name: 'Note' })).toHaveValue('first line\nsecond line\nthird');
      await page.getByRole('button', { name: 'Delete note' }).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click();
      await expect(rowButton).toHaveCount(0);
    });

    test('Alarms: add with repeat, sound and volume; switch off; edit; Stop reports nothing playing; delete', async ({ page }) => {
      const label = `alarm ${run}`;
      await signIn(page, mount.url, '#/alarms');
      await expect(page.getByRole('heading', { name: 'Alarms', level: 2 }).first()).toBeVisible();
      await page.getByRole('button', { name: 'Add alarm' }).click();
      const sheet = page.getByRole('dialog', { name: 'Add Alarm' });
      await sheet.getByLabel('Hour').selectOption('6');
      await sheet.getByLabel('Minute').selectOption('45');
      await sheet.getByLabel('AM or PM').selectOption('AM');
      await sheet.getByRole('button', { name: 'Mon' }).click();
      await sheet.getByRole('button', { name: 'Fri' }).click();
      await sheet.getByLabel('Label').fill(label);
      await sheet.getByLabel('Sound').selectOption({ label: 'SWR3' });
      await sheet.getByRole('button', { name: 'Save' }).click();
      // The hub reads 06:45 in the assistant's time zone and this screen shows the device's, so match the label, not the hour.
      const toggle = page.getByRole('switch', { name: new RegExp(`${label} \\d+:45`) });
      await expect(toggle).toBeChecked();
      const row = page.getByRole('listitem').filter({ has: toggle });
      await expect(row).toContainText(`${label}, Mon, Fri`);
      await expect(row).toContainText('SWR3');

      await page.reload();
      await expect(toggle).toBeChecked();
      await toggle.click();
      await expect(toggle).not.toBeChecked();

      await row.getByRole('button').first().click();
      const edit = page.getByRole('dialog', { name: 'Edit Alarm' });
      await expect(edit.getByLabel('Minute')).toHaveValue('45');
      await edit.getByLabel('Minute').selectOption('50');
      await edit.getByRole('button', { name: 'Save' }).click();
      await expect(page.getByRole('switch', { name: new RegExp(`${label} \\d+:50`) })).toBeVisible();

      await page.getByRole('button', { name: 'Stop alarm' }).click();
      await expect(page.getByText('No alarm is playing.')).toBeVisible();

      await page.getByRole('button', { name: 'Edit', exact: true }).click();
      await page.getByRole('button', { name: `Delete alarm ${label}` }).click();
      await expect(page.getByText(label)).toHaveCount(0);
    });

    test('Chat: owner-bound (no user form), send, reply, saved record reopens, delete after confirmation', async ({ page }) => {
      const question = 'what time is it'; // the hub answers a clock question itself, so no model is involved
      await signIn(page, mount.url, '#/chat');
      await expect(page.getByLabel('User ID')).toHaveCount(0);
      await expect(page.getByText(/User: default-user/)).toBeVisible();
      await page.getByRole('button', { name: /New chat record/ }).click();
      await page.getByRole('textbox', { name: 'Message' }).fill(question);
      await page.getByRole('button', { name: 'Send' }).click();
      await expect(page.getByRole('log').getByText(question)).toBeVisible();
      await expect(page.getByRole('log').locator('article').nth(1)).toContainText(/\d+:\d+/);
      await expect(page.getByText(/Active channel: web/)).toBeVisible();

      await page.reload();
      // The newest saved chat reopens by itself.
      await expect(page.getByRole('log').getByText(question)).toBeVisible();
      await page.getByRole('button', { name: `Delete chat: ${question}` }).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click();
      await expect(page.getByRole('button', { name: `Delete chat: ${question}` })).toBeVisible();
      await page.getByRole('button', { name: `Delete chat: ${question}` }).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click();
      await expect(page.getByRole('button', { name: `Delete chat: ${question}` })).toHaveCount(0);
      expect(await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage))).toBe('{}{}');
    });

    test('a reply requested before logout is cancelled and never shown', async ({ page }) => {
      const question = `slow question ${run}`;
      let release!: () => void;
      const gate = new Promise<void>((resolve) => { release = resolve; });
      let cancelled = false;
      page.on('requestfailed', (request) => { if (request.url().endsWith('/messages')) cancelled = true; });
      await signIn(page, mount.url, '#/chat');
      await page.route('**/messages', async (route) => {
        await gate;
        await route.fulfill({ json: { reply: `SECRET-REPLY-${run}`, web_search: null, context_meeting: null } }).catch(() => undefined);
      });
      await page.getByRole('button', { name: /New chat record/ }).click();
      await page.getByRole('textbox', { name: 'Message' }).fill(question);
      await page.getByRole('button', { name: 'Send' }).click();
      await expect(page.getByRole('log').getByText(question)).toBeVisible();
      await page.getByRole('button', { name: 'Log out' }).click();
      await expect(page.getByRole('heading', { name: 'Sign in to Reachy' })).toBeVisible();
      release();
      await page.waitForTimeout(300);
      await expect(page.getByText(`SECRET-REPLY-${run}`)).toHaveCount(0);
      await expect(page.getByText(question)).toHaveCount(0);
      expect(cancelled).toBe(true);
    });

    test('Meetings: seeded recording opens with speakers, edits persist, recording streams, summary reports no model', async ({ page }) => {
      await signIn(page, mount.url, '#/meetings');
      const seeded = page.getByRole('listitem').filter({ hasText: 'Weekly sync' });
      await expect(seeded).toBeVisible();
      await seeded.getByRole('link', { name: 'View details' }).click();
      await expect(page.getByText(/Status: Complete · Project: apollo/)).toBeVisible();
      await expect(page.getByText(/0:00–0:03\s+hello gemini/)).toBeVisible();
      await expect(page.getByText(/no audio — the phone stopped capturing sound/)).toBeVisible();

      // The recording streams from the hub behind the owner cookie, with byte ranges.
      const audio = await page.evaluate(async () => {
        const src = document.querySelector('audio')!.getAttribute('src')!;
        const r = await fetch(src, { headers: { Range: 'bytes=0-3' }, credentials: 'same-origin' });
        return { status: r.status, bytes: (await r.arrayBuffer()).byteLength };
      });
      expect(audio).toEqual({ status: 206, bytes: 4 });

      const name = `Speaker ${run}`;
      await page.getByRole('button', { name: 'Rename Speaker 1' }).click();
      const dialog = page.getByRole('dialog', { name: 'Name this speaker' });
      await dialog.getByLabel('Name').fill(name);
      await dialog.getByRole('button', { name: 'Save' }).click();
      await expect(page.getByRole('button', { name: `Rename ${name}` })).toBeVisible();

      await page.getByRole('button', { name: 'Edit line at 0:00' }).click();
      const line = page.getByRole('dialog', { name: 'Edit line' });
      await line.getByLabel('Text').fill(`hello Gemini ${run}`);
      await line.getByRole('button', { name: 'Save' }).click();
      await expect(page.getByText(new RegExp(`hello Gemini ${run}\\s+\\(edited\\)`))).toBeVisible();

      await page.reload();
      await expect(page.getByRole('button', { name: `Rename ${name}` })).toBeVisible();
      await expect(page.getByText(new RegExp(`hello Gemini ${run}\\s+\\(edited\\)`))).toBeVisible();

      // Put the seed back: the hub keeps state for the later tests.
      await page.getByRole('button', { name: 'Edit line at 0:00' }).click();
      await page.getByRole('dialog', { name: 'Edit line' }).getByRole('button', { name: 'Restore original' }).click();
      await page.getByRole('button', { name: `Rename ${name}` }).click();
      await page.getByRole('dialog', { name: 'Name this speaker' }).getByRole('button', { name: 'Clear name' }).click();
      await expect(page.getByRole('button', { name: 'Rename Speaker 1' })).toBeVisible();

      // No model is configured on a test hub: the hub says so plainly, nothing is invented.
      await page.getByRole('button', { name: 'Minutes' }).click();
      await expect(page.getByText('the language model is unavailable right now')).toBeVisible();
    });

    test('Meetings: upload a file, cancel it while queued, then delete it after confirmation', async ({ page }) => {
      const title = `Standup ${run}`;
      await signIn(page, mount.url, '#/meetings');
      await page.getByLabel('Title').fill(title);
      await page.getByLabel(/Participants/).fill('Hariz, Alice');
      await page.getByLabel(/Recording file/).setInputFiles({ name: 'meeting.wav', mimeType: 'audio/wav', buffer: Buffer.from('RIFF....WAVEfmt ') });
      await page.getByRole('button', { name: 'Upload meeting' }).click();
      await expect(page.getByText('Uploaded.')).toBeVisible();
      const item = page.getByRole('listitem').filter({ hasText: title });
      await expect(item).toContainText('Queued');
      await expect(item.getByRole('button', { name: `Delete ${title}` })).toHaveCount(0); // not while it is queued
      await item.getByRole('button', { name: 'Cancel processing' }).click();
      await expect(item).toContainText('Cancelled');
      await item.getByRole('button', { name: `Delete ${title}` }).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click();
      await expect(item).toBeVisible();
      await item.getByRole('button', { name: `Delete ${title}` }).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click();
      await expect(page.getByText(title)).toHaveCount(0);
    });

    test('Meetings: a clip recorded in the browser uploads', async ({ page }) => {
      const title = `Voice memo ${run}`;
      await signIn(page, mount.url, '#/meetings');
      await page.getByRole('button', { name: 'Start recording' }).click();
      await expect(page.getByText(/Recording… \d+:\d\d/)).toBeVisible();
      await page.waitForTimeout(1200);
      await page.getByRole('button', { name: 'Stop recording' }).click();
      await expect(page.getByText(/Recorded clip ready/)).toBeVisible();
      await page.getByLabel('Title').fill(title);
      await page.getByRole('button', { name: 'Upload meeting' }).click();
      await expect(page.getByText('Uploaded.')).toBeVisible();
      const item = page.getByRole('listitem').filter({ hasText: title });
      await expect(item).toBeVisible();
      await item.getByRole('button', { name: 'Cancel processing' }).click();
      await item.getByRole('button', { name: `Delete ${title}` }).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click();
      await expect(page.getByText(title)).toHaveCount(0);
    });

    test('Settings: persona saves; a model key is shown only masked; secrets are not left in the page or storage', async ({ page }) => {
      await signIn(page, mount.url, '#/settings');
      await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
      await page.getByLabel('Location').fill(`Lab ${run}`);
      await page.getByRole('button', { name: 'Save persona' }).click();
      await expect(page.getByText('Persona saved.')).toBeVisible();
      await page.reload();
      await expect(page.getByLabel('Location')).toHaveValue(`Lab ${run}`);
      await page.getByLabel('Location').fill('');
      await page.getByRole('button', { name: 'Save persona' }).click();
      await expect(page.getByText('Persona saved.')).toBeVisible();

      await page.getByRole('tab', { name: 'Models' }).click();
      await page.getByLabel('Base URL', { exact: true }).fill('http://ovms.test/v1');
      await page.getByLabel('Model name').fill('qwen');
      const secret = `secret-${run}-4242`;
      await page.getByLabel('API key').first().fill(secret);
      await page.getByRole('button', { name: 'Save model' }).click();
      await expect(page.getByText('Model settings saved.')).toBeVisible();
      await expect(page.getByText('Saved key: ********4242')).toBeVisible();
      expect(await page.content()).not.toContain(secret);
      expect(await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage))).toBe('{}{}');
      await page.getByLabel('API key').first().fill('typed-and-abandoned');
      await page.getByRole('button', { name: 'Log out' }).click();
      await expect(page.getByRole('heading', { name: 'Sign in to Reachy' })).toBeVisible();
      expect(await page.content()).not.toContain('typed-and-abandoned');
    });

    test('Voice & motion: the offline robot cannot be started; animation switches apply and are restored (simulated robot)', async ({ page }) => {
      await signIn(page, mount.url, '#/settings/voice');
      await expect(page.getByText('Off', { exact: true })).toBeVisible();
      await expect(page.getByRole('option', { name: 'desk (offline)' })).toBeAttached();
      await expect(page.getByRole('button', { name: 'Start listening' })).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Stop' })).toBeDisabled();
      await expect(page.getByText('Privacy mode on: not listening for “Hey Reachy”')).toBeVisible();

      const gestures = page.getByRole('checkbox', { name: 'Listening and thinking gestures' });
      await expect(gestures).toBeEnabled();
      await gestures.click();
      await page.getByRole('button', { name: 'Apply animation settings' }).click();
      await expect(page.getByText('Animation settings applied for the next conversation.')).toBeVisible();
      await page.reload();
      await expect(gestures).toBeChecked();
      await gestures.click(); // restore the simulated robot's default
      await page.getByRole('button', { name: 'Apply animation settings' }).click();
      await expect(page.getByText('Animation settings applied for the next conversation.')).toBeVisible();
      await expect(gestures).not.toBeChecked();
    });

    test('Owner recognition: needs the password again; a wrong one does not sign out; a voice sample records, exports and deletes', async ({ page }) => {
      await signIn(page, mount.url, '#/settings/recognition');
      await expect(page.getByText('Confirm your password to change benchmark collection or manage samples.')).toBeVisible();
      await expect(page.getByRole('checkbox', { name: 'Enable benchmark dataset collection' })).toBeDisabled();
      await page.getByLabel('Password').fill('not-the-password');
      await page.getByRole('button', { name: 'Confirm password' }).click();
      await expect(page.getByText('Invalid password')).toBeVisible();
      await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible(); // still signed in

      await page.getByLabel('Password').fill('correct-password');
      await page.getByRole('button', { name: 'Confirm password' }).click();
      await expect(page.getByText(/Password confirmed — expires in about \d+ minute/)).toBeVisible();
      await page.getByRole('checkbox', { name: 'Enable benchmark dataset collection' }).click();
      await expect(page.getByText(/Benchmark dataset collection is on/)).toBeVisible();

      await page.getByRole('button', { name: 'Start recording' }).click();
      await expect(page.getByRole('button', { name: 'Stop recording' })).toBeVisible();
      await page.waitForTimeout(1200);
      await page.getByRole('button', { name: 'Stop recording' }).click();
      await expect(page.getByText('Voice sample saved.')).toBeVisible();
      await expect(page.getByText(/\d+ sample\(s\), .+ total/)).toBeVisible();

      const download = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Export voice dataset' }).click();
      expect((await download).suggestedFilename()).toBe('voice-benchmark-dataset.zip');

      await page.getByRole('button', { name: 'Delete all voice samples' }).click();
      await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click();
      await expect(page.getByText('No samples recorded yet.').first()).toBeVisible();
      await page.getByRole('checkbox', { name: 'Enable benchmark dataset collection' }).click(); // leave the dataset switched off
      await expect(page.getByText(/Off by default/)).toBeVisible();
    });

    test('Activity: shows the hub receipts, failed ones struck through, text literal', async ({ page }) => {
      await signIn(page, mount.url, '#/activity');
      await expect(page.getByRole('heading', { name: 'Recent activity' })).toBeVisible();
      await expect(page.getByText('Task · created')).toBeVisible();
      await expect(page.getByText('Alarm · delivered')).toHaveClass(/line-through/);
      await expect(page.getByText(/failed: no audio/)).toBeVisible();
      await expect(page.getByRole('alert')).toHaveCount(0);
    });

    test('a list requested before logout is cancelled and its late answer never reaches the page', async ({ page }) => {
      const secret = `SECRET-${run}`;
      let release!: () => void;
      const gate = new Promise<void>((resolve) => { release = resolve; });
      let cancelled = false;
      page.on('requestfailed', (request) => { if (request.url().endsWith('/planner/tasks')) cancelled = true; });
      await signIn(page, mount.url);
      await page.route('**/planner/tasks', async (route) => {
        await gate;
        // The browser has already abandoned this request; answering is harmless and must not matter.
        await route.fulfill({ json: [{ id: 'z', text: secret, status: 'open' }] }).catch(() => undefined);
      });
      await page.getByRole('link', { name: 'To Do' }).click();
      await page.getByRole('button', { name: 'Log out' }).click();
      await expect(page.getByRole('heading', { name: 'Sign in to Reachy' })).toBeVisible();
      release();
      await page.waitForTimeout(300);
      await expect(page.getByRole('heading', { name: 'Sign in to Reachy' })).toBeVisible();
      await expect(page.getByText(secret)).toHaveCount(0);
      expect(cancelled).toBe(true);
      await page.goBack();
      await expect(page.getByText(secret)).toHaveCount(0);
      await expect(page.getByRole('heading', { name: 'Sign in to Reachy' })).toBeVisible();
    });

    test('pages fit the viewport; Notes works as list then editor then back on a narrow screen', async ({ page }, info) => {
      await signIn(page, mount.url);
      for (const hash of ['#/todo', '#/reminders', '#/notes', '#/activity', '#/alarms', '#/chat', '#/meetings', '#/settings/models', '#/settings/search', '#/settings/voice', '#/settings/accounts', '#/settings/recognition']) {
        await page.goto(mount.url + hash);
        await expect(page.getByRole('button', { name: 'Log out' })).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
      }
      if (info.project.name === 'mobile') {
        const title = `mobile ${run}`;
        await page.goto(mount.url + '#/notes');
        await page.getByRole('button', { name: 'New note' }).click();
        await expect(page.getByLabel('Search all notes')).toBeHidden(); // editor replaces the list
        await page.getByLabel('Title').fill(title);
        await page.getByRole('textbox', { name: 'Note' }).fill('x');
        await expect(page.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible({ timeout: 5000 });
        await page.getByRole('button', { name: '‹ Notes' }).click();
        await expect(page.getByRole('button', { name: new RegExp(title) })).toBeVisible();
        await page.getByRole('button', { name: new RegExp(title) }).click();
        await page.getByRole('button', { name: 'Delete note' }).click();
        await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click();
        await expect(page.getByRole('button', { name: new RegExp(title) })).toHaveCount(0);
      }
    });
  });
}

// Parity with the legacy operator UI: both clients talk to the same hub, so what one writes the other must show.
test.describe('parity with the legacy UI (/ui/)', () => {
  const direct = `http://127.0.0.1:${HUB_PORT}`;

  async function legacyLogin(page: Page) {
    await page.goto(`${direct}/ui/`);
    // Already signed in when the same browser context used the React client first (one shared cookie).
    if (await page.locator('#username').isVisible()) {
      await page.locator('#username').fill('owner');
      await page.locator('#password').fill('correct-password');
      await page.getByRole('button', { name: 'Log in' }).click();
    }
    await page.locator('#todo-tab').waitFor();
  }

  test('a task written in the legacy UI shows in the React To Do, and the reverse', async ({ page }) => {
    const legacy = `legacy task ${run}`, modern = `react task ${run}`;
    await legacyLogin(page);
    await page.locator('#todo-tab').click();
    await page.locator('#planner-task-new').click();
    await page.locator('#planner-task-list .rl-new-row .rl-edit').fill(legacy);
    await page.keyboard.press('Enter');
    await expect(page.locator('#planner-task-list .rl-text', { hasText: legacy })).toBeVisible();

    await signIn(page, `${direct}/web/`, '#/todo');
    await expect(page.getByText(legacy, { exact: true })).toBeVisible();
    await page.getByRole('button', { name: /New Reminder/ }).click();
    await page.getByRole('textbox', { name: 'New to-do' }).fill(modern);
    await page.keyboard.press('Enter');
    await expect(page.getByText(modern, { exact: true })).toBeVisible();

    await legacyLogin(page);
    await page.locator('#todo-tab').click();
    await expect(page.locator('#planner-task-list .rl-text', { hasText: modern })).toBeVisible();
    // tidy up through the legacy delete buttons
    for (const t of [legacy, modern]) await page.locator('#planner-task-list .rl-row', { hasText: t }).locator('.rl-delete').click();
  });

  test('a reminder shows the same due text in both clients', async ({ page }) => {
    const text = `parity reminder ${run}`;
    await signIn(page, `${direct}/web/`, '#/reminders');
    await page.getByRole('button', { name: /New Reminder/ }).click();
    const sheet = page.getByRole('dialog', { name: 'New Reminder' });
    await sheet.getByLabel('Title').fill(text);
    await sheet.getByLabel('Date').fill('2031-07-08');
    await sheet.getByLabel('Time').fill('09:15');
    await sheet.getByRole('button', { name: 'Add' }).click();
    const modernSub = (await page.getByRole('listitem').filter({ hasText: text }).innerText()).split('\n').find((l) => /9:15/.test(l));

    await legacyLogin(page);
    await page.locator('#reminders-tab').click();
    const legacyRow = page.locator('#planner-reminder-list .rl-row', { hasText: text });
    await expect(legacyRow).toBeVisible();
    expect((await legacyRow.locator('.rl-sub').innerText()).trim()).toBe((modernSub ?? '').trim());
    await legacyRow.locator('.rl-delete').click();
  });

  test('a note written in React opens in the legacy Notes tab with the same title and text', async ({ page }) => {
    const title = `parity note ${run}`;
    await signIn(page, `${direct}/web/`, '#/notes');
    await page.getByRole('button', { name: 'New note' }).click();
    await page.getByLabel('Title').fill(title);
    await page.getByRole('textbox', { name: 'Note' }).fill('shared body\nline two');
    await expect(page.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible({ timeout: 5000 });

    await legacyLogin(page);
    await page.locator('#notes-tab').click();
    await page.locator('#notes-list .notes-row', { hasText: title }).click();
    expect(await page.inputValue('#notes-title')).toBe(title);
    expect(await page.inputValue('#notes-body')).toBe('shared body\nline two');
    await page.locator('#notes-delete').click();
    await page.locator('#confirm-ok').click();
    await expect(page.locator('#notes-list .notes-row', { hasText: title })).toHaveCount(0);
  });
});
