import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEEP_POLL_MS } from '../src/features/meetings/DeepReview';
import { createFakeHub, jsonResponse, type FakeMeeting } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

const status = { ...SAMPLE_STATUS, default_user_id: 'owner-user', owner_bound: true };

// Cases from the legacy tab (clients/operator-ui/tests/{meeting_outputs,deep_review,workspace}.test.cjs).
function meeting(over: Partial<FakeMeeting> = {}): FakeMeeting {
  return {
    id: 'm1', title: '<b>Weekly</b> sync', status: 'complete', created_at: '2030-01-02T07:00:00Z', project_scope: 'apollo', participants: ['Hariz', 'Alice'],
    context: 'ctx <i>text</i>', duration_seconds: 125,
    transcript_segments: [
      { start: 0, end: 3.2, text: 'hello gemini' },
      { start: 3.2, end: 6, text: 'we ship friday' },
      { start: 6, end: 9, text: 'bye' },
    ],
    diarization_segments: [{ start: 0, end: 6, speaker: 'SPEAKER_00' }, { start: 6, end: 9, speaker: 'SPEAKER_01' }],
    aligned_segments: [{ speaker: 'SPEAKER_00' }, { speaker: 'SPEAKER_00' }, { speaker: 'SPEAKER_01' }],
    audio_gaps: { seconds: 3, segments: [2] },
    ...over,
  };
}
function hub(list: FakeMeeting[] = [meeting()]) {
  return createFakeHub({ status, meetings: list });
}
const setup = () => userEvent.setup();

afterEach(() => vi.unstubAllGlobals());

describe('Meetings list', () => {
  it('lists records with status wording, description, silent marker; text is literal; search filters', async () => {
    hub([
      meeting({ description: 'Status <u>round</u>.' }),
      meeting({ id: 'm2', title: 'Aligning one', status: 'aligning', audio_gaps: null }),
      meeting({ id: 'm3', title: 'Broken', status: 'failed', audio_gaps: null }),
      meeting({ id: 'm4', title: 'Running', status: 'transcribing', audio_gaps: null }),
    ]);
    const { container } = renderApp('#/meetings');
    const user = setup();
    expect(await screen.findByText('<b>Weekly</b> sync')).toBeInTheDocument();
    expect(container.querySelector('b, u, i')).toBeNull();
    expect(screen.getByText('Status <u>round</u>.')).toBeInTheDocument();
    expect(screen.getByText('Complete')).toBeInTheDocument();
    expect(screen.getByText('Ready')).toBeInTheDocument(); // aligning
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Transcribing')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Part of this recording has no audio' })).toBeInTheDocument();
    // A running meeting can be cancelled, not deleted; a finished one the reverse. "Ready" (aligning) allows both.
    expect(screen.queryByRole('button', { name: 'Delete Running' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete Aligning one' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Cancel processing' })).toHaveLength(2);
    await user.type(screen.getByLabelText('Find a meeting'), 'aligning');
    expect(screen.queryByText('<b>Weekly</b> sync')).not.toBeInTheDocument();
    expect(screen.getByText('Aligning one')).toBeInTheDocument();
  });

  it('deletes after confirmation, and clears failed and cancelled ones together', async () => {
    const h = hub([meeting(), meeting({ id: 'm2', title: 'Broken', status: 'failed', audio_gaps: null }), meeting({ id: 'm3', title: 'Dropped', status: 'cancelled', audio_gaps: null })]);
    renderApp('#/meetings');
    const user = setup();
    await screen.findByText('Broken');
    await user.click(screen.getByRole('button', { name: 'Delete Broken' }));
    let dialog = within(await screen.findByRole('dialog', { hidden: true }));
    expect(dialog.getByText(/“Broken” will be removed with its recording, transcript, speaker names, corrections, summary and minutes/)).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Cancel' }));
    expect(h.calls.some((c) => c.startsWith('DELETE'))).toBe(false);

    await user.click(screen.getByRole('button', { name: 'Delete failed and cancelled (2)' }));
    dialog = within(await screen.findByRole('dialog', { hidden: true }));
    expect(dialog.getByText(/removes 2 meetings and their recordings/)).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(h.calls).toContain('DELETE /meetings/m2'));
    await waitFor(() => expect(h.calls).toContain('DELETE /meetings/m3'));
    await waitFor(() => expect(screen.queryByText('Broken')).not.toBeInTheDocument());
    expect(screen.getByText('<b>Weekly</b> sync')).toBeInTheDocument();
  });

  it('cancels a running meeting', async () => {
    const h = hub([meeting({ id: 'm4', title: 'Running', status: 'transcribing', audio_gaps: null })]);
    renderApp('#/meetings');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Cancel processing' }));
    await waitFor(() => expect(h.calls).toContain('POST /meetings/m4/cancel'));
    expect(await screen.findByText('Cancelled')).toBeInTheDocument();
  });

  it('shows an empty state and a load error', async () => {
    const h = hub([]);
    renderApp('#/meetings');
    expect(await screen.findByText('No meetings uploaded yet.')).toBeInTheDocument();
    h.respond((c) => c === 'GET /meetings', () => jsonResponse({ detail: 'Companion core unavailable' }, 502));
    await setup().click(screen.getByRole('button', { name: 'Refresh meeting records' }));
    expect(await screen.findByText('Companion core unavailable')).toBeInTheDocument();
  });
});

describe('Upload', () => {
  it('uploads a chosen file with its fields and refreshes the list', async () => {
    const h = hub([]);
    renderApp('#/meetings');
    const user = setup();
    await screen.findByText('No meetings uploaded yet.');
    await user.click(screen.getByRole('button', { name: 'Upload meeting' }));
    await user.type(screen.getByLabelText('Title'), 'Standup');
    await user.type(screen.getByLabelText(/Participants/), 'Hariz, Alice');
    await user.click(screen.getByRole('button', { name: 'Upload meeting' }));
    expect(await screen.findByText('Record a clip or choose a recording to upload')).toBeInTheDocument();
    expect(h.calls.some((c) => c === 'POST /meetings')).toBe(false);
    const file = new File(['RIFF'], 'meeting.wav', { type: 'audio/wav' });
    await user.upload(screen.getByLabelText(/Recording file/), file);
    await user.click(screen.getByRole('button', { name: 'Upload meeting' }));
    expect(await screen.findByText('Uploaded.')).toBeInTheDocument();
    const sent = h.bodies.find((b) => b.call === 'POST /meetings')!.body as Record<string, string>;
    expect(sent).toMatchObject({ title: 'Standup', participants: 'Hariz, Alice', audio: 'file:meeting.wav' });
    expect(await screen.findByText('Standup')).toBeInTheDocument();
    expect(screen.getByLabelText('Title')).toHaveValue('');
  });

  it('records a clip in the browser and uploads it as recording.webm', async () => {
    const h = hub([]);
    const stop = vi.fn();
    const listeners: Record<string, (e: unknown) => void> = {};
    class FakeRecorder {
      static isTypeSupported = () => true;
      state = 'inactive';
      mimeType = 'audio/webm;codecs=opus';
      addEventListener(name: string, fn: (e: unknown) => void) { listeners[name] = fn; }
      start() { this.state = 'recording'; }
      stop() { this.state = 'inactive'; listeners.dataavailable?.({ data: new Blob(['abc']) }); listeners.stop?.({}); }
    }
    vi.stubGlobal('MediaRecorder', FakeRecorder);
    vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop }] }) } });
    renderApp('#/meetings');
    const user = setup();
    await screen.findByText('No meetings uploaded yet.');
    await user.click(screen.getByRole('button', { name: 'Start recording' }));
    expect(await screen.findByRole('button', { name: 'Stop recording' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Stop recording' }));
    expect(await screen.findByText(/Recorded clip ready/)).toBeInTheDocument();
    expect(stop).toHaveBeenCalled(); // the microphone is released
    expect(screen.getByLabelText(/Recording file/)).toBeDisabled();
    await user.type(screen.getByLabelText('Title'), 'Voice memo');
    await user.click(screen.getByRole('button', { name: 'Upload meeting' }));
    expect(await screen.findByText('Uploaded.')).toBeInTheDocument();
    expect((h.bodies.find((b) => b.call === 'POST /meetings')!.body as Record<string, string>).audio).toBe('file:recording.webm');
  });

  it('says so when the browser cannot record', async () => {
    hub([]);
    vi.stubGlobal('MediaRecorder', undefined);
    renderApp('#/meetings');
    expect(await screen.findByText('Recording from the browser is not supported here — upload a file instead.')).toBeInTheDocument();
  });
});

describe('Meeting detail', () => {
  it('shows metadata, the silent-gap warning and speaker-labelled transcript lines, all literal', async () => {
    hub();
    const { container } = renderApp('#/meetings/m1');
    expect(await screen.findByText(/Status: Complete · Project: apollo · Participants: Hariz, Alice · Duration: 2:05/)).toBeInTheDocument();
    expect(screen.getByText('ctx <i>text</i>')).toBeInTheDocument();
    expect(screen.getByText(/0:03 of this recording has no audio/)).toBeInTheDocument();
    expect(container.querySelector('i, b')).toBeNull();
    // A speaker chip appears where the speaker changes, not on every line.
    expect(screen.getAllByRole('button', { name: /^Rename Speaker/ }).map((b) => b.textContent)).toEqual(['Speaker 1', 'Speaker 2']);
    expect(screen.getByText(/0:00–0:03 hello gemini/)).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'No audio was recorded for most of this line' })).toBeInTheDocument();
    expect(screen.getByText(/0:00–0:06 SPEAKER_00/)).toBeInTheDocument(); // raw speaker segments
    expect(document.querySelector('audio')).toHaveAttribute('src', '/meetings/m1/audio');
  });

  it('renames a speaker and clears the name', async () => {
    const h = hub();
    renderApp('#/meetings/m1');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Rename Speaker 1' }));
    let dialog = within(await screen.findByRole('dialog', { name: 'Name this speaker', hidden: true }));
    expect(dialog.getByRole('heading', { name: 'Who is Speaker 1?' })).toBeInTheDocument();
    await user.type(dialog.getByLabelText('Name'), 'Hariz');
    await user.click(dialog.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(h.bodies.find((b) => b.call === 'PUT /meetings/m1/speakers')?.body).toEqual({ names: { SPEAKER_00: 'Hariz' } }));
    await user.click(await screen.findByRole('button', { name: 'Rename Hariz' }));
    dialog = within(await screen.findByRole('dialog', { name: 'Name this speaker', hidden: true }));
    await user.click(dialog.getByRole('button', { name: 'Clear name' }));
    await waitFor(() => expect(h.data.meetings[0]!.speaker_names).toEqual({}));
    expect(await screen.findByRole('button', { name: 'Rename Speaker 1' })).toBeInTheDocument();
  });

  it('edits a line, shows (edited), and restores the original', async () => {
    const h = hub();
    renderApp('#/meetings/m1');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Edit line at 0:00' }));
    let dialog = within(await screen.findByRole('dialog', { name: 'Edit line', hidden: true }));
    const text = dialog.getByLabelText('Text');
    expect(text).toHaveValue('hello gemini');
    await user.clear(text);
    await user.type(text, 'hello Gemini');
    await user.click(dialog.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(h.bodies.find((b) => b.call === 'PUT /meetings/m1/corrections/0')?.body).toEqual({ text: 'hello Gemini' }));
    expect(await screen.findByText(/hello Gemini \(edited\)/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Edit line at 0:00' }));
    dialog = within(await screen.findByRole('dialog', { name: 'Edit line', hidden: true }));
    expect(dialog.getByText('Original: hello gemini')).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Restore original' }));
    await waitFor(() => expect(h.calls).toContain('DELETE /meetings/m1/corrections/0'));
    await waitFor(() => expect(screen.queryByText(/\(edited\)/)).not.toBeInTheDocument());
  });

  it('plays from a line: sets the player position', async () => {
    hub();
    renderApp('#/meetings/m1');
    const user = setup();
    const line = await screen.findByText(/0:03–0:06 we ship friday/);
    const audio = document.querySelector('audio') as HTMLAudioElement;
    audio.play = vi.fn().mockResolvedValue(undefined);
    await user.click(line);
    expect(audio.currentTime).toBeCloseTo(3.2);
    expect(audio.play).toHaveBeenCalled();
  });

  it('edits the title and description, and rewrites them from the transcript', async () => {
    const h = hub();
    renderApp('#/meetings/m1');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Edit title' }));
    let dialog = within(await screen.findByRole('dialog', { name: 'Meeting title', hidden: true }));
    await user.clear(dialog.getByLabelText('Title'));
    await user.type(dialog.getByLabelText('Title'), 'Weekly review');
    await user.type(dialog.getByLabelText('Description'), 'Status round.');
    await user.click(dialog.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(h.bodies.find((b) => b.call === 'PUT /meetings/m1/title')?.body).toEqual({ title: 'Weekly review', description: 'Status round.' }));
    expect((await screen.findAllByText('Status round.')).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: 'Edit title' }));
    dialog = within(await screen.findByRole('dialog', { name: 'Meeting title', hidden: true }));
    await user.click(dialog.getByRole('button', { name: 'Write again from the transcript' }));
    await waitFor(() => expect(h.calls).toContain('POST /meetings/m1/describe'));
    expect((await screen.findAllByText('Generated description.')).length).toBeGreaterThan(0);
  });

  it('shows the technical error for a failed meeting, collapsed', async () => {
    hub([meeting({ status: 'failed', error_detail: 'sidecar exploded <b>x</b>', transcript_segments: null, audio_gaps: null })]);
    const { container } = renderApp('#/meetings/m1');
    expect(await screen.findByText('Processing failed. Open details for the technical error.')).toBeInTheDocument();
    expect(container.querySelector('details')).not.toHaveAttribute('open');
    expect(screen.getByText('sidecar exploded <b>x</b>')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'What to do with this meeting' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete meeting' })).toBeInTheDocument();
  });

  it('Close returns to the add-meeting form', async () => {
    hub();
    renderApp('#/meetings/m1');
    await setup().click(await screen.findByRole('button', { name: 'Close' }));
    expect(await screen.findByRole('heading', { name: 'Add a meeting' })).toBeInTheDocument();
  });
});

describe('Summary and minutes', () => {
  it('writes the summary with the local model the first time it is opened, with its tier label; rerun and clear', async () => {
    const h = hub();
    renderApp('#/meetings/m1');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Summary' }));
    await waitFor(() => expect(h.bodies.find((b) => b.call === 'POST /meetings/m1/outputs/summary')?.body).toEqual({ model: 'local' }));
    expect(await screen.findByText('Generated summary via local')).toBeInTheDocument();
    expect(screen.getByText(/Written by the local model/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/Rerun with/), 'cloud');
    await user.click(screen.getByRole('button', { name: 'Rerun' }));
    expect(await screen.findByText('Generated summary via cloud')).toBeInTheDocument();
    expect(screen.getByText(/Written by the cloud model/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear' }));
    await waitFor(() => expect(h.calls).toContain('DELETE /meetings/m1/outputs/summary'));
    expect(await screen.findByText('No summary yet.')).toBeInTheDocument();
  });

  it('does not rewrite an existing output on opening, and reports a generation failure', async () => {
    const h = hub([meeting({ minutes: { text: 'Existing minutes', tier: 'deep', generated_at: '2030-01-02T08:00:00Z' } })]);
    renderApp('#/meetings/m1');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Minutes' }));
    expect(await screen.findByText('Existing minutes')).toBeInTheDocument();
    expect(screen.getByText(/Written by the larger local model/)).toBeInTheDocument();
    expect(h.calls.some((c) => c.startsWith('POST /meetings/m1/outputs'))).toBe(false);
    h.respond((c) => c.startsWith('POST /meetings/m1/outputs'), () => jsonResponse({ detail: 'the language model is unavailable right now' }, 503));
    await user.click(screen.getByRole('button', { name: 'Rerun' }));
    expect(await screen.findByText('the language model is unavailable right now')).toBeInTheDocument();
  });

  it('Use as context hands the meeting to the chat', async () => {
    hub();
    renderApp('#/meetings/m1');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Use as context' }));
    expect(await screen.findByText(/Meeting context:/)).toBeInTheDocument();
    expect(screen.getByText('<b>Weekly</b> sync', { selector: 'strong' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Stop using this meeting as context' }));
    expect(screen.queryByText(/Meeting context:/)).not.toBeInTheDocument();
  });
});

describe('Suggested corrections', () => {
  const result = {
    suggestions: [
      { original: 'gemini', suggested: 'Gemini', confidence: 'high', reason: 'Same letters as a key term' },
      { original: 'friday', suggested: 'Friday', confidence: 'guess', reason: 'Day name' },
      { original: 'friday', suggested: 'Friday', confidence: 'guess', reason: 'Day name' },
    ],
    terms_used: 3,
    truncated: false,
  };

  it('groups identical suggestions, applies one across the meeting, and dismisses another', async () => {
    const h = hub();
    h.data.suggestions = result;
    renderApp('#/meetings/m1');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Suggest corrections' }));
    expect(await screen.findByText('Checked against 3 terms.')).toBeInTheDocument();
    expect(screen.getByText('gemini → Gemini')).toBeInTheDocument();
    expect(screen.getByText('High confidence: same letters as your term')).toBeInTheDocument();
    expect(screen.getByText('Model guess: check before applying')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Change all 2' }));
    await waitFor(() => expect(h.bodies.find((b) => b.call === 'POST /meetings/m1/corrections/replace')?.body).toEqual({ find: 'friday', replace: 'Friday' }));
    expect(await screen.findByText('Changed 1 place.')).toBeInTheDocument();
    expect(screen.queryByText('friday → Friday')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByText('gemini → Gemini')).not.toBeInTheDocument();
  });

  it('says so when nothing is found or part of the meeting could not be checked', async () => {
    const h = hub();
    h.data.suggestions = { suggestions: [], terms_used: 0, truncated: false };
    renderApp('#/meetings/m1');
    const user = setup();
    await user.click(await screen.findByRole('button', { name: 'Suggest corrections' }));
    expect(await screen.findByText('No likely mistakes found. Add key terms to catch more.')).toBeInTheDocument();
    h.data.suggestions = { suggestions: [], terms_used: 2, truncated: true };
    await user.click(screen.getByRole('button', { name: 'Suggest corrections' }));
    expect(await screen.findByText('Some parts of the meeting could not be checked. Run again to retry.')).toBeInTheDocument();
  });
});

describe('Deep local review', () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'], shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it('warns first, starts only after confirmation, shows the banner everywhere, and announces the end', async () => {
    const h = hub();
    renderApp('#/meetings/m1');
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTimeAsync(ms) });
    await screen.findByRole('button', { name: 'Suggest corrections' });
    await user.selectOptions(screen.getByLabelText('Model'), 'deep');
    await user.click(screen.getByRole('button', { name: 'Suggest corrections' }));
    const dialog = within(await screen.findByRole('dialog', { name: 'Reachy will be unavailable', hidden: true }));
    expect(dialog.getByText(/unavailable for about 6 minutes/)).toBeInTheDocument();
    await user.click(dialog.getByRole('button', { name: 'Cancel' }));
    expect(h.calls.some((c) => c.includes('deep-review') && c.startsWith('POST'))).toBe(false);

    await user.click(screen.getByRole('button', { name: 'Suggest corrections' }));
    await user.click(within(await screen.findByRole('dialog', { name: 'Reachy will be unavailable', hidden: true })).getByRole('button', { name: 'Start deep review' }));
    await waitFor(() => expect(h.calls).toContain('POST /meetings/m1/corrections/deep-review'));
    expect(await screen.findByText('Reachy is unavailable: deep review in progress.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Suggest corrections' })).toBeDisabled();
    await user.click(screen.getByRole('link', { name: 'Overview' })); // the banner follows the owner around
    expect(screen.getByText('Reachy is unavailable: deep review in progress.')).toBeInTheDocument();

    const job = h.data.deepJobs[0];
    Object.assign(job, { status: 'done', reachy_unavailable: false, reachy_online: true, result: { suggestions: [], terms_used: 1, truncated: false } });
    await act(async () => { await vi.advanceTimersByTimeAsync(DEEP_POLL_MS + 100); });
    expect(await screen.findByText('The deep review of "<b>Weekly</b> sync" is complete. Reachy is back online.')).toBeInTheDocument();
    expect(screen.queryByText('Reachy is unavailable: deep review in progress.')).not.toBeInTheDocument();
  });

  it('refuses when deep local is not available', async () => {
    const h = hub();
    h.data.deepInfo = { available: false, reason: 'the model manager is not configured', eta_seconds: 330 };
    renderApp('#/meetings/m1');
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTimeAsync(ms) });
    await screen.findByRole('button', { name: 'Suggest corrections' });
    await user.selectOptions(screen.getByLabelText('Model'), 'deep');
    await user.click(screen.getByRole('button', { name: 'Suggest corrections' }));
    expect(await screen.findByText('Deep local is unavailable: the model manager is not configured.')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Reachy will be unavailable' })).not.toBeInTheDocument();
  });

  it('resumes a review already running when the Meetings page opens', async () => {
    const h = hub();
    h.data.deepJobs.push({ id: 'job9', status: 'running', stage: 'Reloading the standard model', task: 'summary', meeting_id: 'm1', meeting_title: 'X', reachy_unavailable: true, reachy_online: false, error: null, result: null });
    renderApp('#/meetings');
    expect(await screen.findByText('Reloading the standard model')).toBeInTheDocument();
  });
});
