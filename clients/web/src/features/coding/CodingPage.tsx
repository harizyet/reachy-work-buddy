import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { StaleSessionError } from '../../api/client';
import { addProject, getAllowance, listProjects, listSessions, listTerminalSessions, refreshSession, sessionEvents, sessionUsage, startSession, stopSession } from '../../api/coding';
import type { CodingProject, CodingSession, Dimension } from '../../api/types';
import { EmptyState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Dialog } from '../../components/ui/Dialog';
import { Spinner } from '../../components/ui/Spinner';
import { selectClass } from '../settings/fields';

export const CODING_POLL_MS = 15_000;
const ACTIVE = new Set(['created', 'starting', 'running', 'waiting_for_input', 'waiting_for_permission', 'rate_limited']);
const when = (value: string | null) => (value ? new Date(value).toLocaleString() : '');
const words = (value: string) => value.replaceAll('_', ' ');
const dimensionText = (d: Dimension) => `${words(d.name)}: ${d.value} ${d.unit}${d.resets_at ? ` (resets ${when(d.resets_at)})` : ''}`;
const messageOf = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong');
const poll = { refetchInterval: CODING_POLL_MS, refetchOnMount: 'always' as const, retry: false };

// Observation and control of containerised coding-agent sessions. Starting one can spend Claude usage and, with an API
// key, change files in the repository, so it always asks first; terminal sessions the owner ran are view-only.
export function CodingPage() {
  const client = useQueryClient();
  const projects = useQuery({ queryKey: ['coding', 'projects'], queryFn: ({ signal }) => listProjects(signal), ...poll });
  const sessions = useQuery({ queryKey: ['coding', 'sessions'], queryFn: ({ signal }) => listSessions(signal), ...poll });
  const terminal = useQuery({ queryKey: ['coding', 'terminal'], queryFn: ({ signal }) => listTerminalSessions(signal), ...poll });
  const allowance = useQuery({ queryKey: ['coding', 'allowance'], queryFn: ({ signal }) => getAllowance(signal), ...poll });
  const [message, setMessage] = useState('');
  const [starting, setStarting] = useState<{ project: CodingProject; task: string; branch: string | null } | null>(null);
  const [stopping, setStopping] = useState<CodingSession | null>(null);
  const reload = () => client.invalidateQueries({ queryKey: ['coding'] });
  const names = Object.fromEntries((projects.data ?? []).map((p) => [p.id, p.name]));
  const fail = (e: unknown) => !(e instanceof StaleSessionError) && setMessage(messageOf(e));

  const refresh = useMutation({ mutationFn: refreshSession, onSuccess: reload, onError: fail });
  const stop = useMutation({ mutationFn: stopSession, onSuccess: reload, onError: fail });

  return (
    <div className="space-y-4">
      <Card eyebrow="DEVELOPMENT" title="Coding agents">
        <p className="mb-2 text-sm text-[var(--muted)]">Projects and sessions managed by Reachy. Sessions started with a subscription login run read-only; an API key can write to the repository. Terminal sessions you start yourself are not visible here.</p>
        <div className="mb-2 flex items-center justify-between gap-2">
          <p role="status" className="min-h-5 text-sm">{message || (projects.error && !(projects.error instanceof StaleSessionError) ? projects.error.message : '')}</p>
          <Button variant="secondary" onClick={() => void reload()}>Refresh</Button>
        </div>
        <AllowanceBox query={allowance} />
      </Card>

      <Card title="Projects">
        {projects.isPending && <Spinner label="Loading projects" />}
        <ul className="mb-3 list-disc pl-5 text-sm">
          {(projects.data ?? []).map((p) => <li key={p.id}>{`${p.name} — ${p.repository_path} (${p.default_branch}, ${p.provider})`}</li>)}
        </ul>
        {projects.data?.length === 0 && <EmptyState>No projects yet. Add one below.</EmptyState>}
        <ProjectForm onAdded={() => { setMessage('Project added.'); void reload(); }} onError={fail} />
      </Card>

      <Card title="Start a session">
        <SessionForm projects={projects.data ?? []} onAsk={setStarting} onMissing={() => setMessage('Add a project first.')} />
      </Card>

      <Card title="Terminal sessions">
        <p className="mb-2 text-sm text-[var(--muted)]">Claude Code sessions you ran yourself, read from the host's session history. These are shown for monitoring only; Reachy cannot control them.</p>
        {terminal.error && !(terminal.error instanceof StaleSessionError) && <p className="text-sm">{`Terminal sessions unavailable: ${terminal.error.message}`}</p>}
        {terminal.data?.length === 0 && <EmptyState>No terminal sessions found. The host session history may not be mounted (CLAUDE_PROJECTS_DIR).</EmptyState>}
        {(terminal.data ?? []).map((s) => (
          <div key={s.session_id} className="mb-2 rounded border border-[var(--border)] p-2">
            <strong className="break-words">{(s.active ? 'Active — ' : '') + (s.title || s.session_id)}</strong>
            <p className="break-words text-sm text-[var(--muted)]">{`${s.project_path || 'Unknown folder'}${s.git_branch ? ' · ' + s.git_branch : ''} · last activity ${when(s.last_activity_at)}`}</p>
            {s.last_prompt && <p className="break-words text-sm text-[var(--muted)]">{`Last prompt: ${s.last_prompt}`}</p>}
          </div>
        ))}
      </Card>

      <Card title="Sessions">
        {sessions.isPending && <Spinner label="Loading sessions" />}
        {sessions.data?.length === 0 && <EmptyState>No sessions yet. Start one above.</EmptyState>}
        {(sessions.data ?? []).map((s) => (
          <SessionCard key={s.id} session={s} project={names[s.project_id] || 'Unknown project'} onRefresh={() => refresh.mutate(s.id)} onStop={() => setStopping(s)} />
        ))}
      </Card>

      <Dialog open={starting !== null} title="Start a coding session?" onClose={() => setStarting(null)}>
        <h2 className="text-lg font-semibold">Start a coding session?</h2>
        <p className="my-3 break-words text-sm">
          {starting ? `Start a coding session on "${starting.project.name}"?${starting.project.provider === 'simulated' ? '' : ' This spends Claude usage, and with an API key it can change files in the repository.'}` : ''}
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setStarting(null)}>Cancel</Button>
          <Button
            onClick={() => {
              const go = starting;
              setStarting(null);
              if (!go) return;
              startSession({ project_id: go.project.id, task_summary: go.task, branch: go.branch })
                .then(() => { setMessage('Session started.'); return reload(); })
                .catch(fail);
            }}
          >
            Start session
          </Button>
        </div>
      </Dialog>
      <Dialog open={stopping !== null} title="Stop this coding session?" onClose={() => setStopping(null)}>
        <h2 className="text-lg font-semibold">Stop this coding session?</h2>
        <p className="my-3 text-sm">Stop this coding session?</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setStopping(null)}>Cancel</Button>
          <Button onClick={() => { const s = stopping; setStopping(null); if (s) stop.mutate(s.id); }}>Stop</Button>
        </div>
      </Dialog>
    </div>
  );
}

function AllowanceBox({ query }: { query: ReturnType<typeof useQuery<import('../../api/types').Allowance>> }) {
  return (
    <section aria-label="Claude allowance" className="rounded border border-[var(--border)] p-2 text-sm">
      <h3 className="font-medium">Claude allowance</h3>
      {query.isPending && <p className="text-[var(--muted)]">Loading…</p>}
      {query.error && !(query.error instanceof StaleSessionError) && <p>{`Allowance unavailable: ${query.error.message}`}</p>}
      {query.data && query.data.windows.length === 0 && (
        <p>No allowance reading available. Save a Claude account usage credential in Settings · Accounts to see the live 5-hour and weekly figures.</p>
      )}
      {query.data && query.data.windows.length > 0 && (
        <>
          <strong>{query.data.source === 'live' ? 'Live from your Claude account' : 'Last reported by Claude Code'}</strong>
          {query.data.windows.map((d, i) => <div key={i}>{dimensionText(d)}</div>)}
        </>
      )}
    </section>
  );
}

function ProjectForm({ onAdded, onError }: { onAdded: () => void; onError: (e: unknown) => void }) {
  const [name, setName] = useState('');
  const [path, setPath] = useState('');
  const [branch, setBranch] = useState('main');
  const [provider, setProvider] = useState('claude-code');
  function submit(event: FormEvent) {
    event.preventDefault();
    addProject({ name: name.trim(), repository_path: path.trim(), default_branch: branch.trim() || 'main', provider })
      .then(() => { setName(''); setPath(''); setBranch('main'); onAdded(); })
      .catch(onError);
  }
  const field = 'mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2';
  return (
    <form onSubmit={submit}>
      <h3 className="font-medium">Add a project</h3>
      <label className="mb-2 block text-sm">Name<input className={field} required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label className="mb-2 block text-sm">Repository path (on the robot host)<input className={field} required maxLength={4096} value={path} onChange={(e) => setPath(e.target.value)} /></label>
      <label className="mb-2 block text-sm">Default branch<input className={field} maxLength={200} value={branch} onChange={(e) => setBranch(e.target.value)} /></label>
      <label className="mb-2 block text-sm">
        Provider
        <select className={selectClass} value={provider} onChange={(e) => setProvider(e.target.value)}>
          <option value="claude-code">Claude Code</option>
          <option value="simulated">Simulated (no real work)</option>
        </select>
      </label>
      <Button type="submit">Add project</Button>
    </form>
  );
}

function SessionForm({ projects, onAsk, onMissing }: { projects: CodingProject[]; onAsk: (v: { project: CodingProject; task: string; branch: string | null }) => void; onMissing: () => void }) {
  const [projectId, setProjectId] = useState('');
  const [task, setTask] = useState('');
  const [branch, setBranch] = useState('');
  const selected = projects.find((p) => p.id === projectId) ?? projects[0];
  const field = 'mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2';
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!selected) return onMissing();
        onAsk({ project: selected, task: task.trim(), branch: branch.trim() || null });
        setTask('');
        setBranch('');
      }}
    >
      <label className="mb-2 block text-sm">
        Project
        <select className={selectClass} value={selected?.id ?? ''} onChange={(e) => setProjectId(e.target.value)}>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </label>
      <label className="mb-2 block text-sm">Task<textarea className={field} required rows={3} maxLength={4000} value={task} onChange={(e) => setTask(e.target.value)} /></label>
      <label className="mb-2 block text-sm">Branch (optional)<input className={field} value={branch} onChange={(e) => setBranch(e.target.value)} /></label>
      <Button type="submit">Start session</Button>
    </form>
  );
}

function SessionCard({ session, project, onRefresh, onStop }: { session: CodingSession; project: string; onRefresh: () => void; onStop: () => void }) {
  const [open, setOpen] = useState<'events' | 'usage' | null>(null);
  const detail = useQuery({
    queryKey: ['coding', 'detail', session.id, open],
    queryFn: async () => (open === 'events' ? { events: await sessionEvents(session.id) } : { usage: await sessionUsage(session.id) }),
    enabled: open !== null,
    refetchInterval: CODING_POLL_MS,
    retry: false,
  });
  return (
    <div className="mb-3 rounded border border-[var(--border)] p-2">
      <strong className="break-words">{`${project} — ${words(session.status)}`}</strong>
      <p className="break-words">{session.task_summary}</p>
      <p className="text-sm text-[var(--muted)]">{`Started ${when(session.started_at)} · last activity ${when(session.last_activity_at)}${session.branch ? ' · ' + session.branch : ''}`}</p>
      {session.last_event && <p className="break-words text-sm text-[var(--muted)]">{session.last_event}</p>}
      <div className="mt-1 flex flex-wrap gap-2">
        <Button variant="secondary" aria-pressed={open === 'events'} onClick={() => setOpen(open === 'events' ? null : 'events')}>Events</Button>
        <Button variant="secondary" aria-pressed={open === 'usage'} onClick={() => setOpen(open === 'usage' ? null : 'usage')}>Usage</Button>
        {ACTIVE.has(session.status) && <Button variant="secondary" onClick={onRefresh}>Refresh status</Button>}
        {ACTIVE.has(session.status) && <Button variant="secondary" onClick={onStop}>Stop</Button>}
      </div>
      {open && (
        <div className="mt-2 text-sm text-[var(--muted)]">
          {detail.error && !(detail.error instanceof StaleSessionError) && detail.error.message}
          {detail.data?.events && (detail.data.events.length ? detail.data.events.map((e, i) => <div key={i}>{`${when(e.timestamp)} · ${words(e.type)} · ${e.summary}`}</div>) : 'No events recorded.')}
          {detail.data?.usage && (detail.data.usage.length ? detail.data.usage.map((d, i) => <div key={i}>{dimensionText(d)}</div>) : 'No usage figures recorded for this session.')}
        </div>
      )}
    </div>
  );
}
