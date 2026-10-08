import type { Meeting } from '../../api/types';

const STATUS_LABELS: Record<string, string> = {
  uploaded: 'Queued',
  preprocessing: 'Preparing audio',
  transcribing: 'Transcribing',
  diarizing: 'Identifying speakers',
  aligning: 'Ready',
  analyzing: 'Analyzing',
  complete: 'Complete',
  failed: 'Failed',
  cancelled: 'Cancelled',
};
export const statusLabel = (status: string) => STATUS_LABELS[status] ?? status;

export function statusDescription(meeting: Meeting): string {
  if (meeting.status === 'aligning') return 'Transcript and speakers are ready.';
  if (meeting.status === 'failed') return 'Processing failed. Open details for the technical error.';
  if (meeting.status === 'cancelled') return 'Processing was cancelled.';
  return '';
}

export function formatTimestamp(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '--:--';
  const total = Math.max(0, Math.round(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

/** Nothing is running for the meeting in these states, so it may be deleted. */
export const DELETABLE = ['complete', 'failed', 'cancelled', 'aligning'];
/** A usable transcript exists for summaries, minutes and use as context. */
export const READY = ['aligning', 'analyzing', 'complete'];
export const TERMINAL = ['complete', 'failed', 'cancelled'];

/** The owner's name wins over the diarization label; "SPEAKER_00" reads "Speaker 1". */
export function speakerName(meeting: Meeting, label: string): string {
  const named = meeting.speaker_names[label];
  if (named) return named;
  const match = /^SPEAKER_(\d+)$/.exec(label);
  return match ? `Speaker ${Number(match[1]) + 1}` : label;
}

export const silentSeconds = (meeting: Meeting) => meeting.audio_gaps?.seconds ?? 0;
export const silentSummary = (meeting: Meeting) =>
  `${formatTimestamp(Math.round(silentSeconds(meeting)))} of this recording has no audio — the phone stopped capturing sound (for example when it locked or another app used the microphone). Lines marked ⚠ may be missing or unreliable.`;

export const TIER_LABEL: Record<string, string> = { local: 'the local model', deep: 'the larger local model', cloud: 'the cloud model' };
