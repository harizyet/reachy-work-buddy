import { expect, test, type Page } from '@playwright/test';
import { ANALYSIS_PORT } from './global';

// Phase 31 in a real browser: a signed-in owner, the production build, the real hub in front of a REAL companion-core with meeting analysis on. The one stand-in is the local model
// (a scripted provider that makes the mistakes a 7B can make; see analysis_hub_server.py). Data is disposable and lives in memory.
const URL_ = `http://127.0.0.1:${ANALYSIS_PORT}/web/`;

async function signIn(page: Page, hash: string) {
  await page.goto(URL_ + hash);
  const loginHeading = page.getByRole('heading', { name: 'Sign in to Reachy' });
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(loginHeading.or(nav)).toBeVisible();
  if (await loginHeading.isVisible()) {
    await page.getByLabel('Username').fill('owner');
    await page.getByLabel('Password').fill('correct-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
  }
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
  await page.goto(URL_ + hash);
}

async function openAnalysis(page: Page) {
  await signIn(page, '#/meetings');
  const id = await page.evaluate(async () => ((await (await fetch('/meetings')).json()) as { id: string; title: string }[]).find((m) => m.title === 'Cluster sync')!.id);
  await page.goto(`${URL_}#/meetings/${id}`);
  await page.getByRole('button', { name: 'Analysis' }).click();
}

test('analyse, read the evidence, confirm an action once, dismiss a finding, play from a quote', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop');
  await openAnalysis(page);
  await expect(page.getByRole('status', { name: 'Analysis status' })).toHaveText('Not analysed');
  await page.getByRole('button', { name: 'Analyse this meeting' }).click();

  // Nothing is a task yet: the action waits in a review section that says so.
  const review = page.getByLabel('Actions from this meeting');
  await expect(review).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('status', { name: 'Analysis status' })).toHaveText('Actions to review');
  await expect(review.getByText('Not yet confirmed. Nothing is added to your tasks', { exact: false })).toBeVisible();
  // The sentence the speech-to-text cut in two is one quote, with the first fragment's time and speaker.
  await expect(review.getByText('“Alice will contact the vendor about compatibility by next Friday”')).toBeVisible();
  await expect(review.getByText('Speaker 1,', { exact: false })).toBeVisible();
  await expect(review.getByRole('button', { name: 'Play from 0:20' })).toBeVisible();
  // Everything is marked unverified. The agreed decision is in the open; the suggestion ("we could maybe") is kept but collapsed; a decision the transcript does not contain never appears.
  await expect(page.getByText('written by a model from a speech-to-text transcript, so treat it as unverified', { exact: false })).toBeVisible();
  const decisions = page.getByLabel('Decisions');
  await expect(decisions.getByText('Migrate the cluster in the first week of November', { exact: true })).toBeVisible();
  await expect(decisions.getByText('Buy new servers')).toHaveCount(0);
  const weakDecisions = decisions.locator('details');
  await expect(weakDecisions).toHaveCount(1);
  await expect(weakDecisions).not.toHaveAttribute('open', '');
  await expect(decisions.getByText('Add a second region')).toBeHidden();
  await weakDecisions.locator('summary').click();
  await expect(weakDecisions.getByText('Add a second region')).toBeVisible();
  await expect(weakDecisions.locator('li', { hasText: 'Add a second region' }).first()).toContainText('Check the quote');
  await expect(page.getByLabel('Open questions').getByText('Who owns the backup budget', { exact: true })).toBeVisible();
  await expect(page.getByText('1 suggestion was left out because the transcript did not support it.')).toBeVisible();

  // Confirm once; a second click cannot add a second task.
  await review.getByRole('button', { name: 'Confirm as task' }).click();
  await expect(page.getByText('Added to your tasks: “Alice: Contact the vendor about compatibility (next Friday)”', { exact: false })).toBeVisible();
  await expect(review).toHaveCount(0);
  const tasks = await page.evaluate(async () => (await (await fetch('/planner/tasks')).json()) as { text: string }[]);
  expect(tasks.filter((t) => t.text.startsWith('Alice: Contact the vendor'))).toHaveLength(1);

  // Dismiss a finding.
  await weakDecisions.locator('li', { hasText: 'Add a second region' }).first().getByRole('button', { name: 'Dismiss' }).click();
  await expect(decisions.getByText('Add a second region')).toHaveCount(0);

  // The analysis survives a reload (it is stored by the server, not the page).
  await page.reload();
  await page.getByRole('button', { name: 'Analysis' }).click();
  await expect(page.getByLabel('Decisions').getByText('Migrate the cluster in the first week of November', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Decisions').getByText('Add a second region')).toHaveCount(0);

  // "Play from here" goes to the transcript, where the recording is.
  await page.getByLabel('Open questions').getByRole('button', { name: 'Play from 0:50' }).click();
  await expect(page.getByRole('heading', { name: 'Transcript' })).toBeVisible();
});

test('mobile: the Analysis tab fits the screen', async ({ page }, info) => {
  test.skip(info.project.name !== 'mobile');
  await openAnalysis(page);
  await expect(page.getByRole('status', { name: 'Analysis status' })).not.toHaveText('Checking…');
  const first = page.getByRole('button', { name: 'Analyse this meeting' });
  if (await first.isVisible()) await first.click(); // the desktop run shares this server and may already have analysed the meeting
  await expect(page.getByLabel('Decisions')).toBeVisible({ timeout: 15000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
