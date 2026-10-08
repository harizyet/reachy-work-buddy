import { useState, type FormEvent } from 'react';
import { StaleSessionError } from '../../api/client';
import type { Persona } from '../../api/types';
import { useNotice } from '../../components/shared/notice';
import { ErrorState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Spinner } from '../../components/ui/Spinner';
import { useChat } from '../chat/ChatProvider';
import { Check, Field, TextField, selectClass } from './fields';
import { usePersona, useSavePersona, useSaveSession, useSessionFor } from './useSettings';

export const DEFAULT_PERSONA_NAME = 'Reachy';
export const DEFAULT_PERSONA_PROMPT =
  'You are Reachy, an embodied work assistant. You help with tasks, calendar, email, reminders, and general questions. Keep replies concise and practical, and be clear when something is outside what you can do.';
const TONES = ['default', 'cheery', 'serious', 'formal', 'casual', 'playful', 'calm'];
const MODES = ['desk', 'office', 'silent', 'remote', 'trusted'];
const message = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong');

export function AssistantTab() {
  return (
    <div className="space-y-4">
      <SessionCard />
      <PersonaCard />
    </div>
  );
}

function SessionCard() {
  const chat = useChat();
  const { setNotice } = useNotice();
  const session = useSessionFor(chat.user);
  const save = useSaveSession(chat.user);
  return (
    <Card eyebrow="YOUR WORKDAY" title="Session controls">
      {!chat.ownerBound && (
        <form
          className="mb-2 flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            chat.chooseUser(chat.userInput);
          }}
        >
          <label className="flex-1 text-sm">
            User ID
            <input className={selectClass} required value={chat.userInput} onChange={(e) => chat.setUserInput(e.target.value)} />
          </label>
          <Button variant="secondary" type="submit">
            Load session
          </Button>
        </form>
      )}
      {session.isPending && <Spinner label="Loading session" />}
      {session.error && (
        <p role="status" className="text-sm">
          {'status' in session.error && (session.error as { status?: number }).status === 404 ? 'No session yet. Your first message will start one.' : message(session.error)}
        </p>
      )}
      {session.data && (
        <SessionForm
          key={`${session.data.interaction_mode}|${session.data.dnd}`}
          mode={session.data.interaction_mode}
          dnd={session.data.dnd}
          channel={session.data.active_channel}
          busy={save.isPending}
          error={save.error && !(save.error instanceof StaleSessionError) ? message(save.error) : ''}
          onSave={(mode, dnd) => save.mutate({ mode, dnd }, { onSuccess: () => setNotice('Session settings saved.') })}
        />
      )}
    </Card>
  );
}

function SessionForm({ mode, dnd, channel, busy, error, onSave }: { mode: string; dnd: boolean; channel: string; busy: boolean; error: string; onSave: (mode: string, dnd: boolean) => void }) {
  const [m, setM] = useState(mode);
  const [d, setD] = useState(dnd);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSave(m, d);
      }}
    >
      <p role="status" className="mb-2 text-sm">{`Active channel: ${channel}`}</p>
      <Field label="Mode">
        <select className={selectClass} value={m} onChange={(e) => setM(e.target.value)}>
          {MODES.map((x) => (
            <option key={x} value={x}>{x[0]!.toUpperCase() + x.slice(1)}</option>
          ))}
        </select>
      </Field>
      <Check label="Do not disturb" checked={d} onChange={setD} />
      {error && <p role="alert" className="mb-2 text-sm text-[var(--bad)]">{error}</p>}
      <Button type="submit" disabled={busy}>
        Save session
      </Button>
    </form>
  );
}

function PersonaCard() {
  const persona = usePersona();
  return (
    <Card eyebrow="IDENTITY" title="Assistant persona">
      <p className="mb-3 text-sm">Controls how the assistant introduces and describes itself in conversation. Applies to the next conversation turn.</p>
      {persona.isPending && <Spinner label="Loading persona" />}
      {persona.error && !persona.data && <ErrorState message={persona.error.message} onRetry={() => void persona.refetch()} />}
      {persona.data && <PersonaForm key={JSON.stringify(persona.data)} initial={persona.data} />}
    </Card>
  );
}

function PersonaForm({ initial }: { initial: Persona }) {
  const save = useSavePersona();
  const { setNotice } = useNotice();
  const [name, setName] = useState(initial.name);
  const [prompt, setPrompt] = useState(initial.system_prompt);
  const [tone, setTone] = useState(initial.tone);
  const [location, setLocation] = useState(initial.location ?? '');
  const [timezone, setTimezone] = useState(initial.timezone);

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate(
      { name: name.trim(), system_prompt: prompt.trim(), location: location.trim() || null, timezone: timezone.trim() || 'UTC', tone },
      { onSuccess: () => setNotice('Persona saved.') },
    );
  }
  return (
    <form onSubmit={submit}>
      <TextField label="Name" required maxLength={64} placeholder="Reachy" value={name} onChange={(e) => setName(e.target.value)} />
      <Field label="System prompt" hint="Sent to the model ahead of every conversation turn.">
        <textarea className={selectClass} rows={5} required maxLength={4000} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      </Field>
      <Field label="Tone" hint="Sets the style of replies. It never changes what the assistant is allowed to do.">
        <select className={selectClass} value={tone} onChange={(e) => setTone(e.target.value)}>
          {TONES.map((t) => (
            <option key={t} value={t}>{t[0]!.toUpperCase() + t.slice(1)}</option>
          ))}
        </select>
      </Field>
      <TextField label="Location" maxLength={120} placeholder="Singapore" value={location} onChange={(e) => setLocation(e.target.value)} />
      <TextField label="Time zone" maxLength={64} placeholder="Asia/Singapore" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
      <Button variant="secondary" className="mb-2" onClick={() => setTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone)}>
        Use this browser's time zone
      </Button>
      <p className="mb-3 text-sm text-[var(--muted)]">
        Every conversation turn tells the model the local date, time and location. A weather question that names no place is searched for this location, so the search provider receives it too.
      </p>
      {save.error && !(save.error instanceof StaleSessionError) && <p role="alert" className="mb-2 text-sm text-[var(--bad)]">{message(save.error)}</p>}
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          Save persona
        </Button>
        <Button
          variant="secondary"
          onClick={() => {
            setName(DEFAULT_PERSONA_NAME);
            setPrompt(DEFAULT_PERSONA_PROMPT);
            setTone('default');
            setNotice('Default persona loaded — click Save persona to apply.');
          }}
        >
          Reset to default
        </Button>
      </div>
    </form>
  );
}
