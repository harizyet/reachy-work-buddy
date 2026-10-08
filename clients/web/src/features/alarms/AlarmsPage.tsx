import { useMutation } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { StaleSessionError } from '../../api/client';
import { searchStations } from '../../api/planner';
import type { Alarm, Station, StationHit } from '../../api/types';
import { EmptyState, ErrorState } from '../../components/shared/states';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Dialog } from '../../components/ui/Dialog';
import { Spinner } from '../../components/ui/Spinner';
import { byTimeOfDay, DAYS, dayLabel, isOn, repeatText, timeParts, wheelTime } from './alarmText';
import {
  useAlarmList,
  useDeleteAlarm,
  useDeleteStation,
  useSaveAlarm,
  useSaveStation,
  useStationList,
  useStopAlarm,
  useToggleAlarm,
} from './useAlarms';

export function AlarmsPage() {
  const alarms = useAlarmList();
  const stations = useStationList();
  const save = useSaveAlarm();
  const toggle = useToggleAlarm();
  const remove = useDeleteAlarm();
  const stop = useStopAlarm();
  const saveStation = useSaveStation();
  const removeStation = useDeleteStation();
  const [editMode, setEditMode] = useState(false);
  const [sheet, setSheet] = useState<{ alarm: Alarm | null } | null>(null);
  const [stopped, setStopped] = useState('');

  const failure = [save, toggle, remove, stop, saveStation, removeStation]
    .map((m) => m.error)
    .find((e) => e && !(e instanceof StaleSessionError));
  const visible = (alarms.data ?? []).filter((a) => a.status !== 'cancelled').sort(byTimeOfDay);
  const stationNames = new Map((stations.data ?? []).map((s) => [s.id, s.name]));

  return (
    <div className="space-y-4">
      <Card eyebrow="YOUR LISTS" title="Alarms">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            onClick={() =>
              stop.mutate(undefined, { onSuccess: (didStop) => setStopped(didStop ? 'Alarm stopped.' : 'No alarm is playing.') })
            }
          >
            Stop alarm
          </Button>
          <Button variant="secondary" onClick={() => void Promise.all([alarms.refetch(), stations.refetch()])}>
            Refresh
          </Button>
          <p role="status" className="min-h-5 flex-1 text-sm text-[var(--bad)]">
            {failure?.message ?? (stop.isPending ? '' : stopped)}
          </p>
        </div>
        <p className="mt-2 text-sm text-[var(--muted)]">
          Alarms play only when Reachy is listening for you and someone is detected in the room; otherwise you get a Telegram message instead.
        </p>
      </Card>

      <Card title="Alarm clock">
        <div className="mb-2 flex items-center justify-between">
          <Button variant="secondary" onClick={() => setEditMode((v) => !v)}>
            {editMode ? 'Done' : 'Edit'}
          </Button>
          <button
            type="button"
            aria-label="Add alarm"
            className="h-9 w-9 rounded-full bg-[var(--accent)] text-xl leading-none text-white"
            onClick={() => setSheet({ alarm: null })}
          >
            +
          </button>
        </div>
        {alarms.isPending && <Spinner label="Loading alarms" />}
        {alarms.error && !alarms.data && <ErrorState message={alarms.error.message} onRetry={() => void alarms.refetch()} />}
        {alarms.data && visible.length === 0 && <EmptyState>No alarms.</EmptyState>}
        <ul className="divide-y divide-[var(--border)]">
          {visible.map((alarm) => (
            <AlarmRow
              key={alarm.id}
              alarm={alarm}
              stationName={alarm.station_id ? (stationNames.get(alarm.station_id) ?? 'saved station') : ''}
              editMode={editMode}
              onOpen={() => setSheet({ alarm })}
              onToggle={(enabled) => toggle.mutate({ id: alarm.id, enabled })}
              onDelete={() => remove.mutate(alarm.id)}
            />
          ))}
        </ul>
      </Card>

      <StationsCard
        stations={stations.data ?? []}
        onSave={(hit) => saveStation.mutate({ name: hit.name, guideId: hit.guide_id })}
        onRemove={(id) => removeStation.mutate(id)}
      />

      <Dialog open={sheet !== null} title={sheet?.alarm ? 'Edit Alarm' : 'Add Alarm'} onClose={() => setSheet(null)}>
        {sheet && (
          <AlarmSheet
            alarm={sheet.alarm}
            stations={stations.data ?? []}
            onClose={() => setSheet(null)}
            onSave={(input) => {
              const id = sheet.alarm?.id ?? null;
              setSheet(null);
              save.mutate({ id, input });
            }}
            onDelete={() => {
              const id = sheet.alarm?.id;
              setSheet(null);
              if (id) remove.mutate(id);
            }}
          />
        )}
      </Dialog>
    </div>
  );
}

function AlarmRow({
  alarm,
  stationName,
  editMode,
  onOpen,
  onToggle,
  onDelete,
}: {
  alarm: Alarm;
  stationName: string;
  editMode: boolean;
  onOpen: () => void;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
}) {
  const on = isOn(alarm);
  const { time, suffix } = timeParts(alarm.due_at);
  const repeat = repeatText(alarm.repeat);
  const sub = [alarm.label, repeat || (on ? dayLabel(alarm.due_at) : '')].filter(Boolean).join(', ');
  const extra = [
    stationName,
    alarm.volume !== 100 ? `${alarm.volume}% volume` : '',
    alarm.status === 'fired' && alarm.delivery ? `last: ${alarm.delivery}` : '',
  ]
    .filter(Boolean)
    .join(' · ');
  return (
    <li className={`flex items-center gap-3 py-3 ${on ? '' : 'opacity-60'}`}>
      {editMode && (
        <button type="button" aria-label={`Delete alarm ${alarm.label}`} className="h-6 w-6 rounded-full bg-[var(--bad)] text-white" onClick={onDelete}>
          −
        </button>
      )}
      <button type="button" className="min-w-0 flex-1 text-left" onClick={onOpen}>
        <span className="block">
          <span className="text-4xl font-light">{time}</span> <span className="text-lg">{suffix}</span>
        </span>
        <span className="block break-words text-sm">{sub}</span>
        {extra && <span className="block break-words text-xs text-[var(--muted)]">{extra}</span>}
      </button>
      <input
        type="checkbox"
        role="switch"
        className="h-6 w-11 cursor-pointer accent-[var(--accent)]"
        checked={on}
        aria-label={`${alarm.label} ${time} ${suffix}`.trim()}
        onChange={(e) => onToggle(e.target.checked)}
      />
    </li>
  );
}

function AlarmSheet({
  alarm,
  stations,
  onClose,
  onSave,
  onDelete,
}: {
  alarm: Alarm | null;
  stations: Station[];
  onClose: () => void;
  onSave: (input: { label: string; time: string; repeat: number[]; station_id: string | null; volume: number }) => void;
  onDelete: () => void;
}) {
  const start = alarm ? new Date(alarm.due_at) : new Date(Date.now() + 60_000);
  const [hour, setHour] = useState(start.getHours() % 12 || 12);
  const [minute, setMinute] = useState(start.getMinutes());
  const [pm, setPm] = useState(start.getHours() >= 12);
  const [days, setDays] = useState<Set<number>>(new Set(alarm?.repeat ?? []));
  const [label, setLabel] = useState(alarm ? alarm.label : 'Alarm');
  const [stationId, setStationId] = useState(alarm?.station_id && stations.some((s) => s.id === alarm.station_id) ? alarm.station_id : '');
  const [volume, setVolume] = useState(alarm?.volume ?? 100);
  const sortedDays = [...days].sort((a, b) => a - b);

  function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = label.trim();
    if (!trimmed) return;
    onSave({ label: trimmed, time: wheelTime(hour, minute, pm), repeat: sortedDays, station_id: stationId || null, volume });
  }
  const select = 'rounded border border-[var(--border)] bg-[var(--bg)] p-2';
  return (
    <form onSubmit={submit}>
      <h2 className="mb-3 text-lg font-semibold">{alarm ? 'Edit Alarm' : 'Add Alarm'}</h2>
      <div role="group" aria-label="Alarm time" className="mb-3 flex gap-2">
        <select aria-label="Hour" className={select} value={hour} onChange={(e) => setHour(Number(e.target.value))}>
          {Array.from({ length: 12 }, (_, i) => i + 1).map((h) => (
            <option key={h} value={h}>{h}</option>
          ))}
        </select>
        <select aria-label="Minute" className={select} value={minute} onChange={(e) => setMinute(Number(e.target.value))}>
          {Array.from({ length: 60 }, (_, m) => m).map((m) => (
            <option key={m} value={m}>{String(m).padStart(2, '0')}</option>
          ))}
        </select>
        <select aria-label="AM or PM" className={select} value={pm ? 'PM' : 'AM'} onChange={(e) => setPm(e.target.value === 'PM')}>
          <option value="AM">AM</option>
          <option value="PM">PM</option>
        </select>
      </div>
      <div className="mb-3">
        <div className="flex justify-between text-sm">
          <span>Repeat</span>
          <span className="text-[var(--muted)]">{repeatText(sortedDays) || 'Never'}</span>
        </div>
        <div role="group" aria-label="Repeat on" className="mt-1 flex flex-wrap gap-1">
          {DAYS.map((name, day) => (
            <button
              key={name}
              type="button"
              aria-pressed={days.has(day)}
              className={`rounded-full border px-2 py-1 text-xs ${days.has(day) ? 'border-[var(--accent)] bg-[var(--accent)] text-white' : 'border-[var(--border)]'}`}
              onClick={() => {
                const next = new Set(days);
                if (next.has(day)) next.delete(day);
                else next.add(day);
                setDays(next);
              }}
            >
              {name}
            </button>
          ))}
        </div>
      </div>
      <label className="mb-3 block text-sm">
        Label
        <input className={`${select} mt-1 w-full`} value={label} maxLength={200} required autoComplete="off" onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label className="mb-3 block text-sm">
        Sound
        <select className={`${select} mt-1 w-full`} value={stationId} onChange={(e) => setStationId(e.target.value)}>
          <option value="">Chime (no station)</option>
          {stations.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      </label>
      <label className="mb-4 block text-sm">
        Volume <span data-testid="volume-value">{`${volume}%`}</span>
        <input className="mt-1 block w-full" type="range" min={10} max={400} step={10} value={volume} onChange={(e) => setVolume(Number(e.target.value))} />
      </label>
      <div className="flex items-center justify-between gap-2">
        {alarm ? (
          <Button variant="secondary" onClick={onDelete}>
            Delete Alarm
          </Button>
        ) : (
          <span />
        )}
        <span className="flex gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit">Save</Button>
        </span>
      </div>
    </form>
  );
}

function StationsCard({ stations, onSave, onRemove }: { stations: Station[]; onSave: (hit: StationHit) => void; onRemove: (id: string) => void }) {
  const [query, setQuery] = useState('');
  const search = useMutation({ mutationFn: (q: string) => searchStations(q) });
  function submit(event: FormEvent) {
    event.preventDefault();
    const q = query.trim();
    if (q.length < 2) return;
    search.mutate(q);
  }
  const error = search.error && !(search.error instanceof StaleSessionError) ? search.error.message : '';
  return (
    <Card title="Radio stations (TuneIn)">
      <form onSubmit={submit} className="mb-2 flex items-end gap-2">
        <label className="flex-1 text-sm">
          Find a station
          <input
            type="search"
            className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg)] p-2"
            minLength={2}
            maxLength={100}
            autoComplete="off"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <Button type="submit">Search</Button>
      </form>
      {error && <p role="alert" className="text-sm text-[var(--bad)]">{error}</p>}
      {search.data && search.data.length === 0 && <EmptyState>No stations found.</EmptyState>}
      <ul className="divide-y divide-[var(--border)]">
        {(search.data ?? []).map((hit) => (
          <li key={hit.guide_id} className="flex items-center justify-between gap-2 py-2">
            <span className="min-w-0 break-words">
              {hit.name}
              <br />
              <span className="text-sm text-[var(--muted)]">{hit.detail}</span>
            </span>
            <Button variant="secondary" aria-label={`Save station ${hit.name}`} onClick={() => onSave(hit)}>
              Save
            </Button>
          </li>
        ))}
      </ul>
      <h3 className="mt-3 font-medium">Saved stations</h3>
      {stations.length === 0 && <EmptyState>No saved stations.</EmptyState>}
      <ul className="divide-y divide-[var(--border)]">
        {stations.map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-2 py-2">
            <span className="break-words">{s.name}</span>
            <Button variant="secondary" aria-label={`Remove station ${s.name}`} onClick={() => onRemove(s.id)}>
              Remove
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
