import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createAlarm,
  deleteAlarm,
  deleteStation,
  listAlarms,
  listStations,
  saveStation,
  setAlarmEnabled,
  stopAlarm,
  updateAlarm,
  type AlarmInput,
} from '../../api/planner';

const ALARMS = ['planner', 'alarms'] as const;
const STATIONS = ['planner', 'stations'] as const;

export const useAlarmList = () =>
  useQuery({ queryKey: ALARMS, queryFn: ({ signal }) => listAlarms(signal), refetchOnMount: 'always' });
export const useStationList = () =>
  useQuery({ queryKey: STATIONS, queryFn: ({ signal }) => listStations(signal), refetchOnMount: 'always' });

function useChange<V, R = unknown>(keys: (readonly string[])[], run: (value: V) => Promise<R>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => Promise.all(keys.map((queryKey) => client.invalidateQueries({ queryKey }))),
  });
}

export const useSaveAlarm = () =>
  useChange<{ id: string | null; input: AlarmInput }>([ALARMS], (v) => (v.id ? updateAlarm(v.id, v.input) : createAlarm(v.input)));
export const useToggleAlarm = () => useChange<{ id: string; enabled: boolean }>([ALARMS], (v) => setAlarmEnabled(v.id, v.enabled));
export const useDeleteAlarm = () => useChange<string>([ALARMS], (id) => deleteAlarm(id));
export const useSaveStation = () => useChange<{ name: string; guideId: string }>([STATIONS], (v) => saveStation(v.name, v.guideId));
export const useDeleteStation = () => useChange<string>([STATIONS], (id) => deleteStation(id));
export const useStopAlarm = () => useMutation({ mutationFn: stopAlarm });
