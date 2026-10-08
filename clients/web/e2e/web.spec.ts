import { expect, test, type Page } from '@playwright/test';
import { HUB_PORT, PROXY_PORT } from './global';

const MOUNTS = [
  { name: 'direct /web/', url: `http://127.0.0.1:${HUB_PORT}/web/` },
  { name: 'proxied /hub/web/', url: `http://127.0.0.1:${PROXY_PORT}/hub/web/` },
];

async function signIn(page: Page) {
  await page.getByLabel('Username').fill('owner');
  await page.getByLabel('Password').fill('correct-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('heading', { name: 'System status' })).toBeVisible();
}

for (const mount of MOUNTS) {
  test.describe(mount.name, () => {
    test('protected route redirects to sign-in and renders no private content', async ({ page }) => {
      await page.goto(mount.url);
      await expect(page.getByRole('heading', { name: 'Sign in to Reachy' })).toBeVisible();
      await expect(page).toHaveURL(/#\/login$/);
      await expect(page.getByText('Companion core')).toHaveCount(0);
    });

    test('wrong password is refused, right password shows the real hub status', async ({ page }) => {
      await page.goto(mount.url);
      await page.getByLabel('Username').fill('owner');
      await page.getByLabel('Password').fill('wrong');
      await page.getByRole('button', { name: 'Sign in' }).click();
      await expect(page.getByRole('alert')).toContainText('Invalid username or password');
      await signIn(page);
      const card = page.getByRole('region', { name: 'Components' });
      await expect(card.getByText('Reachy hub')).toBeVisible();
      await expect(card.getByText('Companion core')).toBeVisible();
      await expect(card.getByText('desk')).toBeVisible();
      await expect(page.getByRole('region', { name: 'Language model usage' })).toBeVisible();
    });

    test('a reload keeps the session; logout ends it and back-navigation shows nothing private', async ({ page }) => {
      await page.goto(mount.url);
      await signIn(page);
      await page.reload();
      await expect(page.getByRole('heading', { name: 'System status' })).toBeVisible();
      await page.getByRole('button', { name: 'Log out' }).click();
      await expect(page.getByRole('heading', { name: 'Sign in to Reachy' })).toBeVisible();
      await page.goBack();
      await expect(page.getByText('Companion core')).toHaveCount(0);
      await page.goto(mount.url);
      await expect(page.getByRole('heading', { name: 'Sign in to Reachy' })).toBeVisible();
      // The server really ended the session: the data route now refuses.
      const base = new URL('../', mount.url).href;
      const status = await page.request.get(base + 'status');
      expect(status.status()).toBe(401);
    });

    test('an expired session cookie returns to sign-in on reload', async ({ page, context }) => {
      await page.goto(mount.url);
      await signIn(page);
      // The hub re-sets the session cookie on every response, so an in-flight request would
      // bring back the cookie cleared below; let the sign-in's own requests finish first.
      await page.waitForLoadState('networkidle');
      await context.clearCookies(); // what the hub's 12 h expiry looks like to the browser
      await page.reload();
      await expect(page.getByRole('heading', { name: 'Sign in to Reachy' })).toBeVisible();
    });

    test('a 401 during polling drops the page to sign-in and clears private text', async ({ page }) => {
      await page.goto(mount.url);
      await signIn(page);
      // Answer the next polls the way the hub does for an expired session. (Clearing the cookie
      // instead would race: the hub re-sets it on any in-flight response.)
      await page.route('**/status', (route) =>
        route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Login required"}' }),
      );
      // The next 10 s status poll gets the 401.
      await expect(page.getByRole('heading', { name: 'Sign in to Reachy' })).toBeVisible({ timeout: 15_000 });
      await expect(page.getByRole('status').filter({ hasText: 'Your session has ended' })).toBeVisible();
      await expect(page.getByText('Companion core')).toHaveCount(0);
    });

    test('no secrets or data are written to browser storage', async ({ page }) => {
      await page.goto(mount.url);
      await signIn(page);
      const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
      expect(stored).toBe('{}{}');
    });

    test('layout fits the viewport without horizontal scrolling', async ({ page }) => {
      await page.goto(mount.url);
      await signIn(page);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(0);
      await expect(page.getByRole('button', { name: 'Log out' })).toBeVisible();
    });
  });
}

test('legacy clients are untouched beside /web/', async ({ page, request }) => {
  const ui = await request.get(`http://127.0.0.1:${HUB_PORT}/ui/`);
  expect(ui.status()).toBe(200);
  expect(await ui.text()).toContain('Reachy operator');
  expect((await request.get(`http://127.0.0.1:${HUB_PORT}/app/`)).status()).toBe(200);
  await page.goto(`http://127.0.0.1:${HUB_PORT}/ui/`);
  await expect(page.getByRole('heading', { name: 'Reachy operator' })).toBeVisible();
});
