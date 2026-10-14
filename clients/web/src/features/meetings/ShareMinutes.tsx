import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { ApiError, StaleSessionError } from '../../api/client';
import {
  approveDraft,
  attachmentUrl,
  cancelSend,
  discardDraft,
  editDraft,
  prepareEmail,
  queueDraft,
  resolveDraft,
  type DraftDto,
  type DraftStatus,
} from '../../api/meetingEmail';
import type { Meeting } from '../../api/types';
import { Button } from '../../components/ui/Button';
import { Spinner } from '../../components/ui/Spinner';
import { emailDrafts, useEmailConfig, useGroups, useMeetingDrafts, useSuggestions } from './useMeetingEmail';

// Share minutes (Phase 55). Prepare a package from the meeting, review it, approve the EXACT package by typing SEND, and it waits ten minutes (cancellable) before the server sends it
// through the dedicated sender. Nothing here sends anything by itself: every outbound message needs this manual approval. The server owns the state machine and the approval hash; the
// page only shows what the server says and asks for the owner's decisions.

const STATUS_LABEL: Record<DraftStatus, string> = {
  draft: 'Draft',
  ready_for_review: 'Ready for your review',
  approved: 'Approved, not queued',
  queued: 'Queued: will be sent unless you cancel',
  sending: 'Sending…',
  sent: 'Sent',
  cancelled: 'Discarded',
  rejected: 'Rejected',
  failed: 'Not sent: it failed',
  unknown_delivery: 'Delivery unknown',
};
const EVENT_LABEL: Record<string, string> = {
  prepared: 'Prepared',
  edited: 'Edited',
  approved: 'Approved by you',
  queued: 'Queued to send',
  cancelled_before_send: 'Cancelled before sending',
  discarded: 'Discarded',
  sending: 'Sending attempt',
  retry_scheduled: 'Could not connect; will retry',
  sent: 'Sent',
  failed: 'Failed',
  unknown_delivery: 'Delivery unknown',
  owner_confirmed_delivered: 'You confirmed it arrived',
  owner_reopened: 'You chose to send it again',
};
const EDITABLE: DraftStatus[] = ['draft', 'ready_for_review', 'approved'];

const messageOf = (error: unknown) => (error instanceof Error ? error.message : 'Something went wrong');
const lines = (text: string) =>
  text
    .split(/[\n,;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : '');
const shortHash = (h: string) => h.slice(0, 12);

export function ShareMinutes({ meeting }: { meeting: Meeting }) {
  const config = useEmailConfig();
  const drafts = useMeetingDrafts(meeting.id, config.data?.enabled === true);
  const client = useQueryClient();
  const [openId, setOpenId] = useState<string | null>(null);
  const [includePdf, setIncludePdf] = useState(true);
  const [sensitive, setSensitive] = useState(false);
  const [needsAck, setNeedsAck] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const list = drafts.data ?? [];
  const open = list.find((d) => d.id === openId) ?? null;
  const refresh = () => client.invalidateQueries({ queryKey: emailDrafts(meeting.id) });
  const setDraft = (draft: DraftDto) => {
    client.setQueryData<DraftDto[]>(emailDrafts(meeting.id), (all) => [draft, ...(all ?? []).filter((d) => d.id !== draft.id)]);
    setOpenId(draft.id);
  };

  if (config.isPending || drafts.isPending) return <Spinner label="Loading" />;
  if (config.data?.enabled !== true) return <p className="text-sm text-[var(--muted)]">Emailing minutes is not turned on for this Reachy.</p>;
  const sender = config.data.sender;

  const prepare = async () => {
    setBusy(true);
    setError('');
    try {
      setDraft(await prepareEmail(meeting.id, { include_pdf: includePdf, allow_sensitive: sensitive }));
      setNeedsAck(false);
    } catch (e) {
      if (e instanceof StaleSessionError) return;
      if (e instanceof ApiError && e.code === 'sensitive_meeting') setNeedsAck(true);
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <p className="text-sm text-[var(--muted)]">
        Prepare the summary and minutes as an email, review exactly what will go out, and approve it. Nothing is sent without your approval, and a message waits {Math.round((config.data.send_delay_seconds ?? 600) / 60)} minutes so you can still cancel it.
      </p>
      {!sender?.configured && <p role="status" className="my-2 rounded border border-[var(--warn)] bg-[var(--warn-bg)] p-2 text-sm text-[var(--warn)]">Set up the outbound sender first (Settings, Accounts, Outbound meeting email).</p>}
      {sender?.configured && !sender.enabled && <p role="status" className="my-2 text-sm text-[var(--warn)]">Sending is turned off. You can prepare and review a message, but it cannot be queued until sending is enabled in Settings.</p>}
      {(meeting.stale_outputs.length > 0 || meeting.speaker_review_needed) && (
        <p role="status" className="my-2 text-sm text-[var(--warn)]">
          {meeting.speaker_review_needed ? 'The speaker names are not confirmed (speaker detection was run again). ' : ''}
          {meeting.stale_outputs.length > 0 ? `The ${meeting.stale_outputs.join(' and ')} was written before the speaker names changed: write it again before preparing a message.` : ''}
        </p>
      )}

      {open ? (
        <DraftView key={open.id} draft={open} meetingId={meeting.id} onChange={setDraft} onClose={() => { setOpenId(null); void refresh(); }} onRefresh={refresh} />
      ) : (
        <div className="mt-3 rounded border border-[var(--border)] p-3">
          <h4 className="font-medium">Prepare a message</h4>
          <label className="mt-1 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={includePdf} onChange={(e) => setIncludePdf(e.target.checked)} /> Attach the minutes as a PDF
          </label>
          {needsAck && (
            <label className="mt-1 flex items-start gap-2 text-sm text-[var(--warn)]">
              <input type="checkbox" checked={sensitive} onChange={(e) => setSensitive(e.target.checked)} />
              <span>This meeting is marked sensitive. I understand and want to prepare a message from it.</span>
            </label>
          )}
          <Button className="mt-2" disabled={busy || (needsAck && !sensitive)} onClick={() => void prepare()}>
            {busy ? 'Preparing…' : 'Prepare message'}
          </Button>
          {error && <p role="alert" className="mt-1 text-sm text-[var(--bad)]">{error}</p>}
        </div>
      )}

      {!open && list.length > 0 && (
        <div className="mt-4">
          <h4 className="font-medium">Messages for this meeting</h4>
          <ul className="divide-y divide-[var(--border)]">
            {list.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                <span className="min-w-0 flex-1 break-words">
                  <strong>{d.subject}</strong>
                  <span className="block text-[var(--muted)]">{`${STATUS_LABEL[d.status]} · ${d.recipient_count} recipient${d.recipient_count === 1 ? '' : 's'} · ${when(d.created_at)}`}</span>
                </span>
                <Button variant="secondary" aria-label={`Open message ${d.subject}`} onClick={() => setOpenId(d.id)}>
                  Open
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function DraftView({ draft, meetingId, onChange, onClose, onRefresh }: { draft: DraftDto; meetingId: string; onChange: (d: DraftDto) => void; onClose: () => void; onRefresh: () => void }) {
  const groups = useGroups();
  const suggestions = useSuggestions(meetingId, EDITABLE.includes(draft.status));
  const editable = EDITABLE.includes(draft.status);
  const [to, setTo] = useState(draft.recipients.to.join('\n'));
  const [cc, setCc] = useState(draft.recipients.cc.join('\n'));
  const [bcc, setBcc] = useState(draft.recipients.bcc.join('\n'));
  const [subject, setSubject] = useState(draft.subject);
  const [body, setBody] = useState(draft.body);
  const [pdf, setPdf] = useState(draft.attachments.length > 0);
  const [word, setWord] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  // A saved change (a new package hash) resets the form to what the server now holds.
  useEffect(() => {
    setTo(draft.recipients.to.join('\n'));
    setCc(draft.recipients.cc.join('\n'));
    setBcc(draft.recipients.bcc.join('\n'));
    setSubject(draft.subject);
    setBody(draft.body);
    setPdf(draft.attachments.length > 0);
    setWord('');
  }, [draft.package_hash, draft.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = useMemo(
    () => to !== draft.recipients.to.join('\n') || cc !== draft.recipients.cc.join('\n') || bcc !== draft.recipients.bcc.join('\n') || subject !== draft.subject || body !== draft.body || pdf !== (draft.attachments.length > 0),
    [to, cc, bcc, subject, body, pdf, draft],
  );

  const run = async (action: () => Promise<DraftDto>) => {
    setBusy(true);
    setError('');
    try {
      onChange(await action());
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setError(messageOf(e));
      onRefresh();
    } finally {
      setBusy(false);
    }
  };

  const save = () => run(() => editDraft(draft.id, { to: lines(to), cc: lines(cc), bcc: lines(bcc), subject, body, include_pdf: pdf }));
  const addAddress = (address: string) => setTo((current) => (lines(current).includes(address) ? current : [...lines(current), address].join('\n')));
  const wordOk = word.trim().toUpperCase() === 'SEND';
  const canApprove = draft.status === 'ready_for_review' && !dirty && draft.recipients.to.length > 0 && wordOk && !busy;
  const approveAndQueue = () =>
    run(async () => {
      const approved = await approveDraft(draft.id, draft.package_hash ?? '', word);
      return approved.sender_ready ? await queueDraft(draft.id) : approved;
    });

  return (
    <div className="mt-3 rounded border border-[var(--border)] p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="min-w-0 flex-1 font-medium">{draft.subject}</h4>
        <span role="status" aria-label="Message status" className="rounded border border-[var(--border)] px-2 py-0.5 text-xs">{STATUS_LABEL[draft.status]}</span>
        <Button variant="secondary" onClick={onClose}>
          Back
        </Button>
      </div>
      {draft.warnings.map((w) => (
        <p key={w} role="status" className="mt-1 text-sm text-[var(--warn)]">{w}</p>
      ))}
      {draft.meeting_changed && editable && (
        <p role="status" className="mt-1 text-sm text-[var(--warn)]">
          The meeting's summary, minutes or speaker names changed after this message was prepared, so it cannot be queued as it is.{' '}
          <button type="button" className="underline" onClick={() => void run(() => editDraft(draft.id, { refresh: true }))}>Refresh it from the meeting</button> and review it again.
        </p>
      )}

      {editable ? (
        <div className="mt-2 space-y-2">
          <Field label="To (one address per line)" value={to} onChange={setTo} rows={2} />
          <Field label="Cc" value={cc} onChange={setCc} rows={1} />
          <Field label="Bcc (hidden from the other recipients)" value={bcc} onChange={setBcc} rows={1} />
          {groups.data && groups.data.length > 0 && (
            <div className="text-sm">
              <span className="text-[var(--muted)]">Add a saved group to To: </span>
              {groups.data.map((g) => (
                <Button key={g.id} variant="secondary" className="mr-1" aria-label={`Add group ${g.name}`} onClick={() => setTo((current) => [...new Set([...lines(current), ...g.addresses])].join('\n'))}>
                  {g.name}
                </Button>
              ))}
            </div>
          )}
          {suggestions.data && suggestions.data.length > 0 && (
            <fieldset className="text-sm">
              <legend className="text-[var(--muted)]">Suggested from the calendar (nothing is added unless you choose it)</legend>
              {suggestions.data.map((s) => (
                <label key={s.address} className="mr-3 inline-flex items-center gap-1">
                  <input type="checkbox" checked={lines(to).includes(s.address)} onChange={(e) => (e.target.checked ? addAddress(s.address) : setTo(lines(to).filter((a) => a !== s.address).join('\n')))} />
                  {`${s.address} (${s.source})`}
                </label>
              ))}
            </fieldset>
          )}
          <label className="block text-sm">
            Subject
            <input className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2" value={subject} maxLength={200} onChange={(e) => setSubject(e.target.value)} />
          </label>
          <Field label="Message" value={body} onChange={setBody} rows={14} />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={pdf} onChange={(e) => setPdf(e.target.checked)} /> Attach the minutes as a PDF
          </label>
          <div className="flex gap-2">
            <Button disabled={!dirty || busy} onClick={() => void save()}>
              Save changes
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => void run(() => discardDraft(draft.id))}>
              Discard message
            </Button>
          </div>
          {dirty && <p className="text-sm text-[var(--warn)]">You have unsaved changes. Save them, then review the message again before approving.</p>}
        </div>
      ) : (
        <Readonly draft={draft} />
      )}

      <Review draft={draft} />

      {draft.status === 'ready_for_review' && (
        <div className="mt-3 rounded border border-[var(--border)] p-2">
          <h5 className="font-medium">Approve this exact message</h5>
          <p className="text-sm text-[var(--muted)]">
            {`It will go from ${draft.sender ?? 'the configured sender'} to ${draft.recipient_count} recipient${draft.recipient_count === 1 ? '' : 's'} (listed above) after a ten-minute window. Any later change needs a new approval.`}
          </p>
          {!draft.sender_ready && <p className="text-sm text-[var(--warn)]">Sending is turned off, so approving will not queue it.</p>}
          <label className="mt-1 block text-sm">
            Type SEND to approve
            <input className="mt-1 block w-40 rounded border border-[var(--border)] bg-[var(--bg)] p-2" value={word} autoComplete="off" onChange={(e) => setWord(e.target.value)} />
          </label>
          <Button className="mt-2" disabled={!canApprove} onClick={() => void approveAndQueue()}>
            {draft.sender_ready ? 'Approve and queue' : 'Approve'}
          </Button>
        </div>
      )}

      {draft.status === 'approved' && (
        <div className="mt-3 flex gap-2">
          <Button disabled={busy || !draft.sender_ready || draft.meeting_changed} onClick={() => void run(() => queueDraft(draft.id))}>
            Queue for sending
          </Button>
        </div>
      )}
      {draft.status === 'queued' && (
        <div className="mt-3">
          <p role="status" className="text-sm">{`Queued. It will be sent at ${when(draft.dispatch_at)} unless you cancel.`}</p>
          <Button className="mt-1" disabled={busy} onClick={() => void run(() => cancelSend(draft.id))}>
            Cancel sending
          </Button>
        </div>
      )}
      {draft.status === 'sent' && <p role="status" className="mt-3 text-sm">{`Sent ${when(draft.sent_at)}${draft.provider_response ? ` (server reply: ${draft.provider_response})` : ''}.`}</p>}
      {draft.status === 'failed' && (
        <p role="alert" className="mt-3 text-sm text-[var(--bad)]">{`This message was not sent. ${draft.last_error ?? ''} Nothing was delivered. Prepare a new message to try again.`}</p>
      )}
      {draft.status === 'unknown_delivery' && (
        <div className="mt-3 rounded border border-[var(--warn)] p-2">
          <p role="alert" className="text-sm text-[var(--warn)]">
            Reachy could not confirm whether this message was delivered ({draft.last_error ?? 'no answer from the mail server'}). It will not be sent again automatically, to avoid a duplicate. Check the recipient or the sender's Sent folder, then tell Reachy what happened.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button disabled={busy} onClick={() => void run(() => resolveDraft(draft.id, true))}>
              It arrived
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => void run(() => resolveDraft(draft.id, false))}>
              It did not arrive: send it again (needs a new approval)
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => void run(() => discardDraft(draft.id))}>
              Discard
            </Button>
          </div>
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-[var(--bad)]">{error}</p>}

      <h5 className="mt-4 font-medium">History</h5>
      <ul className="text-sm text-[var(--muted)]">
        {draft.events.map((e, i) => (
          <li key={`${e.at}-${i}`}>{`${when(e.at)}: ${EVENT_LABEL[e.event] ?? e.event}${typeof e.detail.reason === 'string' ? ` (${e.detail.reason})` : ''}`}</li>
        ))}
      </ul>
    </div>
  );
}

function Field({ label, value, onChange, rows }: { label: string; value: string; onChange: (v: string) => void; rows: number }) {
  return (
    <label className="block text-sm">
      {label}
      <textarea className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2 font-mono text-sm" rows={rows} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

/** The complete delivery list and the attachment, exactly as the server holds them: what the approval covers. */
function Review({ draft }: { draft: DraftDto }) {
  const r = draft.recipients;
  return (
    <section aria-label="What will be sent" className="mt-3 rounded bg-[var(--hover)] p-2 text-sm">
      <h5 className="font-medium">What will be sent</h5>
      <p>{`From: ${draft.sender ?? '(sender not set)'}`}</p>
      <p>{`To: ${r.to.length ? r.to.join(', ') : '(nobody yet)'}`}</p>
      {r.cc.length > 0 && <p>{`Cc: ${r.cc.join(', ')}`}</p>}
      {r.bcc.length > 0 && <p>{`Bcc (hidden from the others): ${r.bcc.join(', ')}`}</p>}
      <p>{`Subject: ${draft.subject}`}</p>
      {draft.attachments.length === 0 ? (
        <p>No attachment.</p>
      ) : (
        draft.attachments.map((a) => (
          <p key={a.name}>
            {`Attachment: ${a.name} (${Math.max(1, Math.round(a.size / 1024))} KB, fingerprint ${shortHash(a.sha256)}) `}
            <a className="underline" href={attachmentUrl(draft.id, a.name)} target="_blank" rel="noreferrer">
              Preview PDF
            </a>
          </p>
        ))
      )}
      <p className="text-[var(--muted)]">The recording and the raw transcript are never included.</p>
    </section>
  );
}

function Readonly({ draft }: { draft: DraftDto }) {
  return <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded border border-[var(--border)] p-2 text-sm">{draft.body}</pre>;
}
