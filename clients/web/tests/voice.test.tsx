import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { OVERVIEW_POLL_MS, RENEW_MS, WAKE_POLL_MS } from '../src/features/voice/VoiceProvider';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

const status = { ...SAMPLE_STATUS, default_user_id: 'owner-user', owner_bound: true };
const wait = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
const count = (calls: string[], call: string) => calls.filter((c) => c === call).length;

beforeEach(() => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'], shouldAdvanceTime: true }));
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
const setup = () => userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTimeAsync(ms) });
const logout = (user: ReturnType<typeof setup>) => user.click(screen.getByRole('button', { name: 'Log out' }));

describe('Robot microphone', () => {
  it('starts listening for the chosen robot as the owner, renews the lease, and stops', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/settings/voice');
    const user = setup();
    expect(await screen.findByText('Off')).toBeInTheDocument();
    expect(screen.getByText(/Reachy does not recognise who is speaking/)).toBeInTheDocument();
    await user.click(await screen.findByRole('button', { name: 'Start listening' }));
    expect(await screen.findByText('Listening — speak now')).toBeInTheDocument();
    expect(hub.bodies.find((b) => b.call === 'POST /robot-voice/start')?.body).toEqual({ robot_id: 'desk', user_id: 'owner-user' });
    expect(screen.getByRole('button', { name: 'Start listening' })).toBeDisabled();
    expect(screen.getAllByLabelText('Robot')[0]).toBeDisabled();

    await wait(RENEW_MS * 3 + 100);
    expect(count(hub.calls, 'POST /robot-voice/renew')).toBeGreaterThanOrEqual(3);
    expect(hub.bodies.filter((b) => b.call === 'POST /robot-voice/renew').every((b) => (b.body as { voice_session_id: string }).voice_session_id === 'vs1')).toBe(true);

    await user.click(screen.getByRole('button', { name: 'Stop' }));
    expect(await screen.findByText('Off')).toBeInTheDocument();
    expect(screen.getByText(/Stopped: Stopped by owner/)).toBeInTheDocument();
    const renewals = count(hub.calls, 'POST /robot-voice/renew');
    await wait(RENEW_MS * 3);
    expect(count(hub.calls, 'POST /robot-voice/renew')).toBe(renewals); // the lease is no longer renewed
  });

  it('keeps renewing the lease while the owner is on another page, and stops when they sign out', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/settings/voice');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Start listening' }));
    await screen.findByText('Listening — speak now');
    await user.click(screen.getByRole('link', { name: 'To Do' }));
    const before = count(hub.calls, 'POST /robot-voice/renew');
    await wait(RENEW_MS * 4);
    expect(count(hub.calls, 'POST /robot-voice/renew')).toBeGreaterThan(before);

    await logout(user);
    const after = count(hub.calls, 'POST /robot-voice/renew');
    await wait(RENEW_MS * 4);
    expect(count(hub.calls, 'POST /robot-voice/renew')).toBe(after); // the hub ends the session on logout; nothing keeps asking
  });

  it('shows spoken turns in the Chat transcript once, and does not replay a finished session found on load', async () => {
    const hub = createFakeHub({ status });
    hub.data.voiceSession = { voice_session_id: 'old', state: 'stopped', stop_reason: 'Stopped by owner', last_error: null, wake_started: false, turns: [{ turn: 1, transcript: 'an old question', outcome: 'spoken', reply: 'an old answer', reason: '' }] };
    renderApp('#/chat');
    const user = setup();
    await screen.findByRole('log', { name: 'Conversation' });
    await wait(50);
    expect(screen.queryByText('an old question')).not.toBeInTheDocument();

    // A new session opened elsewhere (the wake phrase) shows all of its turns as they arrive.
    hub.data.voiceSession = {
      voice_session_id: 'new', state: 'listening', stop_reason: null, last_error: null, wake_started: true,
      turns: [
        { turn: 1, transcript: 'what time is it', outcome: 'spoken', reply: 'It is nine.', reason: '' },
        { turn: 2, transcript: 'tell me a secret', outcome: 'withheld', reply: 'Not aloud.', reason: 'private' },
        { turn: 3, transcript: '', outcome: 'no_speech', reply: '', reason: '' },
      ],
    };
    await wait(OVERVIEW_POLL_MS + 200);
    expect(await screen.findByText('what time is it')).toBeInTheDocument();
    expect(screen.getAllByText('You · spoken to Reachy', { selector: 'strong' })).toHaveLength(2); // the silent third turn has no transcript
    expect(screen.getByText('Reachy · said aloud')).toBeInTheDocument();
    expect(screen.getByText('Reachy · not spoken (private)')).toBeInTheDocument();
    expect(screen.getByText('I heard a sound but no words. Try again.')).toBeInTheDocument();
    await wait(OVERVIEW_POLL_MS + 200);
    expect(screen.getAllByText('what time is it')).toHaveLength(1); // not appended again on the next poll
    void user;
  });

  it('cannot start for a robot without voice, and says why', async () => {
    const hub = createFakeHub({ status });
    hub.data.robots = [{ robot_id: 'desk', online: false, voice_capable: false, wake_capable: false, wake_armed: false, wake_counts: { candidates: 0, admitted: 0 } }];
    renderApp('#/settings/voice');
    expect(await screen.findByRole('option', { name: 'desk (offline)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start listening' })).toBeDisabled();
    expect(screen.getByText('Privacy mode on: not listening for “Hey Reachy”')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Turn off privacy mode' })).toBeDisabled(); // an offline robot cannot be armed
  });

  it('shows a refusal from the hub when starting fails', async () => {
    const hub = createFakeHub({ status });
    hub.respond((c) => c === 'POST /robot-voice/start', () => jsonResponse({ detail: 'Robot is not connected to the hub' }, 409));
    renderApp('#/settings/voice');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Start listening' }));
    expect(await screen.findByText(/Could not start listening: Robot is not connected to the hub/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start listening' })).toBeEnabled();
  });

  it('turns privacy mode off and on, and polls faster while “Hey Reachy” is armed', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/settings/voice');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Turn off privacy mode' }));
    expect(await screen.findByRole('button', { name: 'Turn on privacy mode' })).toBeInTheDocument();
    expect(hub.bodies.find((b) => b.call === 'POST /robot-voice/wake')?.body).toEqual({ robot_id: 'desk', armed: true, user_id: 'owner-user' });
    expect(screen.getByText('Privacy mode off: listening for “Hey Reachy”')).toBeInTheDocument();
    const before = count(hub.calls, 'GET /robot-voice');
    await wait(WAKE_POLL_MS * 3 + 100);
    expect(count(hub.calls, 'GET /robot-voice') - before).toBeGreaterThanOrEqual(2);
    await user.click(screen.getByRole('button', { name: 'Turn on privacy mode' }));
    expect(await screen.findByRole('button', { name: 'Turn off privacy mode' })).toBeInTheDocument();
    expect(hub.data.robots[0].wake_armed).toBe(false);
  });
});

describe('Conversational animations', () => {
  it('reads the robot’s settings, applies a change, and shows the result', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/settings/voice');
    const user = setup();
    const gestures = await screen.findByRole('checkbox', { name: 'Listening and thinking gestures' });
    await waitFor(() => expect(gestures).toBeEnabled());
    expect(gestures).not.toBeChecked();
    await user.click(gestures);
    await user.click(screen.getByRole('checkbox', { name: 'Head movement while speaking' }));
    await user.click(screen.getByRole('button', { name: 'Apply animation settings' }));
    await waitFor(() => expect(hub.data.motionWrites).toEqual([{ conversation_motion: true, speech_wobble: true }]));
    expect(await screen.findByText('Animation settings applied for the next conversation.')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Listening and thinking gestures' })).toBeChecked();
  });

  it('is locked while a conversation is active', async () => {
    const hub = createFakeHub({ status });
    hub.data.motion = { conversation_motion: true, speech_wobble: false, conversation_active: true };
    renderApp('#/settings/voice');
    expect(await screen.findByText('Stop listening, then refresh to change animations.')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Listening and thinking gestures' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Apply animation settings' })).toBeDisabled();
  });

  it('after a failed write, shows nothing as applied and asks for a fresh read', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/settings/voice');
    const user = setup();
    const gestures = await screen.findByRole('checkbox', { name: 'Listening and thinking gestures' });
    await waitFor(() => expect(gestures).toBeEnabled());
    hub.respond((c) => c.startsWith('PUT /robots/desk/settings/motion'), () => jsonResponse({ detail: 'Robot unreachable' }, 502));
    await user.click(gestures);
    await user.click(screen.getByRole('button', { name: 'Apply animation settings' }));
    expect(await screen.findByText("Robot unreachable. Refresh to check the robot's current settings.")).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Listening and thinking gestures' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Listening and thinking gestures' })).toBeDisabled();
    hub.clearOverrides();
    await user.click(screen.getByRole('button', { name: 'Refresh animation settings' }));
    await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Listening and thinking gestures' })).toBeEnabled());
  });

  it('says so when no robot is registered, and when the robot does not support animations', async () => {
    const hub = createFakeHub({ status });
    hub.data.robots = [];
    renderApp('#/settings/voice');
    expect(await screen.findByText('No robots registered.')).toBeInTheDocument();
    const second = createFakeHub({ status });
    second.data.motion = { error: 'unsupported' };
    renderApp('#/settings/voice');
    expect((await screen.findAllByText('Unexpected response from the hub: This robot does not support animation settings.')).length).toBeGreaterThan(0);
    void within;
  });
});
