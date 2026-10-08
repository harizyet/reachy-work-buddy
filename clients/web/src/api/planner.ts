import { request } from './client';
import {
  parseNote,
  parseNotes,
  parseReceipts,
  parseReminder,
  parseReminders,
  parseTask,
  parseTasks,
  type Note,
  type Receipt,
  type Reminder,
  type Task,
} from './types';

const id = encodeURIComponent;

// Tasks
export const listTasks = async (signal?: AbortSignal): Promise<Task[]> => parseTasks(await request('/planner/tasks', { signal }));
export const createTask = async (text: string): Promise<Task> =>
  parseTask(await request('/planner/tasks', { method: 'POST', body: { text } }));
export const renameTask = async (taskId: string, text: string): Promise<Task> =>
  parseTask(await request(`/planner/tasks/${id(taskId)}`, { method: 'PUT', body: { text } }));
export const setTaskDone = async (taskId: string, done: boolean): Promise<Task> =>
  parseTask(await request(`/planner/tasks/${id(taskId)}/${done ? 'complete' : 'reopen'}`, { method: 'POST' }));
export const deleteTask = async (taskId: string): Promise<void> => {
  await request(`/planner/tasks/${id(taskId)}`, { method: 'DELETE' });
};

// Reminders (the hub can complete and delete one, not reopen or edit it)
export const listReminders = async (signal?: AbortSignal): Promise<Reminder[]> =>
  parseReminders(await request('/planner/reminders', { signal }));
export const createReminder = async (text: string, dueAt: Date): Promise<Reminder> =>
  parseReminder(await request('/planner/reminders', { method: 'POST', body: { text, due_at: dueAt.toISOString() } }));
export const completeReminder = async (reminderId: string): Promise<Reminder> =>
  parseReminder(await request(`/planner/reminders/${id(reminderId)}/complete`, { method: 'POST' }));
export const deleteReminder = async (reminderId: string): Promise<void> => {
  await request(`/planner/reminders/${id(reminderId)}`, { method: 'DELETE' });
};

// Notes
export const listNotes = async (query: string, signal?: AbortSignal): Promise<Note[]> =>
  parseNotes(await request(`/planner/notes${query ? `?q=${encodeURIComponent(query)}` : ''}`, { signal }));
export const createNote = async (title: string, body: string): Promise<Note> =>
  parseNote(await request('/planner/notes', { method: 'POST', body: { title, body } }));
export const saveNote = async (noteId: string, title: string, body: string): Promise<Note> =>
  parseNote(await request(`/planner/notes/${id(noteId)}`, { method: 'PUT', body: { title, body } }));
export const deleteNote = async (noteId: string): Promise<void> => {
  await request(`/planner/notes/${id(noteId)}`, { method: 'DELETE' });
};

// Activity
export const listReceipts = async (signal?: AbortSignal): Promise<Receipt[]> =>
  parseReceipts(await request('/planner/receipts', { signal }));

// Alarms and stations
import { parseAlarm, parseAlarms, parseStationHits, parseStations, type Alarm, type Station, type StationHit } from './types';

export interface AlarmInput {
  label: string;
  time: string; // "HH:MM", read by the server in the assistant's time zone
  repeat: number[];
  station_id: string | null;
  volume: number;
}

export const listAlarms = async (signal?: AbortSignal): Promise<Alarm[]> => parseAlarms(await request('/planner/alarms', { signal }));
export const createAlarm = async (input: AlarmInput): Promise<Alarm> =>
  parseAlarm(await request('/planner/alarms', { method: 'POST', body: input }));
export const updateAlarm = async (alarmId: string, input: AlarmInput): Promise<Alarm> =>
  parseAlarm(await request(`/planner/alarms/${id(alarmId)}`, { method: 'PATCH', body: input }));
export const setAlarmEnabled = async (alarmId: string, enabled: boolean): Promise<Alarm> =>
  parseAlarm(await request(`/planner/alarms/${id(alarmId)}`, { method: 'PATCH', body: { enabled } }));
export const deleteAlarm = async (alarmId: string): Promise<void> => {
  await request(`/planner/alarms/${id(alarmId)}`, { method: 'DELETE' });
};
export const stopAlarm = async (): Promise<boolean> => {
  const result = (await request('/planner/alarms/stop', { method: 'POST' })) as { stopped?: unknown };
  return result.stopped === true;
};
export const listStations = async (signal?: AbortSignal): Promise<Station[]> =>
  parseStations(await request('/planner/stations', { signal }));
export const searchStations = async (query: string, signal?: AbortSignal): Promise<StationHit[]> =>
  parseStationHits(await request(`/planner/stations/search?q=${encodeURIComponent(query)}`, { signal }));
export const saveStation = async (name: string, guideId: string): Promise<void> => {
  await request('/planner/stations', { method: 'POST', body: { name, guide_id: guideId } });
};
export const deleteStation = async (stationId: string): Promise<void> => {
  await request(`/planner/stations/${id(stationId)}`, { method: 'DELETE' });
};
