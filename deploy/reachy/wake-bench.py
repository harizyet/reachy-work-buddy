"""Phase 24g wake-detector and acoustic-filter cost on the robot host.

Streams 16 kHz mono WAV files through two candidate stages and reports
per-call latency, CPU time and resident memory, plus each clip's scores
as a sanity check that the models and features are wired correctly:

- wake: openWakeWord (ONNX) fed 80 ms chunks, as continuous monitoring
  would, with one inference thread;
- event: YAMNet (Qualcomm AI Hub ONNX export, log-mel patch input) over
  0.96 s patches with a 0.48 s hop, as the post-wake acoustic filter would
  run over a bounded candidate;
- eim: an Edge Impulse `.eim` keyword model (a native runner process
  driven over its Unix socket), stepped as the Edge Impulse SDK's audio
  runner does. Clips are resampled to the model's rate.

It reads files only: no microphone, daemon or hub. `--listen` instead
reads the robot microphone live (the shared `reachymini_audio_src` dsnoop
device, record-only) and prints scores as they happen; audio stays in
memory and is never written. Run it in a throwaway container of the
embodiment image so the numbers reflect the deployed runtime, for example:

    docker run --rm -v ~/24g-bench:/bench --entrypoint sh reachy-embodiment:local \\
      -c 'PYTHONPATH=/bench/py /app/.venv/bin/python /bench/wake-bench.py \\
          --models /bench/models --clips /bench/clips --wake hey_jarvis_v0.1'

`--eim` executes the given runner binary; run third-party models only in
that throwaway container with `--network none`. `--listen` additionally
needs the daemon user's ALSA config and IPC namespace, as the embodiment
container gets them (scripts/start-reachy.sh). OpenBLAS's idle worker
threads otherwise spin and double the listener's CPU:

    docker run --rm --name wake-listen --network none --ipc host --user 1000:1000 \\
      --device /dev/snd --group-add audio -e HOME=/tmp/h -e OPENBLAS_NUM_THREADS=1 \\
      -v ~/.asoundrc:/tmp/h/.asoundrc:ro -v ~/24g-bench:/bench:ro ...
      ... wake-bench.py --listen --models /bench/models --eim /bench/eim/<model>.eim

Model files are not in the repository; see
docs/verification for the sources and versions used in a recorded run.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import resource
import socket
import statistics
import subprocess
import tempfile
import time
import wave

import numpy as np

SR = 16000
CHUNK = 1280  # 80 ms, openWakeWord's native step


def resample(samples: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return samples
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(src, dst)
    out = resample_poly(samples.astype(np.float32), dst // g, src // g)
    return np.clip(out, -32768, 32767).astype(np.int16)


def load(path: str, rate: int = SR) -> np.ndarray:
    """Mono 16-bit WAV at any rate, resampled to `rate`."""
    with wave.open(path) as w:
        if (w.getnchannels(), w.getsampwidth()) != (1, 2):
            raise SystemExit(f"{path}: need mono 16-bit")
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        return resample(samples, w.getframerate(), rate)


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * len(ordered)) - 1))]


def summary(name: str, ms: list[float], cpu_s: float, audio_s: float) -> None:
    print(
        f"{name}: calls={len(ms)} p50={statistics.median(ms):.2f}ms "
        f"p95={pct(ms, 0.95):.2f}ms max={max(ms):.2f}ms "
        f"cpu={cpu_s:.2f}s for {audio_s:.1f}s audio "
        f"({100 * cpu_s / audio_s:.1f}% of one core)"
    )


# YAMNet's log-mel front end (tensorflow/models research/audioset/yamnet
# params.py/features.py): 25 ms periodic Hann window, 10 ms hop, 512-point
# FFT magnitude, 64 HTK mel bands 125-7500 Hz, log(mel + 0.001), 96-frame
# patches.
def _hz_to_mel(hz: np.ndarray) -> np.ndarray:
    return 1127.0 * np.log1p(hz / 700.0)


def _mel_matrix(
    bins: int = 64, fft_bins: int = 257, lo: float = 125.0, hi: float = 7500.0
) -> np.ndarray:
    spectrum_mel = _hz_to_mel(np.linspace(0.0, SR / 2, fft_bins))[1:]
    edges = np.linspace(_hz_to_mel(np.array(lo)), _hz_to_mel(np.array(hi)), bins + 2)
    lower, center, upper = edges[:-2], edges[1:-1], edges[2:]
    rising = (spectrum_mel[:, None] - lower) / (center - lower)
    falling = (upper - spectrum_mel[:, None]) / (upper - center)
    weights = np.maximum(0.0, np.minimum(rising, falling))
    return np.pad(weights, ((1, 0), (0, 0))).astype(np.float32)  # DC bin zeroed


_WINDOW = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(400) / 400)).astype(np.float32)
_MEL = _mel_matrix()


def log_mel(samples: np.ndarray) -> np.ndarray:
    x = samples.astype(np.float32) / 32768.0
    frames = 1 + (len(x) - 400) // 160
    idx = np.arange(400)[None, :] + 160 * np.arange(frames)[:, None]
    mag = np.abs(np.fft.rfft(x[idx] * _WINDOW, n=512))
    return np.log(mag @ _MEL + 0.001)


def bench_wake(args: argparse.Namespace, clips: list[str]) -> None:
    from openwakeword.model import Model

    before = rss_mb()
    model = Model(
        wakeword_models=[os.path.join(args.models, f"{args.wake}.onnx")],
        inference_framework="onnx",
        melspec_model_path=os.path.join(args.models, "melspectrogram.onnx"),
        embedding_model_path=os.path.join(args.models, "embedding_model.onnx"),
        ncpu=1,
    )
    print(f"wake model loaded: +{rss_mb() - before:.0f} MB peak RSS")
    ms: list[float] = []
    cpu = audio = 0.0
    # Warm-up so first-call allocation is not counted.
    model.predict(np.zeros(CHUNK, dtype=np.int16))
    for _ in range(args.repeat):
        for path in clips:
            # openWakeWord needs about a second of context before a
            # phrase; its own predict_clip pads the same way.
            pad = np.zeros(SR, dtype=np.int16)
            samples = np.concatenate([pad, load(path), pad])
            model.reset()
            best = 0.0
            for start in range(0, len(samples) - CHUNK + 1, CHUNK):
                t0, c0 = time.perf_counter(), time.process_time()
                scores = model.predict(samples[start : start + CHUNK])
                ms.append(1000 * (time.perf_counter() - t0))
                cpu += time.process_time() - c0
                best = max(best, max(scores.values()))
            audio += len(samples) / SR
            if _ == 0:
                print(f"  {os.path.basename(path)}: max {args.wake} score {best:.3f}")
    summary("wake", ms, cpu, audio)


def bench_event(args: argparse.Namespace, clips: list[str]) -> None:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = args.event_threads
    before = rss_mb()
    session = ort.InferenceSession(os.path.join(args.models, "yamnet.onnx"), options)
    print(f"event model loaded: +{rss_mb() - before:.0f} MB peak RSS")
    with open(os.path.join(args.models, "labels.txt")) as f:
        labels = [line.strip() for line in f]
    name = session.get_inputs()[0].name
    session.run(None, {name: np.zeros((1, 1, 96, 64), dtype=np.float32)})
    ms: list[float] = []
    cpu = audio = 0.0
    for _ in range(args.repeat):
        for path in clips:
            samples = load(path)
            t0, c0 = time.perf_counter(), time.process_time()
            mel = log_mel(samples)
            front_ms = 1000 * (time.perf_counter() - t0)
            # Peak score per class: a short cough in a mostly silent clip
            # would vanish from a mean.
            peaks = np.full(len(labels), -np.inf)
            patches = 0
            for start in range(0, len(mel) - 96 + 1, 48):
                t1 = time.perf_counter()
                (scores,) = session.run(
                    None, {name: mel[None, None, start : start + 96]}
                )
                ms.append(1000 * (time.perf_counter() - t1))
                peaks = np.maximum(peaks, scores[0])
                patches += 1
            cpu += time.process_time() - c0
            audio += len(samples) / SR
            if _ == 0 and patches:
                top = [i for i in np.argsort(peaks)[::-1] if labels[i] != "Silence"][:3]
                ranked = ", ".join(f"{labels[i]} {peaks[i]:.2f}" for i in top)
                print(
                    f"  {os.path.basename(path)}: front {front_ms:.1f}ms, {patches} patches: {ranked}"
                )
    summary(f"event ({args.event_threads} thread)", ms, cpu, audio)


class EimRunner:
    """Minimal Edge Impulse runner client: JSON requests on a Unix socket,
    each response terminated by a NUL byte (edge_impulse_linux/runner.py,
    whose package import needs pyaudio)."""

    def __init__(self, path: str) -> None:
        self._dir = tempfile.mkdtemp()
        sock_path = os.path.join(self._dir, "runner.sock")
        self.proc = subprocess.Popen(
            [path, sock_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        deadline = time.monotonic() + 30
        while not os.path.exists(sock_path):
            if self.proc.poll() is not None or time.monotonic() > deadline:
                raise SystemExit(f"eim runner failed to start ({self.proc.poll()})")
            time.sleep(0.05)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(sock_path)
        self._id = 0

    def send(self, msg: dict) -> dict:
        self._id += 1
        msg["id"] = self._id
        self._sock.sendall(json.dumps(msg).encode())
        data = b""
        while not data.endswith(b"\0"):
            chunk = self._sock.recv(65536)
            if not chunk:
                raise SystemExit("eim runner closed the socket")
            data += chunk
        resp = json.loads(data[:-1].decode().strip())
        if not resp.get("success"):
            raise SystemExit(f"eim error: {resp.get('error')}")
        return resp

    def cpu_seconds(self) -> float:
        with open(f"/proc/{self.proc.pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")

    def peak_rss_mb(self) -> float:
        with open(f"/proc/{self.proc.pid}/status") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) / 1024
        return 0.0

    def close(self) -> None:
        self._sock.close()
        self.proc.terminate()
        self.proc.wait(timeout=5)


def bench_eim(args: argparse.Namespace, clips: list[str]) -> None:
    runner = EimRunner(args.eim)
    try:
        params = runner.send({"hello": 1})["model_parameters"]
        rate, window = params["frequency"], params["input_features_count"]
        # The SDK's audio runner advances by a quarter window per call.
        step = window // 4
        print(
            f"eim model: {rate} Hz, window {window} samples ({window / rate:.2f}s), "
            f"step {step / rate * 1000:.0f}ms, labels {params['labels']}"
        )
        warm = runner.send({"classify": [0] * window})
        print(f"eim timing fields (ms): {warm.get('timing')}")
        ms: list[float] = []
        dsp_ms: list[float] = []
        cpu0, client0 = runner.cpu_seconds(), time.process_time()
        audio = 0.0
        for _ in range(args.repeat):
            for path in clips:
                # --eim-via-16k reproduces the robot's 16 kHz microphone
                # path: no content above 8 kHz reaches the model.
                if args.eim_via_16k:
                    clip = resample(load(path), SR, rate)
                else:
                    clip = load(path, rate)
                # Pad so even a short phrase fills at least one window.
                pad = np.zeros(
                    max(rate // 2, (window - len(clip)) // 2 + 1), dtype=np.int16
                )
                samples = np.concatenate([pad, clip, pad])
                best: dict[str, float] = {}
                for start in range(0, len(samples) - window + 1, step):
                    t0 = time.perf_counter()
                    resp = runner.send(
                        {"classify": samples[start : start + window].tolist()}
                    )
                    ms.append(1000 * (time.perf_counter() - t0))
                    timing = resp.get("timing", {})
                    dsp_ms.append(
                        timing.get("dsp", 0) + timing.get("classification", 0)
                    )
                    for label, score in resp["result"]["classification"].items():
                        best[label] = max(best.get(label, 0.0), score)
                audio += len(samples) / rate
                if _ == 0:
                    ranked = ", ".join(f"{k} {v:.3f}" for k, v in sorted(best.items()))
                    print(f"  {os.path.basename(path)}: max {ranked}")
        runner_cpu = runner.cpu_seconds() - cpu0
        client_cpu = time.process_time() - client0
        summary("eim (runner process)", ms, runner_cpu, audio)
        print(
            f"eim runner-reported dsp+classify p50={statistics.median(dsp_ms):.2f}ms; "
            f"client JSON/resample cpu {client_cpu:.2f}s; runner peak RSS {runner.peak_rss_mb():.0f} MB"
        )
    finally:
        runner.close()


class MicStream:
    """Record-only GStreamer pipeline on the shared dsnoop device, as 16 kHz
    mono int16. No playback element, so it cannot make a sound."""

    def __init__(self) -> None:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        Gst.init([])
        self._pipeline = Gst.parse_launch(
            "alsasrc device=reachymini_audio_src ! audioconvert ! audioresample ! "
            f"audio/x-raw,format=S16LE,rate={SR},channels=1 ! "
            "appsink name=sink max-buffers=200 drop=true"
        )
        self._sink = self._pipeline.get_by_name("sink")
        self._pipeline.set_state(Gst.State.PLAYING)
        self._Gst = Gst

    def read(self) -> np.ndarray | None:
        sample = self._sink.emit("try-pull-sample", 200 * self._Gst.MSECOND)
        if sample is None:
            return None
        buf = sample.get_buffer()
        ok, info = buf.map(self._Gst.MapFlags.READ)
        if not ok:
            return None
        try:
            return np.frombuffer(bytes(info.data), dtype=np.int16)
        finally:
            buf.unmap(info)

    def close(self) -> None:
        self._pipeline.set_state(self._Gst.State.NULL)


def listen(args: argparse.Namespace) -> None:
    import signal

    import onnxruntime as ort
    from openwakeword.model import Model

    stop = False

    def on_signal(*_: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    # Idle ORT worker threads otherwise busy-wait between the small
    # real-time calls, which costs about a core on the Nano. openWakeWord
    # builds its own sessions, so patch the options class it uses.
    base_options = ort.SessionOptions

    def quiet_options() -> ort.SessionOptions:
        opts = base_options()
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        opts.add_session_config_entry("session.inter_op.allow_spinning", "0")
        return opts

    ort.SessionOptions = quiet_options  # type: ignore[misc]

    oww = Model(
        wakeword_models=[os.path.join(args.models, f"{args.wake}.onnx")],
        inference_framework="onnx",
        melspec_model_path=os.path.join(args.models, "melspectrogram.onnx"),
        embedding_model_path=os.path.join(args.models, "embedding_model.onnx"),
        ncpu=1,
    )
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    yamnet = ort.InferenceSession(os.path.join(args.models, "yamnet.onnx"), options)
    yamnet_input = yamnet.get_inputs()[0].name
    with open(os.path.join(args.models, "labels.txt")) as f:
        labels = [line.strip() for line in f]
    runner = EimRunner(args.eim) if args.eim else None
    eim_rate = eim_window16 = 0
    if runner:
        params = runner.send({"hello": 1})["model_parameters"]
        eim_rate = params["frequency"]
        eim_window16 = params["input_features_count"] * SR // eim_rate
        print(
            f"eim: {eim_rate} Hz, {eim_window16 / SR:.1f}s window, labels {params['labels']}"
        )
    mic = MicStream()
    print(
        f"listening; thresholds eim>={args.threshold} {args.wake}>={args.threshold}; "
        "Ctrl-C or docker stop ends. No audio is stored.",
        flush=True,
    )

    history = np.zeros(max(eim_window16, 15600), dtype=np.int16)
    pending = np.zeros(0, dtype=np.int16)
    since_tick = 0
    tick = SR // 2  # the Edge Impulse SDK's quarter-window step for a 2 s window
    started = time.monotonic()
    events: dict[str, list[tuple[float, float]]] = {"eim": [], "oww": []}
    open_event: dict[str, tuple[float, float] | None] = {"eim": None, "oww": None}
    period = {"eim": 0.0, "oww": 0.0, "peak_db": -120.0}
    last_status = started
    cpu0 = time.process_time()
    runner_cpu0 = runner.cpu_seconds() if runner else 0.0

    def note(name: str, score: float, now: float) -> None:
        # One event per burst: scores above threshold within 1.5 s merge.
        current = open_event[name]
        if score >= args.threshold:
            if current and now - current[0] < 1.5:
                open_event[name] = (current[0], max(current[1], score))
            else:
                if current:
                    events[name].append(current)
                open_event[name] = (now, score)
                clock = time.strftime("%H:%M:%S")
                print(f"{clock} +{now:7.1f}s DETECT {name} {score:.3f}", flush=True)

    try:
        while not stop:
            chunk = mic.read()
            if chunk is None:
                continue
            now = time.monotonic() - started
            history = np.concatenate([history, chunk])[-len(history) :]
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) + 1e-9
            period["peak_db"] = max(period["peak_db"], 20 * np.log10(rms / 32768))
            pending = np.concatenate([pending, chunk])
            while len(pending) >= CHUNK:
                scores = oww.predict(pending[:CHUNK])
                pending = pending[CHUNK:]
                score = max(scores.values())
                period["oww"] = max(period["oww"], score)
                note("oww", score, now)
            since_tick += len(chunk)
            if since_tick >= tick:
                since_tick = 0
                if runner:
                    window = resample(history[-eim_window16:], SR, eim_rate)
                    result = runner.send({"classify": window.tolist()})["result"]
                    score = result["classification"].get("hey_reachy", 0.0)
                    period["eim"] = max(period["eim"], score)
                    note("eim", score, now)
                recent = history[-15600:]
                level = 20 * np.log10(
                    float(np.sqrt(np.mean(recent.astype(np.float32) ** 2))) / 32768
                    + 1e-9
                )
                if level > args.event_db:
                    (scores,) = yamnet.run(
                        None, {yamnet_input: log_mel(recent)[None, None, :96]}
                    )
                    top = [
                        i for i in np.argsort(scores[0])[::-1] if labels[i] != "Silence"
                    ][:2]
                    ranked = ", ".join(f"{labels[i]} {scores[0][i]:.1f}" for i in top)
                    print(
                        f"{time.strftime('%H:%M:%S')} +{now:7.1f}s sound {level:.0f} dBFS: {ranked}",
                        flush=True,
                    )
            if time.monotonic() - last_status >= 10:
                last_status = time.monotonic()
                print(
                    f"{time.strftime('%H:%M:%S')} +{now:7.1f}s status: peak {period['peak_db']:.0f} dBFS, "
                    f"max eim {period['eim']:.3f}, max {args.wake} {period['oww']:.3f}",
                    flush=True,
                )
                period = {"eim": 0.0, "oww": 0.0, "peak_db": -120.0}
    finally:
        mic.close()
        elapsed = time.monotonic() - started
        for name, found in events.items():
            last = open_event[name]
            if last:
                found.append(last)
        print(
            f"listened {elapsed:.0f}s; client cpu {100 * (time.process_time() - cpu0) / elapsed:.1f}% of one core"
        )
        if runner:
            used = runner.cpu_seconds() - runner_cpu0
            print(f"eim runner cpu {100 * used / elapsed:.1f}% of one core")
            runner.close()
        for name, found in events.items():
            listed = ", ".join(f"+{t:.1f}s {s:.2f}" for t, s in found)
            print(f"{name} events: {len(found)} [{listed}]", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", required=True)
    parser.add_argument("--clips")
    parser.add_argument(
        "--listen", action="store_true", help="score the live robot microphone"
    )
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument(
        "--event-db",
        type=float,
        default=-40.0,
        help="label sounds louder than this in --listen",
    )
    parser.add_argument("--wake", default="hey_jarvis_v0.1")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--event-threads", type=int, default=1)
    parser.add_argument("--eim", help="Edge Impulse .eim keyword model to run")
    parser.add_argument("--eim-via-16k", action="store_true")
    parser.add_argument("--only", choices=["wake", "event", "eim"])
    args = parser.parse_args()
    if args.listen:
        listen(args)
        return
    clips = sorted(glob.glob(os.path.join(args.clips or "", "*.wav")))
    if not clips:
        raise SystemExit("no clips")
    print(
        f"baseline peak RSS {rss_mb():.0f} MB, {os.cpu_count()} cpus, {len(clips)} clips"
    )
    if args.only in (None, "wake"):
        bench_wake(args, clips)
    if args.only in (None, "event"):
        bench_event(args, clips)
    if args.eim and args.only in (None, "eim"):
        bench_eim(args, clips)
    print(f"final peak RSS {rss_mb():.0f} MB")


if __name__ == "__main__":
    main()
