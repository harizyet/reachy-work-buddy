import { useState, type FormEvent } from 'react';
import { StaleSessionError } from '../../api/client';
import type { Reminder } from '../../api/types';
import { EmptyState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { dueText, nextHourInputs } from '../../utils/dates';
import { CompletedToggle, DeleteButton, ListShell, RoundCheck } from './ListShell';
import { useAddReminder, useCompleteReminder, useDeleteReminder, useReminders } from './usePlanner';

const ACCENT = '#7a42c8';
const byDue = (a: Reminder, b: Reminder) => new Date(a.due_at).getTime() - new Date(b.due_at).getTime();

export function RemindersPage() {
  const reminders = useReminders();
  const add = useAddReminder();
  const complete = useCompleteReminder();
  const remove = useDeleteReminder();
  const [showDone, setShowDone] = useState(false);
  const [sheet, setSheet] = useState(false);

  const failure = [add, complete, remove].map((m) => m.error).find((e) => e && !(e instanceof StaleSessionError));
  const pending = (reminders.data ?? []).filter((r) => r.status !== 'done').sort(byDue);
  const done = (reminders.data ?? []).filter((r) => r.status === 'done').sort((a, b) => byDue(b, a));

  return (
    <>
      <ListShell
        title="Reminders"
        accent={ACCENT}
        onRefresh={() => void reminders.refetch()}
        refreshing={reminders.isFetching}
        loading={reminders.isPending}
        error={reminders.error && !reminders.data ? reminders.error.message : null}
        onRetry={() => void reminders.refetch()}
        status={failure?.message ?? ''}
      >
        <p className="mb-2 text-sm text-[var(--muted)]">Reminders are also sent to your Telegram when they come due.</p>
        <ul className="divide-y divide-[var(--border)]">
          {pending.map((r) => (
            <ReminderRow key={r.id} reminder={r} onComplete={() => complete.mutate(r.id)} onDelete={() => remove.mutate(r.id)} />
          ))}
        </ul>
        {reminders.data && reminders.data.length === 0 && <EmptyState>No reminders.</EmptyState>}
        <CompletedToggle count={done.length} open={showDone} onToggle={() => setShowDone((v) => !v)} controls="reminders-done" />
        {showDone && done.length > 0 && (
          <ul id="reminders-done" className="divide-y divide-[var(--border)]">
            {done.map((r) => (
              <ReminderRow key={r.id} reminder={r} onComplete={() => undefined} onDelete={() => remove.mutate(r.id)} />
            ))}
          </ul>
        )}
        <button type="button" className="mt-4 flex items-center gap-2 text-lg font-medium" style={{ color: ACCENT }} onClick={() => setSheet(true)}>
          <span aria-hidden="true">+</span> New Reminder
        </button>
      </ListShell>
      <NewReminderSheet
        open={sheet}
        onClose={() => setSheet(false)}
        onSave={(text, dueAt) => {
          setSheet(false);
          add.mutate({ text, dueAt });
        }}
      />
    </>
  );
}

function ReminderRow({ reminder, onComplete, onDelete }: { reminder: Reminder; onComplete: () => void; onDelete: () => void }) {
  const isDone = reminder.status === 'done';
  const overdue = !isDone && new Date(reminder.due_at).getTime() <= Date.now();
  return (
    <li className="flex items-center gap-3 py-2">
      {/* The hub can complete a reminder but not reopen one, so a ticked circle stays ticked. */}
      <RoundCheck checked={isDone} disabled={isDone} label={`${isDone ? 'Completed' : 'Complete'}: ${reminder.text}`} onChange={onComplete} />
      <span className="min-w-0 flex-1">
        <span className={`block break-words ${isDone ? 'text-[var(--muted)] line-through' : ''}`}>{reminder.text}</span>
        <span className={`block text-sm ${overdue ? 'text-[var(--bad)]' : 'text-[var(--muted)]'}`}>
          {dueText(reminder.due_at) + (overdue ? ' · due' : '')}
        </span>
      </span>
      <DeleteButton label={`Delete: ${reminder.text}`} onClick={onDelete} />
    </li>
  );
}

function NewReminderSheet({ open, onClose, onSave }: { open: boolean; onClose: () => void; onSave: (text: string, dueAt: Date) => void }) {
  return (
    <Dialog open={open} title="New Reminder" onClose={onClose}>
      <SheetForm onClose={onClose} onSave={onSave} />
    </Dialog>
  );
}

// Mounted only while the dialog is open, so each opening starts from a fresh title and the next whole hour.
function SheetForm({ onClose, onSave }: { onClose: () => void; onSave: (text: string, dueAt: Date) => void }) {
  const initial = nextHourInputs();
  const [text, setText] = useState('');
  const [date, setDate] = useState(initial.date);
  const [time, setTime] = useState(initial.time);
  function submit(event: FormEvent) {
    event.preventDefault();
    const title = text.trim();
    if (!title || !date || !time) return;
    onSave(title, new Date(`${date}T${time}`));
  }
  const field = 'mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2';
  return (
    <form onSubmit={submit}>
      <h2 className="mb-3 text-lg font-semibold">New Reminder</h2>
      <label className="mb-3 block text-sm">
        Title
        <input autoFocus className={field} value={text} maxLength={500} required autoComplete="off" placeholder="Remind me to…" onChange={(e) => setText(e.target.value)} />
      </label>
      <label className="mb-3 block text-sm">
        Date
        <input className={field} type="date" value={date} required onChange={(e) => setDate(e.target.value)} />
      </label>
      <label className="mb-4 block text-sm">
        Time
        <input className={field} type="time" value={time} required onChange={(e) => setTime(e.target.value)} />
      </label>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit">Add</Button>
      </div>
    </form>
  );
}
