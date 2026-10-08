import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getBloom } from '../src/app/displayPrefs';
import type { SceneProps } from '../src/features/brain/BrainScene';
import { createFakeHub } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

const sceneProps: SceneProps[] = [];
vi.mock('../src/features/brain/BrainScene', () => ({
  default: (props: SceneProps) => {
    sceneProps.push(props);
    return <div data-testid="scene-stub" />;
  },
}));
vi.mock('../src/features/brain/webgl', async (original) => ({ ...(await original<typeof import('../src/features/brain/webgl')>()), webglAvailable: () => true }));

beforeEach(() => {
  sceneProps.length = 0;
  window.localStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

describe('Display setting: bloom', () => {
  it('is on by default, can be turned off in Settings, reaches the Brain scene, and is remembered', async () => {
    createFakeHub({ status: SAMPLE_STATUS });
    expect(getBloom()).toBe(true);
    renderApp('#/settings/display');
    const user = userEvent.setup();
    const box = await screen.findByRole('checkbox', { name: 'Glow effect (bloom)' });
    expect(box).toBeChecked();
    await user.click(box);
    expect(box).not.toBeChecked();
    expect(window.localStorage.getItem('reachy.web.brain.bloom')).toBe('0');
    expect(getBloom()).toBe(false);

    await user.click(screen.getByRole('link', { name: 'Brain' }));
    await screen.findByTestId('scene-stub');
    expect(sceneProps.at(-1)!.bloom).toBe(false);

    await user.click(screen.getByRole('link', { name: 'Settings' }));
    await user.click(await screen.findByRole('tab', { name: 'Display' }));
    await user.click(await screen.findByRole('checkbox', { name: 'Glow effect (bloom)' }));
    expect(window.localStorage.getItem('reachy.web.brain.bloom')).toBe('1');
    await user.click(screen.getByRole('link', { name: 'Brain' }));
    await screen.findByTestId('scene-stub');
    expect(sceneProps.at(-1)!.bloom).toBe(true);
  });

  it('starts off for people who prefer reduced motion, but a stored choice wins', () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} }));
    expect(getBloom()).toBe(false);
    window.localStorage.setItem('reachy.web.brain.bloom', '1');
    expect(getBloom()).toBe(true);
  });

  it('keeps working when browser storage is blocked, and stores nothing else', async () => {
    createFakeHub({ status: SAMPLE_STATUS });
    const blocked = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
    vi.stubGlobal('localStorage', blocked);
    renderApp('#/settings/display');
    const user = userEvent.setup();
    const box = await screen.findByRole('checkbox', { name: 'Glow effect (bloom)' });
    expect(box).toBeChecked();
    await user.click(box);
    expect(box).not.toBeChecked(); // the choice holds for this page even though it cannot be saved
  });

  it('stores only the display preference, never records or keys', async () => {
    createFakeHub({ status: SAMPLE_STATUS });
    renderApp('#/settings/display');
    await userEvent.setup().click(await screen.findByRole('checkbox', { name: 'Glow effect (bloom)' }));
    expect(Object.keys({ ...window.localStorage })).toEqual(['reachy.web.brain.bloom']);
    expect(Object.keys({ ...window.sessionStorage })).toEqual([]);
  });
});
