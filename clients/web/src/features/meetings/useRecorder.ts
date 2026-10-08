import { useCallback, useEffect, useRef, useState } from 'react';

const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];

// One clip recorded in the browser, uploaded through the same endpoint as a chosen file.
export function useRecorder() {
  const supported = typeof window !== 'undefined' && Boolean(window.MediaRecorder && navigator.mediaDevices?.getUserMedia);
  const mime = supported ? (MIME_CANDIDATES.find((t) => MediaRecorder.isTypeSupported(t)) ?? null) : null;
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [clip, setClip] = useState<{ blob: Blob; seconds: number } | null>(null);
  const [error, setError] = useState('');
  const stream = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const startedAt = useRef(0);
  const chunks = useRef<Blob[]>([]);

  useEffect(() => {
    if (!recording) return;
    const id = setInterval(() => setElapsed((Date.now() - startedAt.current) / 1000), 500);
    return () => clearInterval(id);
  }, [recording]);

  const release = () => {
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  };

  const start = useCallback(async () => {
    if (!supported) return;
    setClip(null);
    setError('');
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      setError(`Could not access the microphone: ${e instanceof Error ? e.message : 'unknown error'}`);
      return;
    }
    chunks.current = [];
    const r = mime ? new MediaRecorder(stream.current, { mimeType: mime }) : new MediaRecorder(stream.current);
    r.addEventListener('dataavailable', (event) => {
      if (event.data.size > 0) chunks.current.push(event.data);
    });
    r.addEventListener('stop', () => {
      setClip({ blob: new Blob(chunks.current, { type: r.mimeType || 'audio/webm' }), seconds: (Date.now() - startedAt.current) / 1000 });
      release();
    });
    recorder.current = r;
    startedAt.current = Date.now();
    setElapsed(0);
    r.start();
    setRecording(true);
  }, [supported, mime]);

  const stop = useCallback(() => {
    if (recorder.current && recorder.current.state !== 'inactive') recorder.current.stop();
    setRecording(false);
  }, []);

  const discard = useCallback(() => {
    setClip(null);
    setError('');
  }, []);

  // Leaving the page must not leave the microphone open.
  useEffect(
    () => () => {
      if (recorder.current && recorder.current.state !== 'inactive') recorder.current.stop();
      release();
    },
    [],
  );

  const extension = mime?.startsWith('audio/ogg') ? 'opus' : 'webm';
  return { supported, recording, elapsed, clip, error, start, stop, discard, extension };
}
