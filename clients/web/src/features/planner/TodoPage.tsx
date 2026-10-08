import { useEffect, useRef, useState } from 'react';
import { StaleSessionError } from '../../api/client';
import type { Task } from '../../api/types';
import { EmptyState } from '../../components/shared/states';
import { CompletedToggle, DeleteButton, ListShell, RoundCheck } from './ListShell';
import { useAddTask, useDeleteTask, useRenameTask, useTasks, useToggleTask } from './usePlanner';

const ACCENT = '#d4352f';

export function TodoPage() {
  const tasks = useTasks();
  const add = useAddTask();
  const rename = useRenameTask();
  const toggle = useToggleTask();
  const remove = useDeleteTask();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [showDone, setShowDone] = useState(false);

  const failure = [add, rename, toggle, remove].map((m) => m.error).find((e) => e && !(e instanceof StaleSessionError));
  const open = (tasks.data ?? []).filter((t) => t.status === 'open');
  const done = (tasks.data ?? []).filter((t) => t.status === 'done');

  return (
    <ListShell
      title="To Do"
      accent={ACCENT}
      onRefresh={() => void tasks.refetch()}
      refreshing={tasks.isFetching}
      loading={tasks.isPending}
      error={tasks.error && !tasks.data ? tasks.error.message : null}
      onRetry={() => void tasks.refetch()}
      status={failure?.message ?? ''}
    >
      <ul className="divide-y divide-[var(--border)]">
        {open.map((task) => (
          <TaskRow
            key={task.id}
            task={task}
            editing={editing === task.id}
            onEdit={() => setEditing(task.id)}
            onFinishEdit={(text) => {
              setEditing(null);
              if (text !== null && text !== task.text) rename.mutate({ id: task.id, text });
            }}
            onToggle={() => toggle.mutate({ id: task.id, done: true })}
            onDelete={() => remove.mutate(task.id)}
          />
        ))}
        {adding && (
          <NewTaskRow
            onAdd={(text) => add.mutate(text)} // the row stays open (empty) for the next one, as in the legacy list
            onClose={() => setAdding(false)}
          />
        )}
      </ul>
      {tasks.data && tasks.data.length === 0 && !adding && <EmptyState>Nothing to do yet.</EmptyState>}
      <CompletedToggle count={done.length} open={showDone} onToggle={() => setShowDone((v) => !v)} controls="todo-done" />
      {showDone && done.length > 0 && (
        <ul id="todo-done" className="divide-y divide-[var(--border)]">
          {done.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              editing={editing === task.id}
              onEdit={() => setEditing(task.id)}
              onFinishEdit={(text) => {
                setEditing(null);
                if (text !== null && text !== task.text) rename.mutate({ id: task.id, text });
              }}
              onToggle={() => toggle.mutate({ id: task.id, done: false })}
              onDelete={() => remove.mutate(task.id)}
            />
          ))}
        </ul>
      )}
      <button
        type="button"
        className="mt-4 flex items-center gap-2 text-lg font-medium"
        style={{ color: ACCENT }}
        onClick={() => setAdding(true)}
      >
        <span aria-hidden="true">+</span> New Reminder
      </button>
    </ListShell>
  );
}

function TaskRow({
  task,
  editing,
  onEdit,
  onFinishEdit,
  onToggle,
  onDelete,
}: {
  task: Task;
  editing: boolean;
  onEdit: () => void;
  onFinishEdit: (text: string | null) => void;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const isDone = task.status === 'done';
  const [draft, setDraft] = useState(task.text);
  const finished = useRef(false);
  useEffect(() => {
    if (editing) {
      setDraft(task.text);
      finished.current = false;
    }
  }, [editing, task.text]);
  const finish = (save: boolean) => {
    if (finished.current) return; // Enter then blur must not save twice
    finished.current = true;
    onFinishEdit(save && draft.trim() ? draft.trim() : null);
  };
  return (
    <li className="flex items-center gap-3 py-2">
      <RoundCheck checked={isDone} label={`${isDone ? 'Reopen' : 'Complete'}: ${task.text}`} onChange={onToggle} />
      <span className="min-w-0 flex-1">
        {editing ? (
          <input
            autoFocus
            aria-label="Edit to-do"
            maxLength={2000}
            className="w-full rounded border border-[var(--border)] bg-[var(--bg)] p-1"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') finish(true);
              if (e.key === 'Escape') finish(false);
            }}
            onBlur={() => finish(true)}
          />
        ) : (
          <button
            type="button"
            aria-label={`Edit: ${task.text}`}
            className={`block w-full break-words text-left ${isDone ? 'text-[var(--muted)] line-through' : ''}`}
            onClick={onEdit}
          >
            {task.text}
          </button>
        )}
      </span>
      <DeleteButton label={`Delete: ${task.text}`} onClick={onDelete} />
    </li>
  );
}

function NewTaskRow({ onAdd, onClose }: { onAdd: (text: string) => void; onClose: () => void }) {
  const [text, setText] = useState('');
  return (
    <li className="flex items-center gap-3 py-2">
      <input type="checkbox" disabled aria-hidden="true" tabIndex={-1} className="h-5 w-5 shrink-0 rounded-full" />
      <input
        autoFocus
        aria-label="New to-do"
        placeholder="New reminder"
        maxLength={2000}
        className="min-w-0 flex-1 rounded border border-[var(--border)] bg-[var(--bg)] p-1"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            const next = text.trim();
            if (!next) onClose();
            else {
              onAdd(next);
              setText('');
            }
          }
          if (e.key === 'Escape') onClose();
        }}
        onBlur={() => {
          if (!text.trim()) onClose();
        }}
      />
    </li>
  );
}
