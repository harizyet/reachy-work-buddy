import { expect, test, type Page } from '@playwright/test';
import { HUB_PORT } from './global';

// Phase 47C: the Brain view in a real browser with real (software) WebGL. The data is synthetic and the page makes no
// request to the hub for it; only the sign-in and the page shell use the hub.
const URL_ROOT = `http://127.0.0.1:${HUB_PORT}/web/`;

// Counts draw calls and remembers every WebGL context, so tests can see whether rendering continues and whether the
// GPU context is released.
const INSTRUMENT = () => {
  const w = window as unknown as { __draws: number; __contexts: WebGLRenderingContext[] };
  w.__draws = 0;
  w.__contexts = [];
  for (const proto of [WebGLRenderingContext.prototype, WebGL2RenderingContext.prototype] as const) {
    for (const name of ['drawArrays', 'drawElements', 'drawArraysInstanced', 'drawElementsInstanced'] as const) {
      const original = (proto as unknown as Record<string, (...a: unknown[]) => void>)[name]!;
      (proto as unknown as Record<string, unknown>)[name] = function (this: unknown, ...args: unknown[]) {
        w.__draws += 1;
        return original.apply(this, args);
      };
    }
  }
  const getContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...rest: unknown[]) {
    const ctx = (getContext as (...a: unknown[]) => RenderingContext | null).call(this, type, ...rest);
    if (ctx && /webgl/.test(type)) w.__contexts.push(ctx as WebGLRenderingContext);
    return ctx;
  } as typeof HTMLCanvasElement.prototype.getContext;
};

async function openBrain(page: Page, data: 'synthetic' | 'live' = 'synthetic') {
  await page.goto(URL_ROOT);
  const login = page.getByRole('heading', { name: 'Sign in to Reachy' });
  await expect(login.or(page.getByRole('navigation', { name: 'Main' }))).toBeVisible();
  if (await login.isVisible()) {
    await page.getByLabel('Username').fill('owner');
    await page.getByLabel('Password').fill('correct-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
  }
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
  await page.getByRole('link', { name: 'Brain' }).click();
  await expect(page.getByRole('heading', { name: 'Brain' })).toBeVisible();
  if (data === 'synthetic') await page.getByRole('radio', { name: 'Synthetic demonstration' }).check();
  await expect(page.getByText(/Showing \d+ of \d+ records/)).toBeVisible();
}


// How many of a downscaled copy of the canvas are brighter than the near-black background, read in the same frame the
// scene is drawn so the buffer is still valid.
const litPixels = (page: Page) =>
  page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        requestAnimationFrame(() => {
          const gl = document.querySelector<HTMLCanvasElement>('[data-testid=brain-canvas] canvas')!;
          const copy = document.createElement('canvas');
          copy.width = 160;
          copy.height = 100;
          const ctx = copy.getContext('2d')!;
          ctx.drawImage(gl, 0, 0, 160, 100);
          const px = ctx.getImageData(0, 0, 160, 100).data;
          let n = 0;
          for (let i = 0; i < px.length; i += 4) if (px[i]! + px[i + 1]! + px[i + 2]! > 60) n += 1;
          resolve(n);
        });
      }),
  );

const draws = (page: Page) => page.evaluate(() => (window as unknown as { __draws: number }).__draws);

test.describe('Brain view', () => {
  test('renders real WebGL: a canvas, non-blank, lazy-loaded, labelled synthetic', async ({ page }) => {
    await page.addInitScript(INSTRUMENT);
    const requests: string[] = [];
    page.on('request', (r) => requests.push(new URL(r.url()).pathname));
    await page.goto(URL_ROOT);
    await page.getByLabel('Username').fill('owner');
    await page.getByLabel('Password').fill('correct-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
    expect(requests.some((p) => /BrainScene/.test(p))).toBe(false); // the 3D code is not loaded until asked for
    requests.length = 0;
    await page.getByRole('link', { name: 'Brain' }).click();
    await page.getByRole('radio', { name: 'Synthetic demonstration' }).check();
    await expect(page.getByTestId('brain-canvas').locator('canvas')).toBeVisible();
    await expect(page.getByText(/Synthetic demonstration data\./)).toBeVisible();
    expect(requests.some((p) => /BrainScene/.test(p))).toBe(true);

    await expect.poll(() => draws(page), { timeout: 5000 }).toBeGreaterThan(20);
    await expect.poll(() => litPixels(page), { timeout: 8000 }).toBeGreaterThan(40);
  });

  test('the list is a full keyboard path: search, filter, select, reset', async ({ page }) => {
    await page.addInitScript(INSTRUMENT);
    await openBrain(page);
    await expect(page.getByText(/Showing 600 of 600 records/)).toBeVisible();
    await page.getByLabel('Search records').fill('meeting');
    await expect(page.getByText(/Showing \d+ of 600 records/)).toBeVisible();
    await expect(page.getByText(/Showing 600 of 600/)).toHaveCount(0);
    await page.getByLabel('Search records').fill('');
    await page.getByRole('checkbox', { name: /Notes/ }).uncheck();
    await page.getByRole('checkbox', { name: /Tasks/ }).uncheck();
    await expect(page.getByText(/Showing 600 of 600/)).toHaveCount(0);

    const first = page.getByRole('region', { name: 'Records' }).getByRole('button').first();
    await first.focus();
    await page.keyboard.press('Enter');
    const details = page.getByRole('region', { name: 'Record details' });
    await expect(details.getByText('Source')).toBeVisible();
    await expect(details.getByText(/stands for no real record/)).toBeVisible();
    await page.getByRole('button', { name: 'Reset view' }).click();
    await expect(page.getByTestId('brain-canvas').locator('canvas')).toBeVisible();
    await expect(page.getByText(/Not available yet/)).toBeVisible();
  });

  test('selecting in the 3D view works: a click on a record opens its details', async ({ page }) => {
    await page.addInitScript(INSTRUMENT);
    await openBrain(page);
    const canvas = page.getByTestId('brain-canvas').locator('canvas');
    await expect(canvas).toBeVisible();
    await expect.poll(() => draws(page)).toBeGreaterThan(20);
    const box = (await canvas.boundingBox())!;
    const none = page.getByText('Select a record in the list or the 3D view to see where it comes from.');
    await expect(none).toBeVisible();
    let hit = false;
    // Records fill the middle of the view; sweep a grid of points until one lands on a dot.
    scan: for (let y = 0.2; y <= 0.8; y += 0.03) {
      for (let x = 0.15; x <= 0.85; x += 0.03) {
        await page.mouse.click(box.x + box.width * x, box.y + box.height * y);
        if (!(await none.isVisible())) {
          hit = true;
          break scan;
        }
      }
    }
    expect(hit).toBe(true);
    await expect(page.getByRole('region', { name: 'Record details' }).getByText('Classification')).toBeVisible();
  });

  test('without WebGL the records are shown as a list and no 3D code runs', async ({ page }) => {
    await page.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...rest: unknown[]) {
        return /webgl/.test(type) ? null : (original as (...a: unknown[]) => RenderingContext | null).call(this, type, ...rest);
      } as typeof HTMLCanvasElement.prototype.getContext;
    });
    const requests: string[] = [];
    page.on('request', (r) => requests.push(new URL(r.url()).pathname));
    await openBrain(page);
    await expect(page.getByTestId('brain-fallback')).toContainText('3D graphics are not available');
    await expect(page.locator('[data-testid=brain-canvas]')).toHaveCount(0);
    expect(requests.some((p) => /BrainScene/.test(p))).toBe(false);
    await page.getByRole('region', { name: 'Records' }).getByRole('button').first().click();
    await expect(page.getByRole('region', { name: 'Record details' }).getByText('Source')).toBeVisible();
  });

  test('reduced motion starts light and renders only when something changes', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.addInitScript(INSTRUMENT);
    await openBrain(page);
    await expect(page.getByLabel('Detail', { exact: true })).toHaveValue('low');
    await expect(page.getByText(/1,500 decorative particles/)).toBeVisible();
    await expect.poll(() => draws(page)).toBeGreaterThan(0);
    await page.waitForTimeout(500);
    const before = await draws(page);
    await page.waitForTimeout(1000);
    expect(await draws(page) - before).toBeLessThanOrEqual(2); // idle: no animation loop
    await page.getByRole('button', { name: 'Reset view' }).click();
    await expect.poll(async () => (await draws(page)) - before).toBeGreaterThan(0); // a change renders again
  });

  test('a hidden tab stops rendering and a visible one resumes', async ({ page }) => {
    await page.addInitScript(INSTRUMENT);
    await openBrain(page);
    await expect.poll(() => draws(page)).toBeGreaterThan(20);
    const setHidden = (hidden: boolean) =>
      page.evaluate((h) => {
        Object.defineProperty(document, 'hidden', { configurable: true, get: () => h });
        document.dispatchEvent(new Event('visibilitychange'));
      }, hidden);
    await setHidden(true);
    await page.waitForTimeout(400);
    const stopped = await draws(page);
    await page.waitForTimeout(1000);
    expect(await draws(page) - stopped).toBeLessThanOrEqual(2);
    await setHidden(false);
    await expect.poll(async () => (await draws(page)) - stopped, { timeout: 5000 }).toBeGreaterThan(20);
  });

  test('leaving the page releases the WebGL context, and ten visits do not accumulate memory', async ({ page, browserName }, info) => {
    test.skip(browserName !== 'chromium');
    await page.addInitScript(INSTRUMENT);
    await openBrain(page);
    await expect(page.getByTestId('brain-canvas').locator('canvas')).toBeVisible();
    await expect.poll(() => draws(page)).toBeGreaterThan(5);
    await page.getByRole('link', { name: 'Overview' }).click();
    await expect(page.getByRole('heading', { name: 'System status' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => (window as unknown as { __contexts: WebGLRenderingContext[] }).__contexts.every((c) => c.isContextLost()))).toBe(true);

    const heap = () => page.evaluate(() => (performance as unknown as { memory: { usedJSHeapSize: number } }).memory.usedJSHeapSize);
    const gc = () => page.evaluate(() => (window as unknown as { gc?: () => void }).gc?.());
    for (let i = 0; i < 2; i++) {
      await page.getByRole('link', { name: 'Brain' }).click();
      await expect(page.getByTestId('brain-canvas').locator('canvas')).toBeVisible();
      await page.getByRole('link', { name: 'Overview' }).click();
    }
    await gc();
    const base = await heap();
    for (let i = 0; i < 10; i++) {
      await page.getByRole('link', { name: 'Brain' }).click();
      await expect(page.getByTestId('brain-canvas').locator('canvas')).toBeVisible();
      await page.getByRole('link', { name: 'Overview' }).click();
      await expect(page.getByRole('heading', { name: 'System status' })).toBeVisible();
    }
    await gc();
    const after = await heap();
    const contexts = await page.evaluate(() => (window as unknown as { __contexts: WebGLRenderingContext[] }).__contexts.length);
    const alive = await page.evaluate(() => (window as unknown as { __contexts: WebGLRenderingContext[] }).__contexts.filter((c) => !c.isContextLost()).length);
    info.annotations.push({ type: 'measurement', description: `heap ${(base / 1e6).toFixed(1)} MB -> ${(after / 1e6).toFixed(1)} MB after 10 visits; ${contexts} contexts created, ${alive} still alive` });
    expect(alive).toBe(0);
    expect(after - base).toBeLessThan(20 * 1024 * 1024);
  });

  test('records the frame rate of the software renderer (a baseline, not a target)', async ({ page }, info) => {
    await page.addInitScript(INSTRUMENT);
    await openBrain(page);
    await expect.poll(() => draws(page)).toBeGreaterThan(20);
    const start = await draws(page);
    const result = await page.evaluate(
      () =>
        new Promise<{ ms: number; frames: number }>((resolve) => {
          let frames = 0;
          const t0 = performance.now();
          const tick = () => {
            frames += 1;
            if (performance.now() - t0 < 3000) requestAnimationFrame(tick);
            else resolve({ ms: performance.now() - t0, frames });
          };
          requestAnimationFrame(tick);
        }),
    );
    const rendered = (await draws(page)) - start;
    info.annotations.push({ type: 'measurement', description: `${Math.round((result.frames / result.ms) * 1000)} rAF/s, ${rendered} draw calls in ${Math.round(result.ms)} ms (software WebGL, ${info.project.name})` });
    expect(result.frames).toBeGreaterThan(10); // the page keeps responding while rendering
  });

  test('the glow (bloom) is on by default, adds render passes, and is switched off in Settings · Display, and the choice sticks', async ({ page }, info) => {
    await page.addInitScript(INSTRUMENT);
    await openBrain(page);
    await expect.poll(() => draws(page)).toBeGreaterThan(20);
    const perFrame = () =>
      page.evaluate(
        () =>
          new Promise<number>((resolve) => {
            const w = window as unknown as { __draws: number };
            const d0 = w.__draws;
            let frames = 0;
            const t0 = performance.now();
            const tick = () => {
              frames += 1;
              if (performance.now() - t0 < 1500) requestAnimationFrame(tick);
              else resolve((w.__draws - d0) / Math.max(1, frames));
            };
            requestAnimationFrame(tick);
          }),
      );
    const withBloom = await perFrame();

    await page.getByRole('link', { name: 'Settings' }).click();
    await page.getByRole('tab', { name: 'Display' }).click();
    const box = page.getByRole('checkbox', { name: 'Glow effect (bloom)' });
    await expect(box).toBeChecked();
    await box.uncheck();
    await page.getByRole('link', { name: 'Brain' }).click();
    await expect(page.getByTestId('brain-canvas').locator('canvas')).toBeVisible();
    await expect.poll(() => draws(page)).toBeGreaterThan(20);
    const withoutBloom = await perFrame();
    info.annotations.push({ type: 'measurement', description: `draw calls per animation frame: ${withBloom.toFixed(1)} with bloom, ${withoutBloom.toFixed(1)} without (${info.project.name})` });
    expect(withBloom).toBeGreaterThan(withoutBloom + 1);

    await page.reload();
    await page.getByRole('link', { name: 'Settings' }).click();
    await page.getByRole('tab', { name: 'Display' }).click();
    await expect(page.getByRole('checkbox', { name: 'Glow effect (bloom)' })).not.toBeChecked();
    await page.getByRole('checkbox', { name: 'Glow effect (bloom)' }).check(); // leave it on for the other tests
  });

  test('with the glow on, the picture is not blank', async ({ page }) => {
    await page.addInitScript(INSTRUMENT);
    await openBrain(page);
    await expect.poll(() => draws(page)).toBeGreaterThan(20);
    await expect.poll(() => litPixels(page), { timeout: 8000 }).toBeGreaterThan(40);
  });

  test('fits the screen without horizontal scrolling', async ({ page }) => {
    await openBrain(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    await expect(page.getByLabel('Search records')).toBeVisible();
  });
});

test.describe('Brain with the owner’s records (real hub, real core, in-memory stores)', () => {
  test('shows what the owner may see, hides forgotten and sensitive records, and only ever reads', async ({ page }) => {
    const requests: { method: string; path: string; query: string }[] = [];
    page.on('request', (r) => {
      const u = new URL(r.url());
      if (u.pathname.includes('/brain')) requests.push({ method: r.method(), path: u.pathname, query: u.search });
    });
    const responses: { path: string; cache: string | undefined }[] = [];
    page.on('response', (r) => {
      const u = new URL(r.url());
      if (u.pathname.includes('/brain')) responses.push({ path: u.pathname, cache: r.headers()['cache-control'] });
    });
    await openBrain(page, 'live');
    await expect(page.getByText(/Your records\./)).toBeVisible();
    await expect(page.getByText(/Synthetic demonstration data/)).toHaveCount(0);
    const list = page.getByRole('region', { name: 'Records' });
    await expect(list.getByRole('button', { name: /Falcon-7B is the default model/ })).toBeVisible();
    await expect(list.getByRole('button', { name: /Send the summary/ })).toBeVisible();
    await expect(list.getByRole('button', { name: /Weekly sync/ })).toBeVisible();
    // Withheld by the server: sensitive, and forgotten.
    await page.getByLabel('Search records').fill('medical');
    await expect(page.getByText('No records match.')).toBeVisible();
    await page.getByLabel('Search records').fill('forgotten fact');
    await expect(page.getByText('No records match.')).toBeVisible();
    await page.getByLabel('Search records').fill('');

    await list.getByRole('button', { name: /Weekly sync/ }).click();
    const details = page.getByRole('region', { name: 'Record details' });
    await expect(details.getByRole('link', { name: 'Open in Meetings' })).toBeVisible();
    await expect(details.getByText('Classification')).toBeVisible();
    await expect(details.getByText(/No structured links between these kinds of record exist yet/)).toBeVisible();
    await page.getByRole('button', { name: 'Refresh records' }).click();

    // The browser asked for nothing but reads, and named no access level of its own.
    expect(requests.length).toBeGreaterThan(2);
    expect(requests.every((r) => r.method === 'GET')).toBe(true);
    expect(requests.some((r) => /sensitiv|principal|ceiling|destination/i.test(r.query))).toBe(false);
    expect(responses.every((r) => r.cache === 'no-store')).toBe(true);
    await expect(page.getByTestId('brain-canvas').locator('canvas')).toBeVisible();
  });

  test('a record opened from the Brain page opens in its own screen', async ({ page }) => {
    await openBrain(page, 'live');
    await page.getByRole('region', { name: 'Records' }).getByRole('button', { name: /Weekly sync/ }).click();
    await page.getByRole('region', { name: 'Record details' }).getByRole('link', { name: 'Open in Meetings' }).click();
    await expect(page.getByText(/Status: Complete/)).toBeVisible();
  });

  test('the live view is usable without WebGL', async ({ page }) => {
    await page.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...rest: unknown[]) {
        return /webgl/.test(type) ? null : (original as (...a: unknown[]) => RenderingContext | null).call(this, type, ...rest);
      } as typeof HTMLCanvasElement.prototype.getContext;
    });
    await openBrain(page, 'live');
    await expect(page.getByTestId('brain-fallback')).toBeVisible();
    await expect(page.getByRole('region', { name: 'Records' }).getByRole('button', { name: /Send the summary/ })).toBeVisible();
  });
});
