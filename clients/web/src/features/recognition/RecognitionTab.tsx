import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { StaleSessionError } from '../../api/client';
import { deleteAllSamples, deleteSample, exportSamples, getRecognition, reauthenticate, setBenchmark, uploadSample, type Kind } from '../../api/recognition';
import type { RecognitionSample } from '../../api/types';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Dialog } from '../../components/ui/Dialog';
import { saveBlob } from '../../utils/download';
import { Check, TextField } from '../settings/fields';

const KEY = ['recognition'] as const;
const formatBytes = (n: number) => (n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${Math.round(n / 1024)} KB` : `${(n / (1024 * 1024)).toFixed(1)} MB`);
const messageOf = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong');

// A benchmark dataset of raw voice and face samples, explicitly switched on. Nothing recognises anyone with it yet, and
// this is not the future enrolment flow. Camera and microphone streams are released as soon as the owner leaves this
// tab or signs out, and every captured blob is uploaded and then dropped from the browser.
export function RecognitionTab() {
  const client = useQueryClient();
  const status = useQuery({ queryKey: KEY, queryFn: ({ signal }) => getRecognition(signal), refetchOnMount: 'always', retry: false });
  const [reauthMessage, setReauthMessage] = useState('');
  const [benchMessage, setBenchMessage] = useState('');
  const [password, setPassword] = useState('');
  const [confirming, setConfirming] = useState<Kind | null>(null);
  const data = status.data;
  const fresh = data?.reauthenticated === true;
  const reload = () => client.invalidateQueries({ queryKey: KEY });
  const guard = async (say: (m: string) => void, action: () => Promise<void>) => {
    try {
      await action();
    } catch (e) {
      if (!(e instanceof StaleSessionError)) {
        say(messageOf(e));
        void reload(); // a 401 here may mean the confirmation ran out, or the session did; the status read tells which
      }
    }
  };

  return (
    <Card title="Owner recognition">
      <p className="mb-2 text-sm text-[var(--muted)]">
        Operational enrollment (a real speaker/face profile Reachy could use) does not exist yet — there is no recognition model in production. Everything below is the benchmark dataset used to build and evaluate that model.
      </p>
      <p role="status" className="min-h-5 text-sm">
        {reauthMessage ||
          (status.error && !(status.error instanceof StaleSessionError)
            ? status.error.message
            : fresh
              ? `Password confirmed — expires in about ${Math.ceil((data?.reauth_expires_in_seconds ?? 0) / 60)} minute(s).`
              : 'Confirm your password to change benchmark collection or manage samples.')}
      </p>
      <form
        className="mb-4 flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void guard(setReauthMessage, async () => {
            setReauthMessage('');
            await reauthenticate(password);
            setPassword('');
            await reload();
          });
        }}
      >
        <div className="flex-1">
          <TextField label="Password" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <Button type="submit" className="mb-3">Confirm password</Button>
      </form>

      <section aria-label="Benchmark dataset">
        <h3 className="font-medium">Benchmark dataset</h3>
        <p className="mb-2 text-sm">
          Voice and face samples for building and evaluating a real owner/non-owner recognition dataset (Phase 25a.1). Raw captures are kept, encrypted at rest, only while this is explicitly turned on — this is not the eventual production enrollment flow, which will delete raw captures once a template exists.
        </p>
        <Check
          label="Enable benchmark dataset collection"
          checked={data?.benchmark_enabled === true}
          disabled={!fresh}
          onChange={(enabled) => void guard(setBenchMessage, async () => { await setBenchmark(enabled); await reload(); })}
        />
        <p role="status" className="mb-3 text-sm">
          {benchMessage ||
            (data?.benchmark_enabled
              ? 'Benchmark dataset collection is on. Turning it off keeps samples already recorded.'
              : 'Off by default. Turn this on to record voice/face samples for the benchmark dataset.')}
        </p>
        {data && (
          <>
            <VoiceSection samples={data.voice_samples} bytes={data.voice_total_bytes} fresh={fresh} canCapture={fresh && data.benchmark_enabled} reload={reload} guard={guard} askDeleteAll={() => setConfirming('voice')} />
            <FaceSection samples={data.face_samples} bytes={data.face_total_bytes} fresh={fresh} canCapture={fresh && data.benchmark_enabled} reload={reload} guard={guard} askDeleteAll={() => setConfirming('face')} />
          </>
        )}
      </section>

      <Dialog open={confirming !== null} title={`Delete all ${confirming ?? ''} samples?`} onClose={() => setConfirming(null)}>
        <h2 className="text-lg font-semibold">{`Delete all ${confirming ?? ''} samples?`}</h2>
        <p className="my-3 text-sm">{`Delete all recorded ${confirming ?? ''} samples?`}</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirming(null)}>Cancel</Button>
          <Button
            onClick={() => {
              const kind = confirming;
              setConfirming(null);
              if (kind) void guard(() => undefined, async () => { await deleteAllSamples(kind); await reload(); });
            }}
          >
            Delete
          </Button>
        </div>
      </Dialog>
    </Card>
  );
}

type Guard = (say: (m: string) => void, action: () => Promise<void>) => Promise<void>;
interface SectionProps {
  samples: RecognitionSample[];
  bytes: number;
  fresh: boolean;
  canCapture: boolean;
  reload: () => Promise<void>;
  guard: Guard;
  askDeleteAll: () => void;
}

function SampleList({ kind, samples, fresh, reload, guard, say }: { kind: Kind; samples: RecognitionSample[]; fresh: boolean; reload: () => Promise<void>; guard: Guard; say: (m: string) => void }) {
  return (
    <ul className="my-2 text-sm">
      {samples.map((s) => (
        <li key={s.sample_id} className="py-1">
          {`${new Date(s.captured_at).toLocaleString()} · ${formatBytes(s.size_bytes)} `}
          <Button variant="secondary" disabled={!fresh} aria-label={`Delete ${kind} sample from ${new Date(s.captured_at).toLocaleString()}`} onClick={() => void guard(say, async () => { await deleteSample(kind, s.sample_id); await reload(); })}>
            Delete
          </Button>
        </li>
      ))}
      {samples.length === 0 && <li className="text-[var(--muted)]">No samples recorded yet.</li>}
    </ul>
  );
}

function VoiceSection({ samples, bytes, fresh, canCapture, reload, guard, askDeleteAll }: SectionProps) {
  const [message, setMessage] = useState('');
  const [recording, setRecording] = useState(false);
  const stream = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  const release = () => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    recorder.current = null;
    setRecording(false);
  };
  useEffect(() => () => {
    if (recorder.current && recorder.current.state !== 'inactive') recorder.current.stop();
    release();
  }, []); // leaving the tab turns the microphone off

  async function toggle() {
    if (recorder.current && recorder.current.state === 'recording') {
      recorder.current.stop();
      return;
    }
    if (!canCapture) return setMessage('Enable benchmark dataset collection first.');
    const media = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.current = media;
    chunks.current = [];
    const r = new MediaRecorder(media);
    recorder.current = r;
    r.addEventListener('dataavailable', (event) => {
      if (event.data.size) chunks.current.push(event.data);
    });
    r.addEventListener('stop', () => {
      const blob = new Blob(chunks.current, { type: r.mimeType || 'audio/webm' });
      chunks.current = [];
      release();
      void guard(setMessage, async () => {
        if (!blob.size) return setMessage('No audio captured; try again.');
        await uploadSample('voice', blob);
        setMessage('Voice sample saved.');
        await reload();
      });
    });
    r.start();
    setRecording(true);
    setMessage('Recording… speak normally, then select Stop recording.');
  }

  return (
    <div className="mb-4">
      <h4 className="font-medium">Voice samples</h4>
      <p className="mb-2 text-sm text-[var(--muted)]">Record a few short samples of your normal speaking voice, in the room and distance you'd usually talk to Reachy from.</p>
      <Button disabled={!canCapture && !recording} onClick={() => void guard(setMessage, toggle)}>{recording ? 'Stop recording' : 'Start recording'}</Button>
      <p role="status" className="text-sm">{message}</p>
      <p className="text-sm text-[var(--muted)]">{samples.length ? `${samples.length} sample(s), ${formatBytes(bytes)} total` : ''}</p>
      <SampleList kind="voice" samples={samples} fresh={fresh} reload={reload} guard={guard} say={setMessage} />
      <div className="flex gap-2">
        <Button variant="secondary" disabled={!fresh || samples.length === 0} onClick={askDeleteAll}>Delete all voice samples</Button>
        <Button variant="secondary" disabled={!fresh || samples.length === 0} onClick={() => void guard(setMessage, async () => saveBlob(await exportSamples('voice'), 'voice-benchmark-dataset.zip'))}>Export voice dataset</Button>
      </div>
    </div>
  );
}

function FaceSection({ samples, bytes, fresh, canCapture, reload, guard, askDeleteAll }: SectionProps) {
  const [message, setMessage] = useState('');
  const [camera, setCamera] = useState(false);
  const stream = useRef<MediaStream | null>(null);
  const video = useRef<HTMLVideoElement>(null);

  const stopCamera = () => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
    setCamera(false);
  };
  useEffect(() => stopCamera, []); // leaving the tab turns the camera off

  async function start() {
    if (!canCapture) return setMessage('Enable benchmark dataset collection first.');
    stream.current = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
    setCamera(true);
    setMessage('Camera on. Frame your face, then select Capture photo.');
  }
  useEffect(() => {
    if (camera && video.current && stream.current) video.current.srcObject = stream.current;
  }, [camera]);

  async function capture() {
    const v = video.current;
    if (!v) return;
    const canvas = document.createElement('canvas');
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext('2d')?.drawImage(v, 0, 0);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.9));
    if (!blob) return setMessage('Could not capture a photo; try again.');
    await uploadSample('face', blob);
    setMessage('Face sample saved.');
    await reload();
  }

  return (
    <div>
      <h4 className="font-medium">Face samples</h4>
      <p className="mb-2 text-sm text-[var(--muted)]">Capture a few photos at your normal distance from the robot, with different angles and lighting.</p>
      {camera && <video ref={video} autoPlay playsInline muted className="mb-2 max-w-full rounded" />}
      <div className="flex gap-2">
        {!camera && <Button disabled={!canCapture} onClick={() => void guard(setMessage, start)}>Turn on camera</Button>}
        {camera && <Button onClick={() => void guard(setMessage, capture)}>Capture photo</Button>}
        {camera && <Button variant="secondary" onClick={() => { stopCamera(); setMessage(''); }}>Turn off camera</Button>}
      </div>
      <p role="status" className="text-sm">{message}</p>
      <p className="text-sm text-[var(--muted)]">{samples.length ? `${samples.length} sample(s), ${formatBytes(bytes)} total` : ''}</p>
      <SampleList kind="face" samples={samples} fresh={fresh} reload={reload} guard={guard} say={setMessage} />
      <div className="flex gap-2">
        <Button variant="secondary" disabled={!fresh || samples.length === 0} onClick={askDeleteAll}>Delete all face samples</Button>
        <Button variant="secondary" disabled={!fresh || samples.length === 0} onClick={() => void guard(setMessage, async () => saveBlob(await exportSamples('face'), 'face-benchmark-dataset.zip'))}>Export face dataset</Button>
      </div>
    </div>
  );
}
