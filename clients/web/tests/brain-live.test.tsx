import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SceneProps } from '../src/features/brain/BrainScene';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

const sceneProps: SceneProps[] = [];
vi.mock('../src/features/brain/BrainScene', () => ({
  default: (props: SceneProps) => {
    sceneProps.push(props);
    return <div data-testid="scene-stub" />;
  },
}));
const webgl = vi.hoisted(() => ({ available: true }));
vi.mock('../src/features/brain/webgl', async (original) => ({ ...(await original<typeof import('../src/features/brain/webgl')>()), webglAvailable: () => webgl.available }));

const node = (type: string, id: string, title: string, over: Record<string, unknown> = {}) => ({
  id: `${type}:${id}`, type, title, excerpt: `${title} text`, observed_at: '2030-01-02T07:00:00Z', source_ref: { kind: type, id },
  sensitivity: 'work-private', project_scope: null, ...over,
});
const records = () => [
  node('note', 'n1', 'Groceries <b>list</b>'),
  node('task', 't1', 'Send the summary'),
  node('meeting', 'm1', 'Weekly sync'),
  node('memory', 'k1', 'Falcon-7B is the default'),
  node('document', 'd1', 'Architecture'),
  node('reminder', 'r1', 'Call Lisa'),
];

beforeEach(() => {
  sceneProps.length = 0;
  webgl.available = true;
});
afterEach(() => vi.unstubAllGlobals());
const setup = () => userEvent.setup();

describe('Brain with the owner’s records', () => {
  it('reads from the hub by default, says it is the owner’s data, and shows the records literally', async () => {
    const hub = createFakeHub({ status: SAMPLE_STATUS });
    hub.data.brain.nodes = records();
    const { container } = renderApp('#/brain');
    expect(await screen.findByText(/Showing 6 of 6 records/)).toBeInTheDocument();
    expect(screen.getByText(/Your records\./)).toBeInTheDocument();
    expect(screen.getByText(/Forgotten, expired, deleted and sensitive records are not shown or counted/)).toBeInTheDocument();
    expect(screen.queryByText(/Synthetic demonstration data/)).not.toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Your records (read-only)' })).toBeChecked();
    expect(screen.getByText('Groceries <b>list</b>')).toBeInTheDocument();
    expect(container.querySelector('aside b')).toBeNull();
    expect(hub.calls.filter((c) => c.startsWith('GET /brain/nodes?'))).toEqual(['GET /brain/nodes?limit=200']);
    await screen.findByTestId('scene-stub');
    expect(sceneProps.at(-1)!.nodes).toHaveLength(6);
    expect(screen.getByText(/Showing 6 of 6 records · 0 explicit links/)).toBeInTheDocument();
  });

  it('places a record the same way every time, by its id alone', async () => {
    const hub = createFakeHub({ status: SAMPLE_STATUS });
    hub.data.brain.nodes = records();
    const view = renderApp('#/brain');
    await screen.findByText(/Showing 6 of 6/);
    await screen.findByTestId('scene-stub');
    const first = sceneProps.at(-1)!.nodes.map((n) => [n.id, ...n.position]);
    view.unmount();
    sceneProps.length = 0;
    renderApp('#/brain');
    await screen.findByText(/Showing 6 of 6/);
    await screen.findByTestId('scene-stub');
    expect(sceneProps.at(-1)!.nodes.map((n) => [n.id, ...n.position])).toEqual(first);
    // Same id, same place, whatever else exists; a different id, a different place.
    const { positionFor } = await import('../src/features/brain/layout');
    expect(positionFor('note:n1', 'note')).toEqual(positionFor('note:n1', 'note'));
    expect(positionFor('note:n1', 'note')).not.toEqual(positionFor('note:n2', 'note'));
  });

  it('pages through a large collection in bounded requests with the server’s cursor', async () => {
    const hub = createFakeHub({ status: SAMPLE_STATUS });
    hub.data.brain.nodes = Array.from({ length: 450 }, (_, i) => node('task', `t${i}`, `Task ${i}`));
    renderApp('#/brain');
    expect(await screen.findByText(/Showing 450 of 450/)).toBeInTheDocument();
    expect(hub.calls.filter((c) => c.startsWith('GET /brain/nodes?'))).toEqual(['GET /brain/nodes?limit=200', 'GET /brain/nodes?limit=200&cursor=200', 'GET /brain/nodes?limit=200&cursor=400']);
  });

  it('re-checks a record when it is chosen, and drops one that has gone since the list was read', async () => {
    const hub = createFakeHub({ status: SAMPLE_STATUS });
    hub.data.brain.nodes = records();
    renderApp('#/brain');
    const user = setup();
    await screen.findByText(/Showing 6 of 6/);
    hub.data.brain.hidden.add('note:n1'); // forgotten or deleted elsewhere after the list loaded
    await user.click(within(screen.getByRole('region', { name: 'Records' })).getByRole('button', { name: /Groceries/ }));
    expect(await screen.findByText(/That record is no longer available/)).toBeInTheDocument();
    expect(hub.calls).toContain('GET /brain/nodes/note/n1');
    await waitFor(() => expect(screen.getByText(/Showing 5 of 5/)).toBeInTheDocument());
    expect(screen.queryByText('Groceries <b>list</b>')).not.toBeInTheDocument();
    expect(screen.getByText('Select a record in the list or the 3D view to see where it comes from.')).toBeInTheDocument();
  });

  it('offers a way to open a record in its own screen where one exists, and explains the absence of links', async () => {
    const hub = createFakeHub({ status: SAMPLE_STATUS });
    hub.data.brain.nodes = records();
    renderApp('#/brain');
    const user = setup();
    await screen.findByText(/Showing 6 of 6/);
    const list = within(screen.getByRole('region', { name: 'Records' }));
    await user.click(list.getByRole('button', { name: /Weekly sync/ }));
    const details = within(screen.getByRole('region', { name: 'Record details' }));
    expect(details.getByRole('link', { name: 'Open in Meetings' })).toHaveAttribute('href', '#/meetings/m1');
    expect(details.getByText(/No structured links between these kinds of record exist yet, so none are drawn\. Nothing is inferred\./)).toBeInTheDocument();
    await user.click(list.getByRole('button', { name: /Falcon-7B/ }));
    expect(within(screen.getByRole('region', { name: 'Record details' })).queryByRole('link', { name: /^Open in/ })).not.toBeInTheDocument(); // no memory screen yet
  });

  it('switches to the synthetic demonstration and back, clearing the selection', async () => {
    const hub = createFakeHub({ status: SAMPLE_STATUS });
    hub.data.brain.nodes = records();
    renderApp('#/brain');
    const user = setup();
    await screen.findByText(/Showing 6 of 6/);
    await user.click(within(screen.getByRole('region', { name: 'Records' })).getAllByRole('button')[0]!);
    await user.click(screen.getByRole('radio', { name: 'Synthetic demonstration' }));
    expect(await screen.findByText(/Showing 600 of 600/)).toBeInTheDocument();
    expect(screen.getByText(/Synthetic demonstration data\./)).toBeInTheDocument();
    expect(screen.getByText('Select a record in the list or the 3D view to see where it comes from.')).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'Your records (read-only)' }));
    expect(await screen.findByText(/Showing 6 of 6/)).toBeInTheDocument();
  });

  it('says so when there are no records, and when the hub cannot reach them', async () => {
    const hub = createFakeHub({ status: SAMPLE_STATUS });
    renderApp('#/brain');
    expect(await screen.findByText(/There are no records to show yet/)).toBeInTheDocument();
    hub.respond((c) => c.startsWith('GET /brain/'), () => jsonResponse({ detail: 'Knowledge view unavailable' }, 502));
    await setup().click(screen.getByRole('button', { name: 'Refresh records' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Knowledge view unavailable');
  });

  it('keeps nothing of the owner’s records after the page is left, and nothing in browser storage', async () => {
    const hub = createFakeHub({ status: SAMPLE_STATUS });
    hub.data.brain.nodes = records();
    const { client } = renderApp('#/brain');
    const user = setup();
    await screen.findByText(/Showing 6 of 6/);
    await user.click(screen.getByRole('link', { name: 'Overview' }));
    await waitFor(() => expect(client.getQueryCache().findAll({ queryKey: ['brain'] })).toHaveLength(0));
    expect(JSON.stringify({ ...window.localStorage }) + JSON.stringify({ ...window.sessionStorage })).not.toMatch(/Groceries|Falcon/);
  });

  it('a read of the records that finishes after logout is discarded', async () => {
    const hub = createFakeHub({ status: SAMPLE_STATUS });
    hub.data.brain.nodes = records();
    const pending = hub.hold((c) => c.startsWith('GET /brain/nodes?'), { ignoreAbort: true });
    const { client } = renderApp('#/brain');
    const user = setup();
    await waitFor(() => expect(pending).toHaveLength(1));
    await user.click(screen.getByRole('button', { name: 'Log out' }));
    await screen.findByRole('heading', { name: 'Sign in to Reachy' });
    pending[0]!.resolve(jsonResponse({ nodes: records(), next: null, truncated: false }));
    await new Promise((r) => setTimeout(r, 50));
    expect(document.body.textContent).not.toMatch(/Groceries|Falcon/);
    expect(client.getQueryCache().getAll().filter((q) => q.state.data !== undefined)).toHaveLength(0);
  });
});
