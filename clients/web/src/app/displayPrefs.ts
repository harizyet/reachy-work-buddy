import { useSyncExternalStore } from 'react';

// Per-browser display preferences. They hold no secrets and no records, only how this screen looks, so keeping them
// in localStorage is a convenience for this viewer; every read and write tolerates storage being blocked.
const BLOOM_KEY = 'reachy.web.brain.bloom';
const listeners = new Set<() => void>();

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function reduced(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** The stored choice, else off for people who asked for reduced motion and on for everyone else. */
export function getBloom(): boolean {
  const stored = read(BLOOM_KEY);
  if (stored === '1') return true;
  if (stored === '0') return false;
  return !reduced();
}

export function setBloom(on: boolean): void {
  try {
    window.localStorage.setItem(BLOOM_KEY, on ? '1' : '0');
  } catch {
    // Storage is blocked: the choice lasts until the page is reloaded.
    memory = on;
  }
  listeners.forEach((l) => l());
}

let memory: boolean | null = null;
const snapshot = () => (memory ?? getBloom()) as boolean;

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener('storage', listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', listener);
  };
}

export function useBloom(): [boolean, (on: boolean) => void] {
  return [useSyncExternalStore(subscribe, snapshot, () => true), setBloom];
}
