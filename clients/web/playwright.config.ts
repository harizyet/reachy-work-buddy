import { defineConfig } from '@playwright/test';

// The e2e suite runs against a real in-process hub (e2e/hub_server.py) serving
// the production build, directly and through a /hub-prefix proxy.
export default defineConfig({
  testDir: 'e2e',
  testMatch: '**/*.spec.ts',
  globalSetup: './e2e/global.ts',
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    browserName: 'chromium',
    // A synthetic microphone, so recording a clip in the browser can be exercised without hardware.
    launchOptions: { args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--enable-precise-memory-info', '--js-flags=--expose-gc'] },
    permissions: ['microphone'],
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1280, height: 800 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, hasTouch: true } },
  ],
});
