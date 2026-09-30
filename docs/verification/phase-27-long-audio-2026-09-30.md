# Phase 27 long-audio transport verification — 2026-09-30

Scope: remove avoidable long-recording transport pressure and short inference
waits. This is not Phase 27 meeting-quality acceptance or a live-stack rollout.
See [operations](../deployment.md#long-meeting-recordings) for settings and
remaining runtime limits.

## Findings and changes

There was no one-hour recording-duration cap. Core's speech clients used a
fixed 1,800-second response timeout, so slow inference could time out and
retry despite the model still working. Hub, Core and both sidecars read whole
encoded recordings into memory. Sidecar requests waited behind a model lock,
allowing abandoned/timed-out requests to queue for later inference.

- Hub forwards the multipart parser's spooled file to Core; Core copies it
  to its durable audio directory in 1 MiB blocks.
- The worker opens/closes a seekable file for each stage/attempt, including
  WAV duration probing, instead of loading the full recording as bytes.
- Core's inference response wait is configurable with
  `MEETING_INFERENCE_TIMEOUT_SECONDS`, default 21,600 seconds. Connection
  and pool waits remain short. Hub's upload timeout is 600 seconds.
- Sidecars acquire model admission without waiting, return retryable 503
  when busy, and decode from the spooled file. Diarization releases its
  normalized waveform before NeMo loads that file again.

No schema, inference model, speaker-clustering policy or service ownership
changed. Raw speech results still stop at ALIGNING.

## Automated evidence

- `uv run --group dev pytest services/companion-core/tests services/reachy-hub/tests -m 'not slow' -q`:
  **800 passed, 22 skipped, 11 deselected** at the full-suite checkpoint.
  Skipped/slow checks are not evidence for real Postgres or physical systems.
- `services/companion-core/tests/test_long_meetings.py`: **6 passed** after
  adding the final retry cases. A real sparse 65-minute, 16 kHz PCM WAV is
  read through a reader that rejects unbounded or >1 MiB reads. Actual HTTPX
  multipart streaming sends it to an injected streaming transport for both
  inference stages, preserves timestamps beyond one hour, closes files, and
  reaches ALIGNING. Inference responses in this test are simulated.
  The disk-copy test uses the real Postgres store's file-writing path with a
  fake database connection; it is not real database acceptance.
- Timeout configuration rejects nonpositive/nonfinite values; overrides work.
  Timeout/connect-error retries reopen audio and retain successful STT output.
- `services/reachy-hub/tests/test_operator.py`: **16 passed** after strengthening
  the real Hub/Core ASGI upload chain to reject unbounded `UploadFile.read()`.
  Existing authentication, cancellation and status assertions still pass.
- `deploy/homelab/tests/test_speech_uploads.py`: **4 passed in each actual
  sidecar dependency image**. Real decoding plus fake inference checks busy
  admission, file-backed input and lock release on success/decode/model error.
  Run inside a speech image with updated `/app/server.py`, mounting the test
  directory at `/tests`: `python /tests/test_speech_uploads.py`.
- Ruff passed for `services`, `shared`, the changed speech servers and the
  new sidecar tests. No new dependencies were added.
- `scripts/start-homelab.sh --check --transcription --diarization` passed
  Compose validation without starting anything. Direct Compose validation
  lacked the launcher-provided SearXNG secret, so validation used the
  supported launcher. Changed Markdown links/anchors and `git diff --check`
  passed.

## Isolated real-model HTTP checks

Used a separate named Compose project, `reachy-long-meeting-check`, with
existing dependency images (`reachy-transcription:latest` and
`nemotron-diarization-ov:latest`). Mounted this checkout's updated sidecar
`app` directories read-only at `/app`. Reused model caches read-only with
`HF_HUB_OFFLINE=1`; no model download or production-cache mutation. The
transcription model was small.en/int8 on CPU; diarization used the existing
Nemotron/OpenVINO model on the Intel GPU.

Each disposable container started a real Uvicorn server, waited for `/health`,
then streamed multipart PCM WAV over localhost HTTP using bounded reads.
No running service was stopped or restarted. No meeting rows were created
in the owner's database. Existing production volumes were not deleted.

| Fixture (65 minutes / 3,900 seconds) | Endpoint | Model processing | RTF | Segments | Final segment end |
|---|---|---:|---:|---:|---:|
| 16 kHz silent PCM | `/transcribe` | 6.853 s | 0.0018 | 0 | — |
| 16 kHz silent PCM | `/diarize` | 28.389 s | 0.0073 | 0 | — |
| Synthetic speech at five-minute intervals | `/transcribe` | 36.800 s | 0.0094 | 26 | 3,604.02 s |
| Synthetic speech at five-minute intervals | `/diarize` | 28.952 s | 0.0074 | 26 | 3,604.14 s |

All four requests returned HTTP 200 and `duration_s: 3900`. The second fixture
used espeak-ng from an isolated Hub-image container to generate one generic
project-review phrase, inserted every 300 seconds into 65 minutes of mono
22,050 Hz PCM. This confirms real speech is preserved beyond one hour;
large silent gaps mean these RTFs are **not estimates for continuous meetings**.
No private recording was used and no transcript was logged in this record.

The existing live services remained running. A sampled test diarization
container memory reading was about 1.18 GiB during startup; this is not a
measured inference peak. CPU/iGPU utilization and LLM latency coexistence
were not benchmarked.

## Remaining limits

- Live Core/Hub/sidecar rollout remains outstanding. The repo diarization
  Dockerfile was not rebuilt: tests used its updated wrapper with the owner's
  existing dependency image. No new full-image build claim is made.
- No representative >1-hour multi-speaker human recording was supplied.
  Continuous speech, overlap, accents, peak memory and sustained LLM
  coexistence still need acceptance. Browser hour-long capture was not run.
- The new timeout policy was configuration-tested, not exercised by waiting
  six hours. A failed connection can still cause inference recomputation;
  durable compute-job handles remain future work.
- Transport buffering is reduced; full-waveform/features allocation inside
  inference libraries still scales with audio duration. Uploaded audio also
  needs temporary disk space at each multipart hop.
- Authentication activation, explicit real database/audio restart survival,
  alignment and meeting analysis remain separate open work.
