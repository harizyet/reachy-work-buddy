import { spawn, type ChildProcess } from 'node:child_process';
import { startPrefixProxy } from './prefix_proxy.mjs';

export const HUB_PORT = 18047;
export const PROXY_PORT = 18048;
export const NOTEPAD_PORT = 18049; // Phase 49: a hub in front of a real core with Notepad processing on
export const ANALYSIS_PORT = 18050; // Phase 31: a hub in front of a real core with meeting analysis on

let hub: ChildProcess | undefined;
let notepadHub: ChildProcess | undefined;
let analysisHub: ChildProcess | undefined;
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
  notepadHub = spawn(python, ['e2e/notepad_hub_server.py', String(NOTEPAD_PORT)], { stdio: 'inherit' });
  await waitFor(`http://127.0.0.1:${NOTEPAD_PORT}/web/`);
  analysisHub = spawn(python, ['e2e/analysis_hub_server.py', String(ANALYSIS_PORT)], { stdio: 'inherit' });
  await waitFor(`http://127.0.0.1:${ANALYSIS_PORT}/web/`);
  return async () => {
    proxy?.close();
    hub?.kill();
    notepadHub?.kill();
    analysisHub?.kill();
  };
}
