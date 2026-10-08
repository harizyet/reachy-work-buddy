import { act, cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createFakeHub } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';
import type { SceneProps } from '../src/features/brain/BrainScene';

const sceneProps: SceneProps[] = [];
vi.mock('../src/features/brain/BrainScene', () => ({
  default: (props: SceneProps) => {
    sceneProps.push(props);
    return <div data-testid="scene-stub" />;
  },
}));
const webgl = vi.hoisted(() => ({ available: false }));
vi.mock('../src/features/brain/webgl', async (original) => {
  const real = await original<typeof import('../src/features/brain/webgl')>();
  return { ...real, webglAvailable: () => webgl.available };
});
import BrainPage from '../src/features/brain/BrainPage';
import { createSyntheticSource } from '../src/features/brain/synthetic';

const setup = () => userEvent.setup();
const mount = (props: Parameters<typeof BrainPage>[0] = {}) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><BrainPage {...props} /></QueryClientProvider>);
};

beforeEach(() => {
  sceneProps.length = 0;
  webgl.available = false;
});
afterEach(() => vi.unstubAllGlobals());

describe('Brain page without WebGL (list fallback)', () => {
  it('says it is synthetic, explains the fallback, and makes no request to the hub', async () => {
    const fetchSpy = vi.fn(() => { throw new Error('the Brain view must not call the hub'); });
    vi.stubGlobal('fetch', fetchSpy);
    mount();
    expect(await screen.findByText(/Synthetic demonstration data\./)).toBeInTheDocument();
    expect(screen.getByText(/stand for none of Reachy’s real memories/)).toBeInTheDocument();
    expect(await screen.findByTestId('brain-fallback')).toHaveTextContent('3D graphics are not available in this browser');
    expect(screen.queryByTestId('scene-stub')).not.toBeInTheDocument();
    expect(screen.getByText(/0 decorative particles \(not records\)/)).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('lists records, caps the list and says how many more', async () => {
    mount();
    await screen.findByText(/Showing 600 of 600 records/);
    const list = within(screen.getByRole('region', { name: 'Records' }));
    expect(list.getAllByRole('button')).toHaveLength(40);
    expect(list.getByText('560 more — narrow the search to see them.')).toBeInTheDocument();
  });

  it('searches and filters by kind, and the counts follow', async () => {
    mount();
    const user = setup();
    await screen.findByText(/Showing 600 of 600/);
    await user.click(screen.getByRole('checkbox', { name: /Notes/ }));
    await user.click(screen.getByRole('checkbox', { name: /Tasks/ }));
    const status = screen.getByText(/records · /);
    const shown = Number(/Showing (\d+) of 600/.exec(status.textContent ?? '')![1]);
    expect(shown).toBeLessThan(600);
    expect(shown).toBeGreaterThan(0);
    await user.type(screen.getByLabelText('Search records'), 'zzz-no-such-record');
    expect(screen.getByText(/Showing 0 of 600/)).toBeInTheDocument();
    expect(screen.getByText('No records match.')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Search records'));
    await user.type(screen.getByLabelText('Search records'), 'meeting');
    const list = within(screen.getByRole('region', { name: 'Records' }));
    expect(list.getAllByRole('button').every((b) => /meeting/i.test(b.textContent ?? ''))).toBe(true);
  });

  it('shows where a record comes from, literally, with explicit links and why they exist', async () => {
    mount();
    const user = setup();
    await screen.findByText(/Showing 600 of 600/);
    expect(screen.getByText('Select a record in the list or the 3D view to see where it comes from.')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Search records'), 'Task to');
    const first = within(screen.getByRole('region', { name: 'Records' })).getAllByRole('button')[0]!;
    await user.click(first);
    const details = within(screen.getByRole('region', { name: 'Record details' }));
    expect(details.getByText('Kind')).toBeInTheDocument();
    expect(details.getByText('Tasks')).toBeInTheDocument();
    expect(details.getByText(/^task:syn-task-\d+$/)).toBeInTheDocument();
    expect(details.getByText('work-private')).toBeInTheDocument();
    expect(details.getByText(/stands for no real record/)).toBeInTheDocument();
    // Walk to a task that has a link and follow it.
    const buttons = within(screen.getByRole('region', { name: 'Records' })).getAllByRole('button');
    for (const b of buttons) {
      await user.click(b);
      if (within(screen.getByRole('region', { name: 'Record details' })).queryByText(/Explicit link · /)) break;
    }
    const linked = within(screen.getByRole('region', { name: 'Record details' }));
    expect(linked.getAllByText(/Explicit link · (The task records this meeting as its origin|The reminder is linked to this task)/).length).toBeGreaterThan(0);
    await user.click(linked.getAllByRole('button')[0]!);
    expect(within(screen.getByRole('region', { name: 'Record details' })).getByText(/^(Meetings|Reminders)$/)).toBeInTheDocument();
  });

  it('drops a selection that the filters now hide', async () => {
    mount();
    const user = setup();
    await screen.findByText(/Showing 600 of 600/);
    await user.click(within(screen.getByRole('region', { name: 'Records' })).getAllByRole('button')[0]!);
    expect(screen.queryByText('Select a record in the list or the 3D view to see where it comes from.')).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Search records'), 'zzz-no-such-record');
    expect(screen.getByText('Select a record in the list or the 3D view to see where it comes from.')).toBeInTheDocument();
  });

  it('does not simulate relationships or activity it cannot have', async () => {
    mount();
    await screen.findByText(/Showing 600 of 600/);
    const note = within(screen.getByRole('region', { name: 'Relationships and activity' }));
    expect(note.getByText(/Inferred, reviewed and disputed relationships, and a feed of real knowledge activity, need parts of the knowledge system that do not exist yet\./)).toBeInTheDocument();
    expect(screen.queryByText(/similar|related to|activity feed/i)).not.toBeInTheDocument();
  });

  it('a source that fails shows the error with a retry', async () => {
    const broken = { ...createSyntheticSource(), listNodes: vi.fn().mockRejectedValue(new Error('source unavailable')) };
    mount({ source: broken });
    expect(await screen.findByRole('alert')).toHaveTextContent('source unavailable');
  });
});

describe('Brain page with the 3D view', () => {
  it('passes the scene what the filters leave visible, a particle ceiling, links and reset', async () => {
    webgl.available = true;
    mount();
    const user = setup();
    expect(await screen.findByTestId('scene-stub')).toBeInTheDocument();
    expect(screen.getByRole('img')).toHaveAttribute('aria-label', expect.stringMatching(/same records for keyboard and screen reader use/));
    const first = () => sceneProps.at(-1)!;
    expect(first().nodes).toHaveLength(600);
    expect(first().visible.size).toBe(600);
    expect(first().particleCount).toBe(6000);
    expect(first().showAllLinks).toBe(false);
    const token = first().resetToken;

    await user.click(screen.getByRole('checkbox', { name: /Memories/ }));
    expect(first().visible.size).toBeLessThan(600);
    expect(first().nodes).toHaveLength(600); // dimmed, not removed
    await user.selectOptions(screen.getByLabelText('Detail'), 'low');
    expect(first().particleCount).toBe(1500);
    expect(screen.getByText(/1,500 decorative particles \(not records\)/)).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: 'Show all links' }));
    expect(first().showAllLinks).toBe(true);
    await user.click(screen.getByRole('button', { name: 'Reset view' }));
    expect(first().resetToken).toBe(token + 1);

    await user.click(within(screen.getByRole('region', { name: 'Records' })).getAllByRole('button')[0]!);
    expect(first().selectedId).not.toBeNull();
    act(() => first().onSelect(null));
    expect(first().selectedId).toBeNull();
  });

  it('starts light on a phone-width screen and when motion is reduced', async () => {
    webgl.available = true;
    vi.stubGlobal('innerWidth', 390);
    mount();
    await screen.findByTestId('scene-stub');
    expect(sceneProps.at(-1)!.particleCount).toBe(1500);
    cleanup();
    vi.unstubAllGlobals();
    sceneProps.length = 0;
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} }));
    mount();
    await screen.findAllByTestId('scene-stub');
    expect(sceneProps.at(-1)!.reducedMotion).toBe(true);
    expect(sceneProps.at(-1)!.particleCount).toBe(1500);
  });
});

describe('Brain route', () => {
  it('loads on demand inside the signed-in layout', async () => {
    createFakeHub({ status: SAMPLE_STATUS });
    renderApp('#/brain');
    expect(await screen.findByRole('heading', { name: 'Brain' })).toBeInTheDocument();
    expect(await screen.findByText(/Showing 600 of 600/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Brain' })).toHaveAttribute('aria-current', 'page');
  });
});
