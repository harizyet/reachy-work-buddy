import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { StaleSessionError } from '../../api/client';
import {
  busyTimes,
  completeGoogle,
  configureGoogle,
  connectGoogle,
  disconnectGoogle,
  getGoogle,
  listCalendars,
  readMail,
  saveCalendars,
  searchMail,
  startDesktop,
  testGoogle,
  upcomingEvents,
} from '../../api/accounts';
import type { CalendarInfo, GoogleStatus, MailMessage } from '../../api/types';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Dialog } from '../../components/ui/Dialog';
import { Spinner } from '../../components/ui/Spinner';
import { goExternal } from '../../utils/navigation';
import { Check, TextField } from '../settings/fields';
import { CodingCredentials } from './CodingCredentials';
import { sayAccount, shellQuote } from './messages';

const KEY = ['accounts', 'google'] as const;
const DESKTOP_POLL_MS = 3000;
const DESKTOP_DEADLINE_MS = 10 * 60 * 1000;
const PERMISSION_NAMES: [string, string][] = [
  ['gmail.readonly', 'Read Gmail'],
  ['calendar.events.readonly', 'Read calendar events'],
  ['calendar.calendarlist.readonly', 'List calendars'],
];
const permissionText = (scopes: string[]) =>
  scopes.length
    ? [...new Set(scopes.map((s) => PERMISSION_NAMES.find(([part]) => s.includes(part))?.[1] ?? 'Identify your Google account'))].join(', ')
    : 'None';
const CAPS = [
  ['gmail', 'Gmail'],
  ['calendar', 'Google Calendar'],
] as const;
const HEALTH: Record<string, string> = { connected: 'Ready to read', disconnected: 'Not connected', not_checked: 'Permission saved; connection not checked' };

const problem = (e: unknown) => (e instanceof Error ? sayAccount(e.message) : 'Something went wrong');

export function AccountsTab() {
  return (
    <div className="space-y-4">
      <GoogleCard />
      <CodingCredentials />
    </div>
  );
}

function GoogleCard() {
  const client = useQueryClient();
  const status = useQuery({ queryKey: KEY, queryFn: ({ signal }) => getGoogle(signal), refetchOnMount: 'always', retry: false });
  const [message, setMessage] = useState('');
  const [results, setResults] = useState<React.ReactNode>(null);
  const [confirming, setConfirming] = useState(false);
  const [desktop, setDesktop] = useState<{ command: string; waiting: string } | null>(null);
  const poll = useRef<ReturnType<typeof setInterval> | null>(null);
  const [calendars, setCalendars] = useState<CalendarInfo[] | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const returned = useRef(false);

  const stopPoll = () => {
    if (poll.current) clearInterval(poll.current);
    poll.current = null;
  };
  useEffect(() => stopPoll, []); // leaving the page ends the wait for the sign-in helper

  const accept = (next: GoogleStatus) => client.setQueryData(KEY, next);
  const guard = async (action: () => Promise<void>) => {
    try {
      await action();
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setMessage(problem(e));
    }
  };

  const loadCalendars = async (next: GoogleStatus) => {
    if (!next.capabilities.calendar.enabled) return setCalendars(null);
    setCalendars(await listCalendars());
    setChosen(next.selected_calendars);
  };

  // The first look at the page, and coming back from Google's sign-in (?google=return).
  useEffect(() => {
    if (!status.data) return;
    if (!returned.current && new URLSearchParams(window.location.search).get('google') === 'return') {
      returned.current = true;
      window.history.replaceState(null, '', window.location.pathname + window.location.hash);
      void guard(async () => {
        const done = await completeGoogle();
        accept(done);
        setMessage('Google connected. Choose calendars below if you enabled Calendar.');
        await loadCalendars(done);
      });
      return;
    }
    void guard(() => loadCalendars(status.data!));
  }, [status.dataUpdatedAt]); // eslint-disable-line react-hooks/exhaustive-deps

  if (status.isPending) return <Card title="Connected accounts"><Spinner label="Loading accounts" /></Card>;
  const s = status.data;
  if (!s) return <Card title="Connected accounts"><p role="status" className="text-sm text-[var(--bad)]">{problem(status.error)}</p></Card>;

  async function connect(cap: 'gmail' | 'calendar') {
    if (s!.client_type === 'desktop') {
      const start = await startDesktop(cap);
      const hub = window.location.origin + new URL('..', window.location.href).pathname;
      stopPoll();
      setDesktop({
        command: ['python3 google_auth_helper.py', '--hub-url', shellQuote(hub), '--client-id', shellQuote(start.client_id), '--scope', shellQuote(start.scope), '--state', shellQuote(start.state), '--binding', shellQuote(start.binding), '--code-challenge', shellQuote(start.code_challenge)].join(' '),
        waiting: 'Waiting for the helper to finish (this expires in 10 minutes)…',
      });
      const deadline = Date.now() + DESKTOP_DEADLINE_MS;
      poll.current = setInterval(() => {
        if (Date.now() > deadline) {
          stopPoll();
          setDesktop(null);
          setMessage(sayAccount('invalid_or_expired_authorization'));
          return;
        }
        getGoogle()
          .then(async (latest) => {
            if (!latest.capabilities[cap].enabled) return;
            stopPoll();
            setDesktop(null);
            accept(latest);
            setMessage('Google connected. Choose calendars below if you enabled Calendar.');
            await loadCalendars(latest);
          })
          .catch(() => undefined); // transient: keep polling until the deadline
      }, DESKTOP_POLL_MS);
      return;
    }
    const url = new URL(await connectGoogle(cap));
    if (url.origin !== 'https://accounts.google.com') throw new Error('Unexpected sign-in address');
    goExternal(url.href);
  }

  async function runPreview(kind: 'events' | 'busy') {
    const start = new Date();
    const end = new Date(start.getTime() + 7 * 86400000);
    if (kind === 'busy') {
      const rows = await busyTimes(start, end);
      setResults(rows.length ? rows.map((b, i) => <p key={i}>{`Busy · ${new Date(b.start).toLocaleString()} – ${new Date(b.end).toLocaleString()}`}</p>) : 'No busy times in the selected calendars this week.');
    } else {
      const rows = await upcomingEvents(start, end);
      setResults(rows.length ? rows.map((e, i) => <p key={i}>{`${e.title} · ${e.all_day ? 'All day · ' : ''}${new Date(e.start).toLocaleString()}`}</p>) : 'No events in the next seven days.');
    }
  }

  return (
    <Card title="Connected accounts">
      <p className="mb-2 text-sm">Connect Google to let Reachy read your mail and calendar. You sign in and choose permissions on Google's website. Reachy never sees your Google password.</p>
      <p className="mb-2 text-sm text-[var(--muted)]">
        Read-only access: Reachy cannot send, delete or mark mail as read, or change your Google calendar. When cloud inference is enabled, earlier account replies may be included in conversation context sent to that provider.
      </p>
      <p role="status" className="min-h-5 text-sm">{message}</p>
      <p className="mb-2 text-sm">{s.identity ? `Signed in as ${s.identity.email}` : 'No Google account connected.'}</p>
      <div className="grid gap-3 md:grid-cols-2">
        {CAPS.map(([cap, title]) => {
          const state = s.capabilities[cap];
          return (
            <section key={cap} className="rounded border border-[var(--border)] p-3" aria-label={title}>
              <h3 className="font-medium">{title}</h3>
              <p className="text-sm">{HEALTH[state.status] ?? ACCOUNT_STATUS(state.status)}</p>
              <p className="text-sm text-[var(--muted)]">{state.last_success ? `Last successful check: ${new Date(state.last_success).toLocaleString()}` : 'No successful check yet.'}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button disabled={!s.configured} onClick={() => void guard(() => connect(cap))}>{state.enabled ? 'Reconnect' : 'Connect'}</Button>
                {state.enabled && (
                  <>
                    <Button variant="secondary" onClick={() => void guard(async () => { accept(await testGoogle(cap)); setMessage('Connection checked.'); })}>Test connection</Button>
                    <Button variant="secondary" onClick={() => setConfirming(true)}>Disconnect</Button>
                  </>
                )}
              </div>
            </section>
          );
        })}
      </div>
      <p className="my-2 text-sm text-[var(--muted)]">{`Granted permissions: ${permissionText(s.scopes)}`}</p>

      {s.capabilities.calendar.enabled && calendars && (
        <section className="my-3">
          <h3 className="font-medium">Calendars Reachy may read</h3>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void guard(async () => {
                accept(await saveCalendars(chosen));
                setMessage('Calendar choices saved.');
              });
            }}
          >
            {calendars.map((c) => (
              <Check key={c.id} label={`${c.name} (${c.timezone})`} checked={chosen.includes(c.id)} onChange={(on) => setChosen(on ? [...chosen, c.id] : chosen.filter((x) => x !== c.id))} />
            ))}
            <div className="flex flex-wrap gap-2">
              <Button type="submit">Save calendar choices</Button>
              <Button variant="secondary" onClick={() => void guard(() => runPreview('events'))}>Show upcoming events</Button>
              <Button variant="secondary" onClick={() => void guard(() => runPreview('busy'))}>Show busy times</Button>
            </div>
          </form>
          <p className="mt-1 text-sm text-[var(--muted)]">Events and busy times include only your selected calendars.</p>
        </section>
      )}
      {s.capabilities.gmail.enabled && <MailSection guard={guard} setResults={setResults} />}
      <div aria-live="polite" className="my-2 text-sm break-words">{results}</div>

      <SetupDetails status={s} onSaved={(next) => { stopPoll(); setDesktop(null); accept(next); setMessage('Setup saved. Select Connect to sign in with Google.'); }} guard={guard} />
      {desktop && (
        <div className="my-3 rounded border border-[var(--border)] p-3" aria-live="polite">
          <h3 className="font-medium">Run the sign-in helper</h3>
          <p className="text-sm">Run this on the computer whose browser you use to reach Reachy. It opens Google sign-in, then hands the result back to Reachy. It never sees your Google client secret.</p>
          <pre className="my-2 overflow-x-auto whitespace-pre-wrap break-all text-xs">{desktop.command}</pre>
          <Button variant="secondary" onClick={() => void guard(async () => { await navigator.clipboard.writeText(desktop.command); setMessage('Command copied.'); })}>Copy command</Button>
          <p role="status" className="text-sm">{desktop.waiting}</p>
        </div>
      )}

      <Dialog open={confirming} title="Disconnect Google?" onClose={() => setConfirming(false)}>
        <h2 className="text-lg font-semibold">Disconnect Google?</h2>
        <p className="my-3 text-sm">Disconnect Google? This removes access for both Gmail and Calendar. Your local drafts are kept.</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirming(false)}>Cancel</Button>
          <Button
            onClick={() => {
              setConfirming(false);
              void guard(async () => {
                const done = await disconnectGoogle();
                stopPoll();
                setDesktop(null);
                setCalendars(null);
                setResults(null);
                accept(done.status);
                setMessage(done.revoked ? 'Google disconnected. Local drafts were kept.' : 'Disconnected here. Google could not be reached to revoke access; remove Reachy access in your Google account as well.');
              });
            }}
          >
            Disconnect
          </Button>
        </div>
      </Dialog>
    </Card>
  );
}

const ACCOUNT_STATUS = (code: string) => sayAccount(code) !== code ? sayAccount(code) : 'Connection needs attention';

function MailSection({ guard, setResults }: { guard: (a: () => Promise<void>) => Promise<void>; setResults: (n: React.ReactNode) => void }) {
  const [query, setQuery] = useState('');
  function show(messages: MailMessage[]) {
    setResults(messages.length ? <ul>{messages.map((m) => <MailRow key={m.id} message={m} guard={guard} />)}</ul> : 'No matching messages.');
  }
  return (
    <section className="my-3">
      <h3 className="font-medium">Read Gmail</h3>
      <p className="mb-2 text-sm">Shows up to 60 messages. Search to narrow the results. Attachments are not downloaded; long messages use a limited text preview.</p>
      <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); void guard(async () => show(await searchMail(query))); }}>
        <label className="flex-1 text-sm">
          Search your mail
          <input className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2" maxLength={512} placeholder="Leave blank for recent messages" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <Button type="submit">Show messages</Button>
      </form>
    </section>
  );
}

function MailRow({ message, guard }: { message: MailMessage; guard: (a: () => Promise<void>) => Promise<void> }) {
  const [body, setBody] = useState<string | null>(null);
  return (
    <li className="py-1">
      {body === null ? (
        <Button variant="secondary" onClick={() => void guard(async () => setBody(await readMail(message.id)))}>{`${message.sender}: ${message.subject}`}</Button>
      ) : (
        <pre className="whitespace-pre-wrap break-words">{body}</pre>
      )}
    </li>
  );
}

function SetupDetails({ status, onSaved, guard }: { status: GoogleStatus; onSaved: (s: GoogleStatus) => void; guard: (a: () => Promise<void>) => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [replace, setReplace] = useState(false);
  const callback = window.location.origin + new URL('../settings/accounts/google/callback', window.location.href).pathname;

  async function save(event: FormEvent) {
    event.preventDefault();
    await guard(async () => {
      if (!file || file.size > 65536) throw new Error('Choose the Google connection JSON file (under 64 KB).');
      let parsed: { installed?: Record<string, string>; web?: Record<string, string> };
      try {
        parsed = JSON.parse(await file.text());
      } catch {
        throw new Error('This is not a Google connection file.');
      }
      const clientType = parsed.installed ? 'desktop' : parsed.web ? 'web' : null;
      const c = parsed.installed ?? parsed.web;
      if (!clientType || !c?.client_id || !c?.client_secret) throw new Error('Choose a Web application or Desktop app connection file downloaded from Google.');
      onSaved(
        await configureGoogle({ client_id: c.client_id, client_secret: c.client_secret, client_type: clientType, redirect_uri: clientType === 'web' ? callback : undefined, disconnect_existing: replace }),
      );
      setFile(null);
    });
  }
  return (
    <details open={!status.configured} className="my-3">
      <summary className="cursor-pointer">One-time Google connection setup</summary>
      <p className="my-2 text-sm">{status.configured ? 'Connection setup saved. Your client secret is stored securely.' : 'Google sign-in is not ready yet. The person setting up this Reachy installation needs to complete this one-time setup.'}</p>
      <p className="text-sm">This connects your own Google application to Reachy. Once it is set up, everyday use only needs the Connect buttons above.</p>
      <ol className="my-2 ml-5 list-decimal text-sm">
        <li>Open <a className="underline" href="https://console.cloud.google.com/" target="_blank" rel="noopener noreferrer">Google Cloud</a> and create a project. Enable the Gmail API and Google Calendar API.</li>
        <li>In Google Auth Platform, set up the consent screen for your use. For a personal test, add your Google email as a test user.</li>
        <li>Create a <strong>Desktop app</strong> OAuth client and download its JSON file (recommended: works without a public domain or HTTPS certificate). If this Reachy already has a stable HTTPS hostname, you may instead create a <strong>Web application</strong> client with the return address shown below as its authorized redirect URI.</li>
        <li>Choose that file here and select Save connection setup. Then use Connect to sign in and approve read-only permissions. For a Desktop client, Connect shows a command to run on the computer whose browser you're using.</li>
      </ol>
      <p className="mb-2 text-sm">Testing-mode permissions may expire after seven days. Personal/internal use and public apps have different Google verification requirements; see the deployment guide before relying on this for ongoing use.</p>
      <form onSubmit={(e) => void save(e)}>
        {status.client_type !== 'desktop' && <TextField label="Return address" readOnly value={callback} />}
        <label className="mb-3 block text-sm">
          Google connection file
          <input type="file" accept=".json,application/json" className="mt-1 block w-full" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <Check label="Disconnect my existing Google connection before replacing this setup" checked={replace} onChange={setReplace} />
        <Button type="submit">Save connection setup</Button>
      </form>
    </details>
  );
}
