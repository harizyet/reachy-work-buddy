import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { StaleSessionError } from '../../api/client';
import { deleteGroup, disconnectSender, getEmailConfig, getSender, saveGroup, saveSender, sendTestEmail, setSenderEnabled, verifySender, type GroupDto, type SenderDto } from '../../api/meetingEmail';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Check, TextField } from '../settings/fields';
import { EMAIL_CONFIG, useGroups } from '../meetings/useMeetingEmail';

// Outbound meeting email (Phase 55, ADR 0039): the dedicated sender account and the saved recipient groups. The password is write-only: it is sent once, stored encrypted by the server and
// never shown again (only "a credential is saved"). Sending is OFF until the connection has been verified and the owner turns it on, and any change to the sender or its credential turns
// it off again. Verifying signs in and quits: it sends no message and names no recipient.

const SENDER_KEY = ['meeting-email', 'sender'] as const;
const messageOf = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong');

export function MailSender() {
  const config = useQuery({ queryKey: EMAIL_CONFIG, queryFn: ({ signal }) => getEmailConfig(signal), staleTime: 30_000 });
  if (config.isPending) return null;
  if (config.data?.enabled !== true) return null; // the feature is off on this server: nothing to set up
  return (
    <>
      <SenderCard />
      <GroupsCard />
    </>
  );
}

function SenderCard() {
  const client = useQueryClient();
  const sender = useQuery({ queryKey: SENDER_KEY, queryFn: ({ signal }) => getSender(signal) });
  const [host, setHost] = useState('');
  const [port, setPort] = useState('587');
  const [from, setFrom] = useState('');
  const [username, setUsername] = useState('');
  const [ownerName, setOwnerName] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [testTo, setTestTo] = useState('');
  const [testStatus, setTestStatus] = useState('');
  const [testing, setTesting] = useState(false);

  const data = sender.data;
  useEffect(() => {
    if (!data) return;
    setHost(data.host);
    setPort(String(data.port));
    setFrom(data.from_address);
    setUsername(data.username);
    setOwnerName(data.owner_name);
    setPassword(''); // the typed credential is dropped as soon as the server has it
  }, [data]);

  const apply = (next: SenderDto) => {
    client.setQueryData(SENDER_KEY, next);
    void client.invalidateQueries({ queryKey: EMAIL_CONFIG });
  };
  const run = async (label: string, action: () => Promise<SenderDto | void>) => {
    setBusy(true);
    setStatus('');
    try {
      const next = await action();
      if (next) apply(next);
      if (label) setStatus(label); // an action that reports its own result passes an empty label
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setStatus(messageOf(e));
    } finally {
      setBusy(false);
    }
  };

  // One fixed test message to the address typed here: it needs sending turned on, contains no meeting content, and is limited by the server to a few an hour.
  const test = async () => {
    setTesting(true);
    setTestStatus('');
    try {
      const result = await sendTestEmail(testTo.trim());
      setTestStatus(
        result.status === 'sent'
          ? `Test email sent to ${result.to}${result.provider_response ? ` (server reply: ${result.provider_response})` : ''}. Check that inbox (and its spam folder).`
          : result.status === 'unknown_delivery'
            ? `The mail server did not confirm whether the test email to ${result.to} arrived (${result.error ?? 'no answer'}). Check that inbox before trying again.`
            : `The test email to ${result.to} was not sent: ${result.error ?? 'it failed'}.`,
      );
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setTestStatus(messageOf(e));
    } finally {
      setTesting(false);
    }
  };

  const save = () =>
    run('Saved. Verify the connection, then turn sending on.', () =>
      saveSender({ host: host.trim(), port: Number(port) || 587, security: 'starttls', from_address: from.trim(), username: username.trim(), owner_name: ownerName.trim(), ...(password ? { password } : {}) }),
    );

  return (
    <Card title="Outbound meeting email" eyebrow="MEETING MINUTES">
      <p className="mb-3 text-sm text-[var(--muted)]">
        A dedicated mail account Reachy sends meeting summaries and minutes from, only after you approve each message. Use a separate account, not your own. For Gmail: host smtp.gmail.com, port 587,
        the account's address as both sender and username, and an app password (the account needs 2-Step Verification). The password is stored encrypted and is never shown again.
      </p>
      {data && (
        <p role="status" aria-label="Sender status" className="mb-3 text-sm">
          {!data.configured ? 'Not set up.' : data.enabled ? `Sending is ON as ${data.from_address}.` : `Set up as ${data.from_address}; sending is OFF.`}
          {data.configured && ` ${data.has_credential ? 'A credential is saved.' : 'No credential saved.'}`}
          {data.verified_ok === true && ' Connection verified.'}
          {data.verified_ok === false && ` Last check failed: ${data.verified_detail}`}
        </p>
      )}
      <TextField
        label="Your name"
        value={ownerName}
        onChange={(e) => setOwnerName(e.target.value)}
        autoComplete="off"
        hint="Used in the fixed text of every meeting email: “I'm Reachy, [your name]'s personal AI assistant”. Required to prepare a message."
      />
      <TextField label="SMTP host" value={host} onChange={(e) => setHost(e.target.value)} autoComplete="off" />
      <TextField label="Port" value={port} inputMode="numeric" onChange={(e) => setPort(e.target.value)} hint="587 with STARTTLS. The connection is always encrypted before the password is sent." />
      <TextField label="Sender address" value={from} onChange={(e) => setFrom(e.target.value)} autoComplete="off" hint="Messages are sent as this address, and no other." />
      <TextField label="Username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
      <TextField label={data?.has_credential ? 'Password (leave empty to keep the saved one)' : 'Password or app password'} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy || !host.trim() || !from.trim()} onClick={() => void save()}>
          Save sender
        </Button>
        <Button
          variant="secondary"
          disabled={busy || !data?.configured}
          onClick={() =>
            void run('', async () => {
              const result = await verifySender();
              setStatus(result.ok ? `Connection verified: ${result.detail}. No message was sent.` : `The check failed: ${result.detail}`);
              return result.sender;
            })
          }
        >
          Verify connection
        </Button>
        <Check label="Allow Reachy to send approved meeting emails" checked={data?.enabled === true} disabled={busy || !data?.configured || data?.verified_ok !== true && data?.enabled !== true} onChange={(on) => void run(on ? 'Sending is on.' : 'Sending is off.', () => setSenderEnabled(on))} />
        <Button
          variant="secondary"
          disabled={busy || !data?.configured}
          onClick={() => {
            if (window.confirm('Remove the sender and its saved credential? Messages already waiting will not be sent until a sender is set up again.')) void run('Sender removed.', () => disconnectSender());
          }}
        >
          Remove sender
        </Button>
      </div>
      {status && <p role="status" className="mt-2 text-sm">{status}</p>}
      <section aria-label="Send a test email" className="mt-4 border-t border-[var(--border)] pt-3">
        <h3 className="text-sm font-semibold">Send a test email</h3>
        <p className="mb-2 text-sm text-[var(--muted)]">
          Sends one short fixed message from {data?.from_address || 'the sender'} to the address below, to check that the account works. It contains no meeting content. Sending must be turned on, and
          only a few test emails are allowed an hour.
        </p>
        <TextField label="Send the test email to" type="email" value={testTo} onChange={(e) => setTestTo(e.target.value)} autoComplete="off" placeholder="an address you can check" />
        <Button disabled={testing || !testTo.trim() || data?.enabled !== true} onClick={() => void test()}>
          {testing ? 'Sending…' : 'Send test email'}
        </Button>
        {data?.configured && data.enabled !== true && <p className="mt-1 text-sm text-[var(--muted)]">Verify the connection and turn sending on first.</p>}
        {testStatus && <p role="status" aria-label="Test email result" className="mt-2 text-sm">{testStatus}</p>}
      </section>
    </Card>
  );
}

function GroupsCard() {
  const client = useQueryClient();
  const groups = useGroups();
  const [name, setName] = useState('');
  const [addresses, setAddresses] = useState('');
  const [editing, setEditing] = useState<GroupDto | null>(null);
  const [status, setStatus] = useState('');
  const reload = () => client.invalidateQueries({ queryKey: ['meeting-email', 'groups'] });

  const save = async () => {
    setStatus('');
    try {
      await saveGroup(name, addresses.split(/[\n,;]+/).map((a) => a.trim()).filter(Boolean), editing?.id);
      setName('');
      setAddresses('');
      setEditing(null);
      await reload();
    } catch (e) {
      if (!(e instanceof StaleSessionError)) setStatus(messageOf(e));
    }
  };

  return (
    <Card title="Recipient groups" eyebrow="MEETING MINUTES">
      <p className="mb-3 text-sm text-[var(--muted)]">A group is only a shortcut that fills in the recipients of one message. Choosing it never sends anything, and you review the full list every time.</p>
      <ul className="mb-3 divide-y divide-[var(--border)] text-sm">
        {(groups.data ?? []).map((g) => (
          <li key={g.id} className="flex flex-wrap items-center gap-2 py-2">
            <span className="min-w-0 flex-1 break-words">
              <strong>{g.name}</strong>
              <span className="block text-[var(--muted)]">{g.addresses.join(', ')}</span>
            </span>
            <Button variant="secondary" aria-label={`Edit group ${g.name}`} onClick={() => { setEditing(g); setName(g.name); setAddresses(g.addresses.join('\n')); }}>
              Edit
            </Button>
            <Button variant="secondary" aria-label={`Delete group ${g.name}`} onClick={() => void deleteGroup(g.id).then(reload).catch((e: unknown) => !(e instanceof StaleSessionError) && setStatus(messageOf(e)))}>
              Delete
            </Button>
          </li>
        ))}
        {groups.data?.length === 0 && <li className="py-2 text-[var(--muted)]">No groups yet.</li>}
      </ul>
      <TextField label="Group name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
      <label className="mb-3 block text-sm">
        Addresses (one per line)
        <textarea className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2 font-mono text-sm" rows={3} value={addresses} onChange={(e) => setAddresses(e.target.value)} />
      </label>
      <div className="flex gap-2">
        <Button disabled={!name.trim() || !addresses.trim()} onClick={() => void save()}>
          {editing ? 'Save group' : 'Add group'}
        </Button>
        {editing && (
          <Button variant="secondary" onClick={() => { setEditing(null); setName(''); setAddresses(''); }}>
            Cancel
          </Button>
        )}
      </div>
      {status && <p role="alert" className="mt-2 text-sm text-[var(--bad)]">{status}</p>}
    </Card>
  );
}
