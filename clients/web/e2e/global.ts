import { spawn, type ChildProcess } from 'node:child_process';
import { startPrefixProxy } from './prefix_proxy.mjs';

export const HUB_PORT = 18047;
export const PROXY_PORT = 18048;

let hub: ChildProcess | undefined;
let proxy: { close(): void } | undefined;

async function waitFor(url: string) {
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`hub did not start: ${url}`);
}

export default async function setup() {
  const python = process.env.HUB_PYTHON ?? 'python3';
  hub = spawn(python, ['e2e/hub_server.py', String(HUB_PORT)], { stdio: 'inherit' });
  await waitFor(`http://127.0.0.1:${HUB_PORT}/web/`);
  proxy = await startPrefixProxy(PROXY_PORT, HUB_PORT);
  return async () => {
    proxy?.close();
    hub?.kill();
  };
}
