import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFakeHub, type FakeMeeting } from './fakeHub';
import { renderApp, SAMPLE_STATUS } from './helpers';

const status = { ...SAMPLE_STATUS, default_user_id: 'owner-user', owner_bound: true };
const meeting = (over: Partial<FakeMeeting> = {}): FakeMeeting => ({
  id: 'm1', title: 'Weekly sync', status: 'complete', created_at: '2030-01-02T07:00:00Z', participants: ['Hariz'], duration_seconds: 125,
  transcript_segments: [{ start: 0, end: 3, text: 'hello' }], diarization_segments: [{ start: 0, end: 3, speaker: 'SPEAKER_00' }], aligned_segments: [{ speaker: 'SPEAKER_00' }],
  summary: { text: 'Priya Shah proposed shipping on Friday.', tier: 'local', generated_at: '2030-01-02T07:30:00Z' }, ...over,
});
function hub(opts: { enabled?: boolean; meetingOver?: Partial<FakeMeeting> } = {}) {
  const h = createFakeHub({ status, meetings: [meeting(opts.meetingOver)] });
  h.data.email.enabled = opts.enabled ?? true;
  return h;
}
afterEach(() => vi.unstubAllGlobals());

async function openShare() {
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Share minutes' }));
  return user;
}
async function prepare(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Prepare message' }));
  await screen.findByRole('region', { name: 'What will be sent' });
}

describe('Share minutes', () => {
  it('states the undo window in plain words', async () => {
    const { delayText } = await import('../src/api/meetingEmail');
    expect([delayText(600), delayText(60), delayText(5), delayText(1), delayText(120)]).toEqual(['10 minutes', '1 minute', '5 seconds', '1 second', '2 minutes']);
    hub();
    renderApp('#/meetings/m1');
    await openShare();
    expect(await screen.findByText(/a message waits 10 minutes so you can still cancel it/)).toBeInTheDocument();
  });

  it('shows the fixed opening and closing text read-only around the editable message, and what the AI-processing record says', async () => {
    const h = hub();
    renderApp('#/meetings/m1');
    const user = await openShare();
    await prepare(user);
    const opening = within(screen.getByRole('region', { name: 'Opening text added by Reachy' }));
    expect(opening.getByText(/I'm Reachy, Hariz's personal AI assistant/)).toBeInTheDocument();
    expect(opening.getByText('Added automatically and cannot be edited.')).toBeInTheDocument();
    const closing = within(screen.getByRole('region', { name: 'Closing text and disclosures added by Reachy' }));
    expect(closing.getByText(/processed entirely on private infrastructure/)).toBeInTheDocument();
    expect(closing.getByText(/delivered through Gmail/)).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeInTheDocument(); // only the middle is editable
    expect(within(screen.getByRole('region', { name: 'What will be sent' })).getByText(/AI processing: Every recorded step ran on private infrastructure/)).toBeInTheDocument();
    expect(h.data.email.calls.some((c: string) => c.includes('approve'))).toBe(false);
  });

  it('says plainly when an external AI service was used or the processing could not be verified', async () => {
    for (const [processing, text] of [['external', /An external AI service processed some of this meeting/], ['unverified', /could not be verified/]] as const) {
      const h = hub();
      h.data.email.processing = processing;
      const { unmount } = renderApp('#/meetings/m1');
      const user = await openShare();
      await prepare(user);
      expect(within(screen.getByRole('region', { name: 'What will be sent' })).getByText(text)).toBeInTheDocument();
      unmount();
    }
  });

  it('is only offered when the server has the feature on', async () => {
    hub({ enabled: false });
    renderApp('#/meetings/m1');
    await screen.findByRole('button', { name: 'Summary' });
    expect(screen.queryByRole('button', { name: 'Share minutes' })).toBeNull();
  });

  it('prepares a package and shows the complete delivery list, the attachment and a relative preview link before anything can be approved', async () => {
    const h = hub();
    renderApp('#/meetings/m1');
    const user = await openShare();
    await prepare(user);
    const review = within(screen.getByRole('region', { name: 'What will be sent' }));
    expect(review.getByText('From: reachy.minutes@example.test')).toBeInTheDocument();
    expect(review.getByText('To: (nobody yet)')).toBeInTheDocument();
    expect(review.getByText(/Attachment: Weekly-sync-minutes.pdf \(4 KB, fingerprint aaaaaaaaaaaa\)/)).toBeInTheDocument();
    expect(review.getByRole('link', { name: 'Preview PDF' })).toHaveAttribute('href', '/meeting-email/drafts/d1/attachments/Weekly-sync-minutes.pdf');
    expect(review.getByText(/recording and the raw transcript are never included/)).toBeInTheDocument();
    expect(screen.getByText('1 action candidate not included: you have not confirmed it.')).toBeInTheDocument();
    expect(screen.getByRole('status', { name: 'Message status' })).toHaveTextContent('Ready for your review');
    expect(screen.getByRole('button', { name: 'Approve and queue' })).toBeDisabled(); // no recipient, no typed word
    expect(h.data.email.calls.filter((c: string) => c.includes('/queue') || c.includes('/approve'))).toEqual([]);
  });

  it('needs a saved recipient list, the typed word and no unsaved changes; then approves the exact package and queues it, and the owner can cancel', async () => {
    const h = hub();
    renderApp('#/meetings/m1');
    const user = await openShare();
    await prepare(user);
    await user.type(screen.getByLabelText('To (one address per line)'), 'Colleague@Example.org');
    await user.type(screen.getByLabelText('Cc'), 'boss@example.org');
    await user.type(screen.getByLabelText('Bcc (hidden from the other recipients)'), 'hidden@example.org');
    expect(screen.getByText(/You have unsaved changes/)).toBeInTheDocument();
    await user.type(screen.getByLabelText('Type SEND to approve'), 'send');
    expect(screen.getByRole('button', { name: 'Approve and queue' })).toBeDisabled(); // unsaved: what is on screen is not what the server holds
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    const review = within(await screen.findByRole('region', { name: 'What will be sent' }));
    await waitFor(() => expect(review.getByText('To: colleague@example.org')).toBeInTheDocument());
    expect(review.getByText('Cc: boss@example.org')).toBeInTheDocument();
    expect(review.getByText('Bcc (hidden from the others): hidden@example.org')).toBeInTheDocument();
    expect(screen.getByLabelText('Type SEND to approve')).toHaveValue(''); // a saved change needs a fresh typed approval
    expect(screen.getByRole('button', { name: 'Approve and queue' })).toBeDisabled();
    await user.type(screen.getByLabelText('Type SEND to approve'), 'SEND');
    await user.click(screen.getByRole('button', { name: 'Approve and queue' }));
    expect(await screen.findByText(/Queued\. It will be sent at .* unless you cancel\./)).toBeInTheDocument();
    expect(screen.getByRole('status', { name: 'Message status' })).toHaveTextContent('Queued');
    expect(h.data.email.drafts[0].status).toBe('queued');
    expect(h.data.email.drafts[0].approved_hash).toBe(h.data.email.drafts[0].package_hash);
    await user.click(screen.getByRole('button', { name: 'Cancel sending' }));
    expect(await screen.findByRole('button', { name: 'Queue for sending' })).toBeInTheDocument();
    expect(h.data.email.drafts[0].status).toBe('approved');
    const history = screen.getByText('History').nextElementSibling as HTMLElement;
    expect(within(history).getByText(/Approved by you/)).toBeInTheDocument();
    expect(within(history).getByText(/Cancelled before sending/)).toBeInTheDocument();
  });

  it('suggestions and groups only fill the list when chosen, and nothing is preselected', async () => {
    const h = hub();
    h.data.email.suggestions = [{ address: 'dana.lee@example.org', source: 'calendar invitee' }];
    h.data.email.groups = [{ id: 'g1', name: 'Project team', addresses: ['x@example.org', 'y@example.org'] }];
    renderApp('#/meetings/m1');
    const user = await openShare();
    await prepare(user);
    const box = await screen.findByRole('checkbox', { name: /dana.lee@example.org \(calendar invitee\)/ });
    expect(box).not.toBeChecked();
    expect(screen.getByLabelText('To (one address per line)')).toHaveValue('');
    await user.click(box);
    await user.click(screen.getByRole('button', { name: 'Add group Project team' }));
    expect(screen.getByLabelText('To (one address per line)')).toHaveValue('dana.lee@example.org\nx@example.org\ny@example.org');
  });

  it('a sensitive meeting asks for an explicit acknowledgement before a message is prepared', async () => {
    const h = hub();
    h.data.email.sensitive = true;
    renderApp('#/meetings/m1');
    const user = await openShare();
    await user.click(await screen.findByRole('button', { name: 'Prepare message' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This meeting is marked sensitive');
    expect(screen.getByRole('button', { name: 'Prepare message' })).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: /marked sensitive\. I understand/ }));
    await user.click(screen.getByRole('button', { name: 'Prepare message' }));
    await screen.findByRole('region', { name: 'What will be sent' });
    expect(h.data.email.calls.some((c: string) => c.includes('/email/prepare'))).toBe(true);
  });

  it('shows the server\'s own explanation when it refuses, and a stale approval cannot go through', async () => {
    const h = hub();
    renderApp('#/meetings/m1');
    const user = await openShare();
    await prepare(user);
    await user.type(screen.getByLabelText('To (one address per line)'), 'a@example.org');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await screen.findByText('To: a@example.org');
    h.data.email.drafts[0].package_hash = 'changed-elsewhere'; // the message changed on the server after this page loaded it
    await user.type(screen.getByLabelText('Type SEND to approve'), 'SEND');
    await user.click(screen.getByRole('button', { name: 'Approve and queue' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The message changed since you reviewed it. Review it again.');
    expect(h.data.email.drafts[0].status).toBe('ready_for_review');
  });

  it('with sending turned off a message can be reviewed and approved but not queued, and the page says so', async () => {
    const h = hub();
    h.data.email.sender.enabled = false;
    renderApp('#/meetings/m1');
    const user = await openShare();
    expect(await screen.findByText(/Sending is turned off\. You can prepare and review a message/)).toBeInTheDocument();
    await prepare(user);
    await user.type(screen.getByLabelText('To (one address per line)'), 'a@example.org');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await screen.findByText('To: a@example.org');
    await user.type(screen.getByLabelText('Type SEND to approve'), 'SEND');
    await user.click(screen.getByRole('button', { name: 'Approve' }));
    expect(await screen.findByRole('button', { name: 'Queue for sending' })).toBeDisabled();
    expect(h.data.email.drafts[0].status).toBe('approved');
  });

  it('a message whose delivery is unknown is never retried by the page: the owner says whether it arrived', async () => {
    const h = hub();
    renderApp('#/meetings/m1');
    const user = await openShare();
    await prepare(user);
    Object.assign(h.data.email.drafts[0], { status: 'unknown_delivery', last_error: 'no final answer after sending: timeout' });
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await user.click(await screen.findByRole('button', { name: /Open message/ }));
    expect(await screen.findByText(/could not confirm whether this message was delivered/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve and queue' })).toBeNull();
    await user.click(screen.getByRole('button', { name: /It did not arrive/ }));
    expect(await screen.findByRole('status', { name: 'Message status' })).toHaveTextContent('Ready for your review');
    expect(h.data.email.drafts[0].approved_hash).toBeNull(); // sending it again needs a new approval
  });

  it('a failed message says nothing was delivered and offers no resend', async () => {
    const h = hub();
    renderApp('#/meetings/m1');
    const user = await openShare();
    await prepare(user);
    Object.assign(h.data.email.drafts[0], { status: 'failed', last_error: 'authentication failed: 535' });
    await user.click(screen.getByRole('button', { name: 'Back' }));
    await user.click(await screen.findByRole('button', { name: /Open message/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Nothing was delivered');
    expect(screen.queryByRole('button', { name: /Queue|Approve/ })).toBeNull();
  });

  it('text from the server is shown literally', async () => {
    const h = hub();
    renderApp('#/meetings/m1');
    const user = await openShare();
    await prepare(user);
    h.data.email.drafts[0].warnings = ['<img src=x onerror=alert(1)> warning'];
    h.data.email.drafts[0].subject = '<b>Bold</b> subject';
    await user.click(screen.getByRole('button', { name: 'Back' }));
    expect(await screen.findByText('<b>Bold</b> subject')).toBeInTheDocument();
    expect(document.querySelector('b, img')).toBeNull();
  });
});

describe('Outbound meeting email settings', () => {
  const openSettings = async () => {
    const view = renderApp('#/settings/accounts');
    await screen.findByRole('region', { name: 'Outbound meeting email' });
    return view;
  };

  it('is absent when the feature is off', async () => {
    hub({ enabled: false });
    renderApp('#/settings/accounts');
    await screen.findByRole('tablist', { name: 'Feature settings' });
    expect(screen.queryByRole('region', { name: 'Outbound meeting email' })).toBeNull();
  });

  it('sends the password once, never shows it again, and clears the field', async () => {
    const h = hub();
    h.data.email.sender = { ...h.data.email.sender, configured: false, has_credential: false, host: '', from_address: '', username: '', owner_name: '', verified_ok: null, enabled: false };
    await openSettings();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('SMTP host'), 'smtp.gmail.com');
    await user.type(screen.getByLabelText(/^Sender address/), 'reachy.minutes@gmail.com');
    await user.type(screen.getByLabelText('Username'), 'reachy.minutes@gmail.com');
    await user.type(screen.getByLabelText(/^Your name/), 'Hariz');
    await user.type(screen.getByLabelText('Password or app password'), 'abcd-efgh-ijkl-mnop');
    await user.click(screen.getByRole('button', { name: 'Save sender' }));
    await waitFor(() => expect(h.data.email.passwords).toEqual(['abcd-efgh-ijkl-mnop']));
    expect(h.data.email.sender.owner_name).toBe('Hariz'); // the name the fixed message text uses
    expect(await screen.findByLabelText('Password (leave empty to keep the saved one)')).toHaveValue('');
    expect(screen.getByRole('status', { name: 'Sender status' })).toHaveTextContent('A credential is saved.');
    expect(document.body.textContent).not.toContain('abcd-efgh-ijkl-mnop');
    expect(JSON.stringify(h.data.email.sender)).not.toContain('abcd-efgh');
  });

  it('sending is off until the connection is verified, verifying sends nothing, and removing the sender needs confirmation', async () => {
    const h = hub();
    h.data.email.sender = { ...h.data.email.sender, enabled: false, verified_ok: null };
    await openSettings();
    const user = userEvent.setup();
    const toggle = screen.getByRole('checkbox', { name: 'Allow Reachy to send approved meeting emails' });
    expect(toggle).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Verify connection' }));
    expect(await screen.findByText(/Connection verified: connected to smtp.example.test:587 and signed in\. No message was sent\./)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Allow Reachy to send approved meeting emails' })).toBeEnabled());
    await user.click(screen.getByRole('checkbox', { name: 'Allow Reachy to send approved meeting emails' }));
    await waitFor(() => expect(h.data.email.sender.enabled).toBe(true));
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    await user.click(screen.getByRole('button', { name: 'Remove sender' }));
    expect(h.data.email.sender.configured).toBe(true); // declined
    await user.click(screen.getByRole('button', { name: 'Remove sender' }));
    await waitFor(() => expect(h.data.email.sender.configured).toBe(false));
    expect(h.data.email.sender.has_credential).toBe(false);
  });

  it('manages saved recipient groups', async () => {
    const h = hub();
    await openSettings();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Group name'), 'Project team');
    await user.type(screen.getByLabelText('Addresses (one per line)'), 'X@Example.org{enter}y@example.org');
    await user.click(screen.getByRole('button', { name: 'Add group' }));
    expect(await screen.findByText('x@example.org, y@example.org')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Delete group Project team' }));
    await waitFor(() => expect(h.data.email.groups).toEqual([]));
  });
});

describe('Send a test email', () => {
  const open = async () => {
    renderApp('#/settings/accounts');
    return within(await screen.findByRole('region', { name: 'Send a test email' }));
  };

  it('sends one test message to the typed address and says what happened', async () => {
    const h = hub();
    const section = await open();
    const user = userEvent.setup();
    expect(section.getByRole('button', { name: 'Send test email' })).toBeDisabled(); // nobody typed yet
    await user.type(section.getByLabelText('Send the test email to'), 'Owner.Test@Example.org');
    await user.click(section.getByRole('button', { name: 'Send test email' }));
    expect(await section.findByRole('status', { name: 'Test email result' })).toHaveTextContent('Test email sent to owner.test@example.org (server reply: 2.0.0 OK queued). Check that inbox');
    expect(h.data.email.tests).toEqual(['Owner.Test@Example.org']);
    expect(section.getByText(/It contains no meeting content/)).toBeInTheDocument();
  });

  it('cannot be used while sending is off, and says why', async () => {
    const h = hub();
    h.data.email.sender = { ...h.data.email.sender, enabled: false };
    const section = await open();
    await userEvent.setup().type(section.getByLabelText('Send the test email to'), 'a@example.org');
    expect(section.getByRole('button', { name: 'Send test email' })).toBeDisabled();
    expect(section.getByText('Verify the connection and turn sending on first.')).toBeInTheDocument();
    expect(h.data.email.tests).toEqual([]);
  });

  it('shows the server\'s refusal for a bad address and the reason when the mail server fails', async () => {
    const h = hub();
    const section = await open();
    const user = userEvent.setup();
    const box = section.getByLabelText('Send the test email to');
    await user.type(box, 'not-an-address');
    await user.click(section.getByRole('button', { name: 'Send test email' }));
    expect(await section.findByRole('status', { name: 'Test email result' })).toHaveTextContent('not a valid email address: not-an-address');
    await user.clear(box);
    await user.type(box, 'a@example.org');
    h.data.email.testFails = 'authentication failed: 535';
    await user.click(section.getByRole('button', { name: 'Send test email' }));
    await waitFor(() => expect(section.getByRole('status', { name: 'Test email result' })).toHaveTextContent('The test email to a@example.org was not sent: authentication failed: 535.'));
    expect(h.data.email.tests).toEqual([]);
  });
});
