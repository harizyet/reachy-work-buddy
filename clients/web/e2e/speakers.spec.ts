import { expect, test, type Page } from '@playwright/test';
import { SPEAKERS_PORT } from './global';

// Phase 54 in a real browser: a signed-in owner, the production build, the real hub in front of a REAL companion-core, and a REAL recording (one tone per speaker, see
// speakers_hub_server.py). Playback is the browser's own <audio> over the hub's authenticated, range-capable recording route. Data is disposable and in memory.
const URL_ = `http://127.0.0.1:${SPEAKERS_PORT}/web/`;

async function openMeeting(page: Page) {
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
  const id = await page.evaluate(async () => ((await (await fetch('/meetings')).json()) as { id: string; title: string }[]).find((m) => m.title === 'Tone sync')!.id);
  await page.goto(`${URL_}#/meetings/${id}`);
  await page.getByRole('button', { name: 'Identify speakers' }).click();
  await expect(page.getByRole('heading', { name: /SPEAKER_00/ })).toBeVisible(); // by label: an earlier test may already have named them
  return id;
}

test('listen to a sample of each speaker, swap one, name them, and see the names in the transcript', async ({ page }, info) => {
  test.skip(info.project.name !== 'desktop');
  const id = await openMeeting(page);
  const card = (n: number) => page.getByRole('listitem', { name: `Speaker ${n}` });

  // A speaker with almost no speech says so instead of offering a useless sample.
  await expect(card(3).getByText('Too little uninterrupted speech', { exact: false })).toBeVisible();

  // Real playback: the first sample of Speaker 1 starts where it says and the browser stops it at its end.
  const first = card(1).getByRole('button', { name: /^Play Speaker 1 sample at/ }).first();
  const label = (await first.getAttribute('aria-label'))!;
  const range = /at (\d+):(\d+)–(\d+):(\d+)/.exec(label)!;
  const sampleStart = Number(range[1]) * 60 + Number(range[2]);
  const sampleEnd = Number(range[3]) * 60 + Number(range[4]);
  await first.click();
  await expect(card(1).getByRole('button', { name: label.replace(/^Play/, 'Pause') })).toHaveAttribute('aria-pressed', 'true');
  await expect.poll(async () => page.evaluate(() => { const a = document.querySelector('audio')!; return !a.paused && a.currentTime > 0.2; })).toBe(true);
  const heard = await page.evaluate(() => document.querySelector('audio')!.currentTime);
  expect(heard).toBeGreaterThanOrEqual(sampleStart - 0.5);
  expect(heard).toBeLessThan(sampleEnd + 0.5);
  await expect(card(1).getByRole('button', { name: label })).toBeVisible({ timeout: 20000 }); // the Pause button turned back into Play: it stopped by itself
  const stoppedAt = await page.evaluate(() => document.querySelector('audio')!.currentTime);
  expect(stoppedAt).toBeGreaterThanOrEqual(sampleEnd - 0.1);
  expect(stoppedAt).toBeLessThan(sampleEnd + 1.5);

  // The browser really fetched ranges of the recording, not the whole file or another route.
  const another = card(1).getByRole('button', { name: /^Another sample instead of/ }).first();
  if (await another.count()) {
    await another.click();
    await expect(card(1).getByRole('button', { name: new RegExp(`^Play Speaker 1 sample at ${range[1]}:${range[2]}`) })).toHaveCount(0);
  }

  // Name one speaker, mark another unknown, skip the one with no sample, save once.
  await card(1).getByLabel('Who is Speaker 1?').fill('Priya Shah');
  await card(2).getByRole('button', { name: 'Unknown' }).click();
  await card(3).getByRole('button', { name: 'Skip' }).click();
  await page.getByRole('button', { name: 'Save 3 changes' }).click();
  await expect(page.getByText('Saved. The transcript now shows these names.')).toBeVisible();

  // The names are on the meeting, the raw labels are untouched, and the transcript uses them.
  const meeting = await page.evaluate(async (m) => (await (await fetch(`/meetings/${m}`)).json()) as { speaker_names: Record<string, string>; diarization_segments: { speaker: string }[] }, id);
  expect(meeting.speaker_names).toEqual({ SPEAKER_00: 'Priya Shah' });
  expect(meeting.diarization_segments[0]!.speaker).toBe('SPEAKER_00');
  await page.getByRole('button', { name: 'Transcript' }).click();
  await expect(page.getByRole('button', { name: 'Rename Priya Shah' }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Rename Speaker 2' }).first()).toBeVisible(); // unknown stays generic

  // It survives a reload (the hub holds it, not the page), and the screen shows what was saved.
  await page.reload();
  await page.getByRole('button', { name: 'Identify speakers' }).click();
  await expect(page.getByText('Saved as Priya Shah.')).toBeVisible();
  await expect(page.getByText('Saved as unknown.')).toBeVisible();
  await expect(page.getByText('Saved as skipped.')).toBeVisible();

  // A signed-out client gets neither the samples nor the recording.
  const refused = await page.evaluate(async (m) => {
    await fetch('/auth/logout', { method: 'POST', headers: { 'X-Reachy-CSRF': '1' } });
    return [(await fetch(`/meetings/${m}/speakers/identify`)).status, (await fetch(`/meetings/${m}/audio`)).status];
  }, id);
  expect(refused).toEqual([401, 401]);
});

test('the screen fits a phone without sideways scrolling', async ({ page }, info) => {
  test.skip(info.project.name !== 'mobile');
  await openMeeting(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
