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

async function openBrain(page: Page) {
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
}

const draws = (page: Page) => page.evaluate(() => (window as unknown as { __draws: number }).__draws);

test.describe('Brain view', () => {
  test('renders real WebGL: a canvas, non-blank, lazy-loaded, labelled synthetic, no hub data requests', async ({ page }) => {
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
    await expect(page.getByTestId('brain-canvas').locator('canvas')).toBeVisible();
    await expect(page.getByText(/Synthetic demonstration data\./)).toBeVisible();
    expect(requests.some((p) => /BrainScene/.test(p))).toBe(true);
    // Nothing about the synthetic records was asked of the hub (the shell's own status polling is unrelated).
    expect(requests.filter((p) => /\/(memories|documents|brain|planner\/notes|meetings)/.test(p))).toEqual([]);

    await expect.poll(() => draws(page), { timeout: 5000 }).toBeGreaterThan(20);
    const lit = await page.evaluate(
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
            for (let i = 0; i < px.length; i += 4) if (px[i]! + px[i + 1]! + px[i + 2]! > 60) n += 1; // brighter than the near-black background
            resolve(n);
          });
        }),
    );
    expect(lit).toBeGreaterThan(40);
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

  test('fits the screen without horizontal scrolling', async ({ page }) => {
    await openBrain(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    await expect(page.getByLabel('Search records')).toBeVisible();
  });
});
