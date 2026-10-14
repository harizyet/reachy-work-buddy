import { expect, test, type Page } from '@playwright/test';
import { EMAIL_PORT } from './global';

// Phase 55 in a real browser: a signed-in owner, the production build, the real hub in front of a REAL companion-core with the real sender and dispatch loop. The mail server is a
// capturing SMTP fixture (meeting_email_hub_server.py), so what the browser approved can be compared with the bytes that were actually transmitted. Disposable, in memory.
const URL_ = `http://127.0.0.1:${EMAIL_PORT}/web/`;
type Mail = { subject: string; to: string; cc: string | null; headers: string; rcpts: string[]; body: string; attachments: { filename: string; type: string; sha256: string; size: number }[] };

async function openShare(page: Page) {
  await page.goto(URL_ + '#/meetings');
  const loginHeading = page.getByRole('heading', { name: 'Sign in to Reachy' });
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(loginHeading.or(nav)).toBeVisible();
  if (await loginHeading.isVisible()) {
    await page.getByLabel('Username').fill('owner');
    await page.getByLabel('Password').fill('correct-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
  }
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
  const id = await page.evaluate(async () => ((await (await fetch('/meetings')).json()) as { id: string; title: string }[]).find((m) => m.title === 'Weekly sync')!.id);
  await page.goto(`${URL_}#/meetings/${id}`);
  await page.getByRole('button', { name: 'Share minutes' }).click();
  return id;
}
const mail = (page: Page) => page.evaluate(async () => (await (await fetch('/__mail')).json()) as Mail[]);

async function prepareWithRecipient(page: Page) {
  await page.getByRole('button', { name: 'Prepare message' }).click();
  const review = page.getByRole('region', { name: 'What will be sent' });
  await expect(review).toBeVisible();
  await page.getByLabel('To (one address per line)').fill('Owner.Test.Inbox@example.org');
  await page.getByLabel('Cc', { exact: true }).fill('cc.person@example.org');
  await page.getByLabel('Bcc (hidden from the other recipients)').fill('hidden.person@example.org');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(review.getByText('To: owner.test.inbox@example.org')).toBeVisible();
  return review;
}

test('prepare, review, approve by typing SEND, and the delivered message matches what was approved', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop');
  await openShare(page);
  expect(await mail(page)).toEqual([]); // nothing is sent by preparing or reviewing
  const review = await prepareWithRecipient(page);
  await expect(review.getByText(/Attachment: Weekly-sync-minutes-2026-10-14\.pdf/)).toBeVisible();
  await expect(page.getByText('Priya Shah proposed shipping on Friday')).toBeVisible();

  // The preview is the very PDF that will be sent: real bytes through the hub with the owner cookie.
  const href = await review.getByRole('link', { name: 'Preview PDF' }).getAttribute('href');
  const preview = await page.evaluate(async (h) => {
    const r = await fetch(h!);
    const b = new Uint8Array(await r.arrayBuffer());
    return { status: r.status, type: r.headers.get('content-type'), head: String.fromCharCode(...b.slice(0, 5)), size: b.length, nosniff: r.headers.get('x-content-type-options') };
  }, href);
  expect(preview).toMatchObject({ status: 200, type: 'application/pdf', head: '%PDF-', nosniff: 'nosniff' });

  await page.getByLabel('Type SEND to approve').fill('SEND');
  await page.getByRole('button', { name: 'Approve and queue' }).click();
  await expect(page.getByText(/Queued\. It will be sent at .* unless you cancel\./)).toBeVisible();
  expect(await mail(page)).toEqual([]); // still inside the undo window

  await expect(page.getByRole('status', { name: 'Message status' })).toHaveText('Sent', { timeout: 30000 });
  const [delivered] = await mail(page);
  expect(delivered!.subject).toBe('Meeting minutes: Weekly sync');
  expect(delivered!.rcpts.sort()).toEqual(['cc.person@example.org', 'hidden.person@example.org', 'owner.test.inbox@example.org']);
  expect(delivered!.to).toBe('owner.test.inbox@example.org');
  expect(delivered!.cc).toBe('cc.person@example.org');
  expect(delivered!.headers).not.toContain('hidden.person@example.org'); // Bcc is an envelope recipient only
  expect(delivered!.body).toContain('Priya Shah proposed shipping on Friday');
  expect(delivered!.body + delivered!.attachments.map((a) => a.filename).join()).not.toContain('SECRET-TRANSCRIPT-LINE');
  expect(delivered!.attachments).toHaveLength(1);
  expect(delivered!.attachments[0]).toMatchObject({ filename: 'Weekly-sync-minutes-2026-10-14.pdf', type: 'application/pdf' });
  // The attachment fingerprint the owner saw on screen is the one that was delivered.
  const shown = await review.getByText(/fingerprint [0-9a-f]{12}/).textContent();
  expect(delivered!.attachments[0]!.sha256.startsWith(/fingerprint ([0-9a-f]{12})/.exec(shown!)![1]!)).toBe(true);
  await expect(page.getByText('History').locator('xpath=following-sibling::ul')).toContainText('Approved by you');
});

test('a queued message can be cancelled in the window and is then never sent; editing after approval needs a new approval', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop');
  await openShare(page);
  const before = (await mail(page)).length;
  await page.getByRole('button', { name: /Prepare message/ }).click();
  await page.getByLabel('To (one address per line)').fill('cancel.me@example.org');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByText('To: cancel.me@example.org')).toBeVisible();
  await page.getByLabel('Type SEND to approve').fill('send');
  await page.getByRole('button', { name: 'Approve and queue' }).click();
  await expect(page.getByRole('button', { name: 'Cancel sending' })).toBeVisible();
  await page.getByRole('button', { name: 'Cancel sending' }).click();
  await expect(page.getByRole('button', { name: 'Queue for sending' })).toBeVisible();

  // editing an approved message returns it to review: the old approval no longer applies
  await page.getByLabel('Subject').fill('A different subject');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('status', { name: 'Message status' })).toHaveText('Ready for your review');
  await expect(page.getByRole('button', { name: 'Queue for sending' })).toHaveCount(0);

  await page.waitForTimeout(8000); // longer than the 5 s window: a cancelled or unapproved message must not go out
  expect((await mail(page)).length).toBe(before);
});

test('the Share minutes screen fits a phone without sideways scrolling', async ({ page }, info) => {
  test.skip(info.project.name !== 'mobile');
  await openShare(page);
  await page.getByRole('button', { name: 'Prepare message' }).click();
  await expect(page.getByRole('region', { name: 'What will be sent' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});

test('Settings can send one fixed test email to the typed address, and it contains no meeting content', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop');
  await page.goto(URL_ + '#/settings/accounts');
  const loginHeading = page.getByRole('heading', { name: 'Sign in to Reachy' });
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(loginHeading.or(nav)).toBeVisible();
  if (await loginHeading.isVisible()) {
    await page.getByLabel('Username').fill('owner');
    await page.getByLabel('Password').fill('correct-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
  }
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
  await page.goto(URL_ + '#/settings/accounts');
  const section = page.getByRole('region', { name: 'Send a test email' });
  await expect(section).toBeVisible();
  const before = (await mail(page)).length;
  await expect(section.getByRole('button', { name: 'Send test email' })).toBeDisabled();
  await section.getByLabel('Send the test email to').fill('Owner.Test.Inbox@example.org');
  await section.getByRole('button', { name: 'Send test email' }).click();
  await expect(section.getByRole('status', { name: 'Test email result' })).toContainText('Test email sent to owner.test.inbox@example.org', { timeout: 20000 });
  const all = await mail(page);
  expect(all).toHaveLength(before + 1);
  const sent = all.at(-1)!;
  expect(sent).toMatchObject({ subject: 'Reachy test email', to: 'owner.test.inbox@example.org', attachments: [] });
  expect(sent.rcpts).toEqual(['owner.test.inbox@example.org']);
  expect(sent.body).toContain('test message from Reachy');
  expect(sent.body).not.toContain('Weekly sync');
  expect(sent.body).not.toContain('Priya');
});
