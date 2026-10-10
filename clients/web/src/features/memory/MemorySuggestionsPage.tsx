import { useState } from 'react';
import { StaleSessionError } from '../../api/client';
import type { AcceptBody, CandidateDto, MemoryKind, Sensitivity } from '../../api/memoryCandidates';
import { EmptyState, ErrorState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Spinner } from '../../components/ui/Spinner';
import { useAccept, useCandidates, useForgetConversation, useReject } from './useCandidates';

const RANK: Record<Sensitivity, number> = { public: 0, 'work-private': 1, sensitive: 2 };
const KIND_LABEL: Record<MemoryKind, string> = { profile: 'Profile (lasting)', working: 'Working (current)', episodic: 'Episodic (an event)' };
const WHEN = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });

export function MemorySuggestionsPage() {
  const list = useCandidates();
  const accept = useAccept();
  const reject = useReject();
  const forget = useForgetConversation();
  const [done, setDone] = useState('');
  const failure = [accept, reject, forget].map((m) => m.error).find((e) => e && !(e instanceof StaleSessionError));

  return (
    <section aria-labelledby="memory-title">
      <h1 id="memory-title" className="text-xl font-semibold">Memory suggestions</h1>
      <p className="mt-1 text-sm text-[var(--muted)]">
        Reachy may suggest things worth remembering from what you type to it. Nothing is saved until you accept it here. Suggestions you ignore are deleted after 14 days.
      </p>
      {list.data && !list.data.capture_enabled && (
        <p className="mt-2 rounded-md border border-[var(--border)] p-2 text-sm">Suggestions are not being collected right now. You can still review any that are waiting.</p>
      )}
      {done && <p role="status" className="mt-3 rounded-md bg-[var(--hover)] p-2 text-sm">{done}</p>}
      {failure && <p role="alert" className="mt-3 text-sm text-[var(--bad)]">{failure.message}</p>}
      <div className="mt-4">
        {list.isPending && <Spinner label="Loading suggestions" />}
        {list.error && !list.data && <ErrorState message={list.error.message} onRetry={() => void list.refetch()} />}
        {list.data && list.data.candidates.length === 0 && <EmptyState>No suggestions are waiting.</EmptyState>}
        <ul className="space-y-3">
          {(list.data?.candidates ?? []).map((c) => (
            <Suggestion
              key={c.id}
              candidate={c}
              busy={accept.isPending || reject.isPending || forget.isPending}
              onAccept={(body) => accept.mutate({ id: c.id, body }, { onSuccess: (r) => setDone(r.memory ? `Saved to memory: ${r.memory.content}` : 'Saved.') })}
              onReject={(suppress) => reject.mutate({ id: c.id, suppress }, { onSuccess: () => setDone(suppress ? 'Dismissed. Reachy will not suggest this again.' : 'Dismissed.') })}
              onForgetConversation={() =>
                c.conversation_id && forget.mutate(c.conversation_id, { onSuccess: (n) => setDone(`Removed ${n} suggestion${n === 1 ? '' : 's'} from that conversation.`) })
              }
            />
          ))}
        </ul>
      </div>
    </section>
  );
}

function Suggestion({ candidate, busy, onAccept, onReject, onForgetConversation }: {
  candidate: CandidateDto; busy: boolean; onAccept: (body: AcceptBody) => void; onReject: (suppress: boolean) => void; onForgetConversation: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(candidate.text);
  const [kind, setKind] = useState<MemoryKind>(candidate.proposed_type);
  const [level, setLevel] = useState<Sensitivity>(candidate.sensitivity);
  const [scope, setScope] = useState(candidate.proposed_scope ?? '');
  const [keep, setKeep] = useState<'default' | 'none' | '30' | '90' | '365'>('default');
  const [lowerOk, setLowerOk] = useState(false);
  const lowering = RANK[level] < RANK[candidate.sensitivity];
  const tooLong = draft.length > 400 || draft.trim() === '';

  const save = () => {
    const body: AcceptBody = {};
    if (draft !== candidate.text) body.text = draft.trim();
    if (kind !== candidate.proposed_type) body.type = kind;
    if (level !== candidate.sensitivity) body.sensitivity = level;
    if ((scope.trim() || null) !== candidate.proposed_scope) body.project_scope = scope.trim() || null;
    if (keep === 'none') body.expires_in_days = null;
    else if (keep !== 'default') body.expires_in_days = Number(keep);
    if (lowering) body.acknowledge_lower = lowerOk;
    onAccept(body);
  };

  return (
    <li className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      {/* The sentence is the owner's own words; React renders it as text, never as HTML. */}
      {!editing && <p className="break-words text-base">{candidate.text}</p>}
      {editing && (
        <div className="space-y-2">
          <label className="block text-sm font-medium" htmlFor={`text-${candidate.id}`}>Memory</label>
          <textarea id={`text-${candidate.id}`} className="w-full rounded-md border border-[var(--border)] p-2" rows={3} maxLength={400} value={draft} onChange={(e) => setDraft(e.target.value)} />
          <div className="flex flex-wrap gap-3 text-sm">
            <label>Kind{' '}
              <select value={kind} onChange={(e) => setKind(e.target.value as MemoryKind)}>
                {Object.entries(KIND_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label>Sensitivity{' '}
              <select value={level} onChange={(e) => setLevel(e.target.value as Sensitivity)}>
                <option value="public">Public</option>
                <option value="work-private">Work-private</option>
                <option value="sensitive">Sensitive</option>
              </select>
            </label>
            <label>Project{' '}
              <input className="rounded border border-[var(--border)] px-1" value={scope} maxLength={64} onChange={(e) => setScope(e.target.value)} />
            </label>
            <label>Keep for{' '}
              <select value={keep} onChange={(e) => setKeep(e.target.value as typeof keep)}>
                <option value="default">Default for this kind</option>
                <option value="30">30 days</option>
                <option value="90">90 days</option>
                <option value="365">1 year</option>
                <option value="none">Until I forget it</option>
              </select>
            </label>
          </div>
          {lowering && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={lowerOk} onChange={(e) => setLowerOk(e.target.checked)} />
              I understand this lowers the privacy level Reachy suggested.
            </label>
          )}
        </div>
      )}
      <p className="mt-2 text-xs text-[var(--muted)]">
        Suggested {WHEN.format(new Date(candidate.created_at))} from your {candidate.channel} chat · {KIND_LABEL[candidate.proposed_type]} · {candidate.sensitivity} · expires {WHEN.format(new Date(candidate.expires_at))}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {!editing && <Button disabled={busy} aria-label={`Save to memory: ${candidate.text}`} onClick={() => onAccept({})}>Save to memory</Button>}
        {!editing && <Button variant="secondary" disabled={busy} aria-label={`Edit: ${candidate.text}`} onClick={() => setEditing(true)}>Edit…</Button>}
        {editing && <Button disabled={busy || tooLong || (lowering && !lowerOk)} onClick={save}>Save edited memory</Button>}
        {editing && <Button variant="secondary" onClick={() => { setEditing(false); setDraft(candidate.text); }}>Cancel edit</Button>}
        <Button variant="secondary" disabled={busy} aria-label={`Dismiss: ${candidate.text}`} onClick={() => onReject(false)}>Dismiss</Button>
        <Button variant="secondary" disabled={busy} aria-label={`Never suggest this again: ${candidate.text}`} onClick={() => onReject(true)}>Never suggest this</Button>
        {candidate.conversation_id && (
          <Button variant="secondary" disabled={busy} onClick={onForgetConversation}>Forget suggestions from this chat</Button>
        )}
      </div>
    </li>
  );
}
