import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { StaleSessionError } from '../../api/client';
import { listCredentials, removeCredential, saveCredential } from '../../api/accounts';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Dialog } from '../../components/ui/Dialog';
import { Spinner } from '../../components/ui/Spinner';
import { selectClass } from '../settings/fields';

const PROVIDERS: { id: string; title: string; hint?: string; fixedKind?: string }[] = [
  {
    id: 'claude-code',
    title: 'Claude Code',
    hint: 'API key: pay-per-use billing from your Anthropic Console account. OAuth token: if you have a Claude Pro or Max subscription, run "claude setup-token" on a computer where you can sign in, then paste the token it prints here — usage counts against your subscription instead of API billing. Reachy cannot run that sign-in step itself. Starting a session with an OAuth token is disabled for now, so your subscription cannot be spent by this feature yet; only an API key can actually run a task at this stage.',
  },
  {
    id: 'claude-code-account',
    title: 'Claude account usage',
    fixedKind: 'oauth_token',
    hint: 'Optional, read-only: lets Reachy show your live 5-hour and weekly Claude allowance. The session token above cannot do this. Paste the contents of the .credentials.json file that "claude login" creates (or its claudeAiOauth object). Use a separate login so it does not share a refresh token with your own computer: run CLAUDE_CONFIG_DIR=/tmp/reachy-login claude login, then paste /tmp/reachy-login/.credentials.json. Reachy refreshes and re-saves this credential itself, and only ever uses it to read usage.',
  },
  { id: 'codex', title: 'OpenAI Codex CLI' },
];

// A credential value is write-only: it is sent once and only its last four characters ever come back.
export function CodingCredentials() {
  const records = useQuery({ queryKey: ['credentials'], queryFn: ({ signal }) => listCredentials(signal), refetchOnMount: 'always', retry: false });
  const [message, setMessage] = useState('');
  const [removing, setRemoving] = useState<{ id: string; title: string } | null>(null);
  const client = useQueryClient();
  const remove = useMutation({
    mutationFn: removeCredential,
    onSuccess: () => client.invalidateQueries({ queryKey: ['credentials'] }),
  });
  const by = Object.fromEntries((records.data ?? []).map((r) => [r.provider, r]));
  return (
    <Card eyebrow="DEVELOPMENT" title="Coding agent credentials">
      <p className="mb-2 text-sm text-[var(--muted)]">
        Credentials a coding agent container needs to run, kept separate from Reachy's own application credentials. Reachy never sees or stores the agent's conversation itself here — only the secret it uses to authenticate.
      </p>
      <p role="status" className="min-h-5 text-sm">{message || (records.error && !(records.error instanceof StaleSessionError) ? records.error.message : '')}</p>
      {records.isPending && <Spinner label="Loading credentials" />}
      {records.data && (
        <div className="grid gap-3 md:grid-cols-2">
          {PROVIDERS.map((p) => (
            <CredentialForm
              key={p.id + (by[p.id]?.updated_at ?? '')}
              provider={p}
              record={by[p.id]}
              onSaved={() => {
                setMessage(`${p.title} credential saved.`);
                void client.invalidateQueries({ queryKey: ['credentials'] });
              }}
              onError={setMessage}
              onRemove={() => setRemoving({ id: p.id, title: p.title })}
            />
          ))}
        </div>
      )}
      <Dialog open={removing !== null} title="Remove credential?" onClose={() => setRemoving(null)}>
        <h2 className="text-lg font-semibold">Remove credential?</h2>
        <p className="my-3 text-sm">{`Remove the stored ${removing?.title ?? ''} credential?`}</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setRemoving(null)}>Cancel</Button>
          <Button
            onClick={() => {
              const target = removing;
              setRemoving(null);
              if (target) remove.mutate(target.id, { onSuccess: () => setMessage(`${target.title} credential removed.`), onError: (e) => setMessage(e.message) });
            }}
          >
            Remove
          </Button>
        </div>
      </Dialog>
    </Card>
  );
}

function CredentialForm({ provider, record, onSaved, onError, onRemove }: { provider: (typeof PROVIDERS)[number]; record?: { last_four: string; updated_at: string }; onSaved: () => void; onError: (m: string) => void; onRemove: () => void }) {
  const [kind, setKind] = useState(provider.fixedKind ?? 'api_key');
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <section className="rounded border border-[var(--border)] p-3" aria-label={provider.title}>
      <h3 className="font-medium">{provider.title}</h3>
      <p className="text-sm">{record ? `Credential configured (ending ${record.last_four}). Saved ${new Date(record.updated_at).toLocaleString()}.` : 'No credential configured yet.'}</p>
      {provider.hint && <p className="my-1 text-sm text-[var(--muted)]">{provider.hint}</p>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setBusy(true);
          saveCredential(provider.id, kind, value)
            .then(() => {
              setValue('');
              onSaved();
            })
            .catch((err: unknown) => !(err instanceof StaleSessionError) && onError(err instanceof Error ? err.message : 'Could not save'))
            .finally(() => setBusy(false));
        }}
      >
        {!provider.fixedKind && (
          <label className="mb-2 block text-sm">
            Credential type
            <select className={selectClass} value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="api_key">API key</option>
              <option value="oauth_token">OAuth token</option>
            </select>
          </label>
        )}
        <label className="mb-2 block text-sm">
          {`${provider.title} credential value`}
          <input type="password" autoComplete="off" required maxLength={8192} className={selectClass} value={value} onChange={(e) => setValue(e.target.value)} />
        </label>
        <div className="flex gap-2">
          <Button type="submit" disabled={busy}>{record ? 'Replace credential' : 'Save credential'}</Button>
          {record && <Button variant="secondary" onClick={onRemove}>Remove credential</Button>}
        </div>
      </form>
    </section>
  );
}
