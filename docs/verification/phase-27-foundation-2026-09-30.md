# Phase 27.1 foundation — 2026-09-30

Dated evidence for [docs/phase-27.md](../phase-27.md)'s 27.1 Foundation
implementation sequence entry. Not a startup instruction or current health
check.

## What ran

- `.venv/bin/ruff check .` — clean across the repo after the change.
- `pytest services/companion-core/tests -q -m 'not slow'` — 444 passed,
  19 skipped, 2 deselected. Includes the new
  `services/companion-core/tests/test_meetings.py` (14 cases): in-memory
  `MeetingStore` CRUD and state transitions, `MeetingWorker` real WAV
  duration probing via the stdlib `wave` module, orphaned-job requeue on
  worker startup, and the full upload → list → get → cancel HTTP surface
  through a real in-process FastAPI chain (`httpx`/`TestClient`, no mocks
  of companion-core's own routes).
- `pytest services/reachy-hub/tests -q -m 'not slow'` — 340 passed, 3
  skipped, 9 deselected. Includes
  `test_operator.py::test_meetings_proxy_upload_list_get_cancel_require_auth`,
  which chains a real in-process reachy-hub app to a real in-process
  companion-core app over `httpx.ASGITransport` and exercises the owner
  auth requirement (401 unauthenticated), CSRF, upload, list, get, 404 on
  an unknown meeting, cancel, and 409 on a second cancel.
- `node --check app.js` and `node --check meetings.js` for the new
  operator-ui Meetings tab.
- `docker compose config` on `deploy/homelab/docker-compose.yml` parsed
  the new `MEETING_AUDIO_DIR` environment/volume wiring without a YAML
  error (it stopped on an unrelated, pre-existing missing
  `SEARXNG_SECRET_KEY`, the same requirement every homelab bring-up has).

## What did not run

- No real Postgres — `PostgresMeetingStore` (filesystem audio + SQL) was
  not exercised against a live database, only `InMemoryMeetingStore`
  through the app's dependency-injection seam. The migration
  (`010_meetings`) was not applied to a real database either.
- No live homelab Compose stack — the `meeting-audio` volume mount and
  `MEETING_AUDIO_DIR` default were checked for YAML validity only, not a
  running container.
- No real browser — the operator-ui Meetings tab (upload form, list,
  cancel) was not opened in Chromium/Playwright; this session had neither
  available. `node --check` only proves the files parse as valid
  JavaScript.
- No real meeting recording, and no STT/diarization/analysis — 27.2
  onward are unimplemented by design at this point in the sequence (see
  phase-27.md's Status section); nothing here claims otherwise.

## Next verification owed

Before treating 27.1 as done rather than implemented-but-unverified: run
the real migration against a live Postgres, upload a real recording
through the browser on a deployed homelab stack, and confirm the meeting
row/audio file survive a `docker compose restart companion-core`.

## Addendum: 27.3 diarization service deployment — 2026-09-30

The owner pointed at `~/inferencing/diarization` (their own prior local
experimentation, previously tested standalone outside this repo) and
asked for it in reachy's deployment. Ported into
`deploy/homelab/diarization/` (Dockerfile + `app/`, excluding the
~570 MB of downloaded model weights/exported ONNX, which regenerate into
the new `diarization-data` volume on first start) as a new `diarization`
Compose profile.

**What ran:** `scripts/start-homelab.sh --check --diarization` against
this dev box's real `deploy/homelab/.env` — real `docker compose config`
validated the new service block, profile wiring, and env var
interpolation; passed. This box does have `/dev/dri` (confirmed with
`ls /dev/dri`), so the launcher's missing-device warning path was not
exercised here. `scripts/start-homelab.sh --check` (no `--diarization`)
was also re-run to confirm the default path is unchanged. `bash -n` on
the launcher; no `shellcheck` available in this environment.

**What did not run:** the image was never built (`docker compose build
diarization` / `--diarization --build`), so the NeMo/OpenVINO install,
model download, ONNX export and `/health` reaching `"status": "ready"`
are all unverified — only the compose wiring around it is. No real audio
was sent to `POST /diarize`. No code in this repo calls this service yet.

## Addendum: 27.2/27.3 worker wiring, transcription sidecar, and Meetings
## frontend (record + detail view) — 2026-09-30

Per [ADR 0025](../adr/0025-speech-inference-service.md)'s decision and the
owner's follow-up requests: implemented the `TranscriptionClient`/
`DiarizationClient` seam (`companion_core/meetings/speech_clients.py`),
wired `MeetingWorker`'s TRANSCRIBING/DIARIZING stages to it, added
`deploy/homelab/transcription/` (a faster-whisper long-form sidecar, same
shape as the diarization one, `--transcription` profile), and built out
the operator-ui Meetings tab: browser recording (`MediaRecorder`,
uploading through the same `POST /meetings` as a file) and a meeting
detail view (raw transcript/diarization segments, since 27.4 alignment
and 27.6 analysis don't exist — no fabricated "minutes"). Also found and
fixed a real race during this work: `mark_transcribed`/`mark_diarized`/
`mark_preprocessed` previously applied unconditionally, so an owner
cancel landing while a stage was in flight could be silently overwritten
by that stage's later completion; they now guard on the expected prior
status (both `InMemoryMeetingStore` and `PostgresMeetingStore`) and are a
no-op otherwise.

**What ran:**
- `pytest services/companion-core/tests -q -m 'not slow'` — 455 passed
  (up from 444), 19 skipped, 2 deselected. `test_meetings.py` grew to 25
  cases: `HTTPTranscriptionClient`/`HTTPDiarizationClient`-shaped fakes
  driving `MeetingWorker` through TRANSCRIBING→DIARIZING→ALIGNING,
  `SpeechServiceUnavailable` leaving a job untouched for retry vs.
  `SpeechServiceRejected` failing it permanently, one stuck stage not
  starving another ready to progress, and the cancel-race no-op guard.
- `pytest services/reachy-hub/tests -q -m 'not slow'` — 340 passed
  (unchanged; no hub-side change this addendum), 3 skipped, 9 deselected.
- `.venv/bin/ruff check .` — clean, including the new
  `deploy/homelab/transcription/app/server.py`.
- `node --check meetings.js` and `app.js` for the recording/detail-view
  frontend changes.
- `scripts/start-homelab.sh --check --transcription --diarization` (and
  `--check` alone, and `--check --diarization` alone) against this dev
  box's real `.env` — all valid, read-only.

**What did not run:** neither sidecar was built or started, so no real
`/health`, no real `POST /transcribe`/`POST /diarize` call, and no real
30–60 minute meeting has gone through the pipeline — the 27.2/27.3 exit
criteria remain open (see phase-27.md). The new Meetings frontend
(recording, detail view) was not opened in a real browser — no
Playwright/Chromium available this session; `node --check` only proves
the files parse as valid JavaScript, not that `getUserMedia`/
`MediaRecorder` actually work as written, that the detail panel renders
correctly, or that a real recorded clip uploads and decodes successfully
server-side.

## Next verification owed (supersedes the single item above)

1. Build and start both sidecars for real
   (`--transcription --diarization --build`); confirm `/health` on each
   reaches `"status": "ready"`.
2. Upload a real recording through the operator-ui Meetings tab in an
   actual browser; separately, record a clip through the browser's
   microphone and confirm it uploads and the same job progresses through
   PREPROCESSING → TRANSCRIBING → DIARIZING → ALIGNING with real
   `transcript_segments`/`diarization_segments` visible in the detail
   view.
3. Run `010_meetings`/`011_meeting_speech_results` against a real
   Postgres and confirm a meeting's row/audio file survive
   `docker compose restart companion-core`.

## Addendum: real live deployment and end-to-end pipeline run — 2026-09-30

Item 1 above (build/start for real) and item 3 (real Postgres) are now
done, on the owner's actual running homelab (`reachy-homelab` Compose
project), not a disposable test stack — this is the first Phase 27 pass
with real evidence rather than mocks/fakes.

**Two real bugs found and fixed by this live run** (neither was, or
plausibly could have been, caught by the existing test suite, since it
never sends real audio through a real faster-whisper/PyAV decode or
starts the real companion-core container):

1. **`python-multipart` was missing from `services/companion-core/
   pyproject.toml`.** companion-core's new `/meetings` route uses
   `Form()`/`File()`, which FastAPI requires it for; the package was only
   ever present because the shared dev venv installs every workspace
   member together and reachy-hub already depends on it — exactly the
   "workspace dependencies can mask a missing direct runtime dependency"
   trap `docs/development.md`'s testing conventions already warn about.
   The real container crash-looped with `RuntimeError: Form data
   requires "python-multipart" to be installed` until this was added and
   `uv.lock` regenerated.
2. **PyAV 19 (the unpinned latest, since faster-whisper 1.2.1 only
   declares `av>=11`) removed `av.open()`'s `metadata_errors` kwarg**,
   which faster-whisper's `decode_audio()` still passes — every real
   `/transcribe` call failed with `open() got an unexpected keyword
   argument 'metadata_errors'` (correctly surfaced to the meeting as a
   permanent `SpeechServiceRejected` failure, not a silent hang — the
   error-handling design worked as intended even while finding this).
   Fixed by pinning `av==14.0.1` (confirmed compatible, live, before
   changing the Dockerfile) in `deploy/homelab/transcription/Dockerfile`.

**What ran, for real:**
- `docker compose -p reachy-homelab --env-file deploy/homelab/.env
  pg_dump` — a fresh backup
  (`~/reachy-backups/reachy-before-phase27-speech-deploy-*.dump`) before
  touching schema, per the documented cutover procedure.
- `scripts/start-homelab.sh --transcription --build` — built and started
  the transcription sidecar for the first time ever, rebuilt and
  recreated `companion-core`/`reachy-hub` with all of today's code, and
  ran the real migration job: `alembic_version` moved from `009_wake_arm`
  (the prior live revision) straight to `011_meeting_speech_results` on
  the real database, no `--adopt-legacy` needed (both are ordinary
  forward migrations).
- The diarization sidecar was **not** rebuilt/restarted — the owner's
  existing standalone `diarization` container (from their own prior
  `~/inferencing/diarization` work, already healthy for 29+ hours, using
  the real Intel iGPU) was reused instead of starting a competing second
  instance. `docker network connect reachy-homelab_default diarization`
  gave it the `diarization` hostname alias companion-core's default
  `DIARIZATION_URL` already expects, so no code or env override was
  needed — reversible with `docker network disconnect`.
- Confirmed both `GET /health` reach `"status": "ready"` from inside the
  `companion-core` container (`transcription`: faster-whisper small.en on
  CPU; `diarization`: Nemotron-3/OpenVINO on the real Intel Iris Xe iGPU).
- Uploaded a real 3-second silent WAV through the real hub proxy
  (`POST /hub/meetings`, bearer auth) — reached UPLOADED → PREPROCESSING →
  TRANSCRIBING → DIARIZING → ALIGNING in about 3.5 seconds wall time, with
  empty `transcript_segments`/`diarization_segments` (correct: no speech,
  no speakers).
- Generated a real 5.3-second speech clip with `espeak-ng` ("We should
  move the migration to next week. I will contact the vendor about
  compatibility.") and uploaded it the same way. Real faster-whisper
  transcript came back matching the spoken text almost exactly, correctly
  segmented into two sentences with real timestamps; real diarization
  came back with one consistent `speaker_0` across both segments (a
  single-voice `espeak-ng` clip, so this doesn't exercise multi-speaker
  separation — see "still open" below). Total pipeline time: about 2
  seconds for the 5.3-second clip.
- Exercised `POST /meetings/{id}/cancel` for real: 200 with
  `status: "cancelled"`, then 409 on a second call.
- Confirmed the rebuilt `reachy-hub` is serving the new Meetings UI
  (`curl .../hub/ui/meetings.js` contains `MediaRecorder`;
  `.../hub/ui/` contains the `meeting-record-start` button).
- Checked `GET /hub/status`: hub, companion-core, LLM (real usage
  history) all `ok`; robot `nano-1` reachable-but-`unavailable` (expected
  — no physical robot connected right now, unrelated to this work) and
  container logs for `reachy-hub`/`companion-core` clean, no new errors.
  Local `pytest`/`ruff` re-run after the dependency fix — still 796
  passed, clean.

**What is still open:**
- Only a synthetic single-speaker `espeak-ng` clip was tested, not a real
  30–60 minute multi-speaker meeting — the 27.2/27.3 exit criteria's
  "real 30–60 minute recording" and measured RTF/CPU/RAM at that duration
  remain unverified. `espeak-ng` also doesn't exercise real-world
  acoustic difficulty (noise, overlap, accents).
- Browser recording (`MediaRecorder`) and the detail view were exercised
  through curl/the raw API, not an actual browser — still no
  Playwright/Chromium available this session.
- `SPEECH_SERVICE_TOKEN` (the service-to-service auth ADR 0025 calls
  for) was implemented in code this session but deliberately left unset
  in this deployment: turning it on requires also rebuilding and
  restarting the owner's existing diarization container, which was
  intentionally left untouched given it was already healthy and serving
  real results. Doing that, and deciding whether to keep the standalone
  container or replace it with a `reachy-homelab`-managed one, is an
  owner decision, not made unilaterally here.
- The homelab now has four leftover test meetings ("Test meeting ...",
  "Speech test ...", "Cancel test") in the real database/audio volume —
  there is no delete endpoint, only cancel, so these remain visible in
  the Meetings list until the owner decides whether/how to remove them.

