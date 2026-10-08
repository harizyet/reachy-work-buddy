/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// `base: './'` keeps every asset URL relative, so the same build works when the
// hub serves it directly at /web/ and behind Caddy at /hub/web/.
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  build: { outDir: 'dist', sourcemap: false },
  server: {
    // Development only: proxy hub routes so the dev server stays same-origin
    // (cookies, no CORS). Start a hub on :8000 first.
    proxy: Object.fromEntries(
      ['/auth', '/status', '/robots', '/settings'].map((p) => [p, { target: 'http://127.0.0.1:8000' }]),
    ),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.{ts,tsx}'],
  },
});
