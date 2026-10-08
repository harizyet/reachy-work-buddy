import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  completeReminder,
  createReminder,
  createTask,
  deleteReminder,
  deleteTask,
  listReminders,
  listTasks,
  renameTask,
  setTaskDone,
} from '../../api/planner';

const TASKS = ['planner', 'tasks'] as const;
const REMINDERS = ['planner', 'reminders'] as const;

// The legacy tabs reload their list each time they are opened, and after every change.
export const useTasks = () =>
  useQuery({ queryKey: TASKS, queryFn: ({ signal }) => listTasks(signal), refetchOnMount: 'always' });
export const useReminders = () =>
  useQuery({ queryKey: REMINDERS, queryFn: ({ signal }) => listReminders(signal), refetchOnMount: 'always' });

function useChange<V>(key: readonly string[], run: (value: V) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    // Reload even after a failure: the hub, not this page, says what the list now is.
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  });
}

export const useAddTask = () => useChange(TASKS, (text: string) => createTask(text));
export const useRenameTask = () => useChange(TASKS, (v: { id: string; text: string }) => renameTask(v.id, v.text));
export const useToggleTask = () => useChange(TASKS, (v: { id: string; done: boolean }) => setTaskDone(v.id, v.done));
export const useDeleteTask = () => useChange(TASKS, (id: string) => deleteTask(id));
export const useAddReminder = () =>
  useChange(REMINDERS, (v: { text: string; dueAt: Date }) => createReminder(v.text, v.dueAt));
export const useCompleteReminder = () => useChange(REMINDERS, (id: string) => completeReminder(id));
export const useDeleteReminder = () => useChange(REMINDERS, (id: string) => deleteReminder(id));
