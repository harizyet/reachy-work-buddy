import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, jsonResponse } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

vi.mock('../src/utils/download', () => ({ saveBlob: vi.fn() }));
import { saveBlob } from '../src/utils/download';

const status = { ...SAMPLE_STATUS, default_user_id: 'owner-user', owner_bound: true };
const setup = () => userEvent.setup();
const stopTrack = vi.fn();

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(saveBlob).mockReset();
  stopTrack.mockReset();
});

function fakeMedia() {
  const listeners: Record<string, (e: unknown) => void> = {};
  class FakeRecorder {
    static isTypeSupported = () => true;
    state = 'inactive';
    mimeType = 'audio/webm;codecs=opus'; // what Chromium reports
    addEventListener(name: string, fn: (e: unknown) => void) { listeners[name] = fn; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; listeners.dataavailable?.({ data: new Blob(['voice-bytes']) }); listeners.stop?.({}); }
  }
  vi.stubGlobal('MediaRecorder', FakeRecorder);
  const getUserMedia = vi.fn(async () => ({ getTracks: () => [{ stop: stopTrack }] }));
  vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia } });
  return getUserMedia;
}

async function confirmPassword(user: ReturnType<typeof setup>, password = 'correct-password') {
  await user.type(await screen.findByLabelText('Password'), password);
  await user.click(screen.getByRole('button', { name: 'Confirm password' }));
}

describe('Owner recognition benchmark dataset', () => {
  it('stays locked until the password is confirmed; a wrong password is refused and cleared', async () => {
    const hub = createFakeHub({ status });
    renderApp('#/settings/recognition');
    const user = setup();
    expect(await screen.findByText('Confirm your password to change benchmark collection or manage samples.')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Enable benchmark dataset collection' })).toBeDisabled();
    expect(await screen.findByRole('button', { name: 'Start recording' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Turn on camera' })).toBeDisabled();
    await confirmPassword(user, 'wrong');
    expect(await screen.findByText('Invalid password')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument(); // still signed in: a wrong password is not a lost session
    expect(hub.data.recognition.reauthenticated).toBe(false);

    await user.clear(screen.getByLabelText('Password'));
    await confirmPassword(user);
    expect(await screen.findByText('Password confirmed — expires in about 5 minute(s).')).toBeInTheDocument();
    expect((screen.getByLabelText('Password') as HTMLInputElement).value).toBe(''); // the password is not kept
    expect(screen.getByRole('checkbox', { name: 'Enable benchmark dataset collection' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Start recording' })).toBeDisabled(); // collection is still off
  });

  it('turns collection on, records a voice sample as a blob with its own type, lists it, deletes it', async () => {
    const hub = createFakeHub({ status });
    const getUserMedia = fakeMedia();
    renderApp('#/settings/recognition');
    const user = setup();
    await confirmPassword(user);
    await user.click(await screen.findByRole('checkbox', { name: 'Enable benchmark dataset collection' }));
    expect(await screen.findByText(/Benchmark dataset collection is on/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Start recording' }));
    expect(await screen.findByRole('button', { name: 'Stop recording' })).toBeInTheDocument();
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    await user.click(screen.getByRole('button', { name: 'Stop recording' }));
    expect(await screen.findByText('Voice sample saved.')).toBeInTheDocument();
    expect(hub.data.saves.find((s) => s.call === 'POST /benchmark/voice/samples')?.body).toEqual({ blob: { size: 11, type: 'audio/webm' } }); // the codecs parameter is dropped: the hub matches the type exactly
    expect(stopTrack).toHaveBeenCalled(); // the microphone is released
    expect(screen.getByText('1 sample(s), 11 B total')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^Delete voice sample from/ }));
    await waitFor(() => expect(hub.data.recognition.voice_samples).toHaveLength(0));
    expect((await screen.findAllByText('No samples recorded yet.')).length).toBe(2); // voice and face lists are both empty
  });

  it('captures a face photo as a JPEG and turns the camera off', async () => {
    const hub = createFakeHub({ status });
    hub.data.recognition.reauthenticated = true;
    hub.data.recognition.benchmark_enabled = true;
    hub.data.recognition.reauth_expires_in_seconds = 300;
    const getUserMedia = fakeMedia();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({ drawImage: vi.fn() })) as never;
    HTMLCanvasElement.prototype.toBlob = vi.fn((cb: BlobCallback, type?: string) => cb(new Blob(['jpegbytes'], { type }))) as never;
    renderApp('#/settings/recognition');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Turn on camera' }));
    expect(getUserMedia).toHaveBeenCalledWith({ video: { facingMode: 'user' } });
    expect(await screen.findByText('Camera on. Frame your face, then select Capture photo.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Capture photo' }));
    expect(await screen.findByText('Face sample saved.')).toBeInTheDocument();
    expect(hub.data.saves.find((s) => s.call === 'POST /benchmark/face/samples')?.body).toEqual({ blob: { size: 9, type: 'image/jpeg' } });
    await user.click(screen.getByRole('button', { name: 'Turn off camera' }));
    expect(stopTrack).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Turn on camera' })).toBeInTheDocument();
  });

  it('deletes all samples only after confirmation, and exports a dataset as a file', async () => {
    const hub = createFakeHub({ status });
    Object.assign(hub.data.recognition, { reauthenticated: true, benchmark_enabled: false, reauth_expires_in_seconds: 120 });
    hub.data.recognition.voice_samples = [{ sample_id: 'v1', captured_at: '2030-01-02T03:04:05Z', size_bytes: 2048 }];
    renderApp('#/settings/recognition');
    const user = setup();
    expect(await screen.findByText('1 sample(s), 2 KB total')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Export voice dataset' }));
    await waitFor(() => expect(saveBlob).toHaveBeenCalled());
    expect(vi.mocked(saveBlob).mock.calls[0]![1]).toBe('voice-benchmark-dataset.zip');
    await user.click(screen.getByRole('button', { name: 'Delete all voice samples' }));
    let dialog = within(await screen.findByRole('dialog', { name: /Delete all voice samples/, hidden: true }));
    await user.click(dialog.getByRole('button', { name: 'Cancel' }));
    expect(hub.data.recognition.voice_samples).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: 'Delete all voice samples' }));
    dialog = within(await screen.findByRole('dialog', { name: /Delete all voice samples/, hidden: true }));
    await user.click(dialog.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(hub.data.recognition.voice_samples).toHaveLength(0));
  });

  it('a refused upload because the confirmation ran out is explained, and keeps the sign-in', async () => {
    const hub = createFakeHub({ status });
    Object.assign(hub.data.recognition, { reauthenticated: true, benchmark_enabled: true, reauth_expires_in_seconds: 300 });
    fakeMedia();
    renderApp('#/settings/recognition');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Start recording' }));
    hub.respond((c) => c === 'POST /owner-recognition/benchmark/voice/samples', () => jsonResponse({ detail: 'Fresh password confirmation required' }, 401));
    await user.click(await screen.findByRole('button', { name: 'Stop recording' }));
    expect(await screen.findByText('Fresh password confirmation required')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Sign in to Reachy' })).not.toBeInTheDocument();
  });

  it('releases the microphone when the owner leaves the tab mid-recording', async () => {
    const hub = createFakeHub({ status });
    Object.assign(hub.data.recognition, { reauthenticated: true, benchmark_enabled: true, reauth_expires_in_seconds: 300 });
    fakeMedia();
    renderApp('#/settings/recognition');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Start recording' }));
    await screen.findByRole('button', { name: 'Stop recording' });
    await user.click(screen.getByRole('tab', { name: 'Accounts' }));
    expect(stopTrack).toHaveBeenCalled();
    void act;
  });

  it('releases the microphone and uploads nothing when the owner signs out mid-recording', async () => {
    const hub = createFakeHub({ status });
    Object.assign(hub.data.recognition, { reauthenticated: true, benchmark_enabled: true, reauth_expires_in_seconds: 300 });
    fakeMedia();
    renderApp('#/settings/recognition');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Start recording' }));
    await screen.findByRole('button', { name: 'Stop recording' });
    await user.click(screen.getByRole('button', { name: 'Log out' }));
    await screen.findByRole('heading', { name: 'Sign in to Reachy' });
    expect(stopTrack).toHaveBeenCalled();
    expect(hub.data.saves.some((s) => s.call.startsWith('POST /benchmark'))).toBe(false);
  });
});
