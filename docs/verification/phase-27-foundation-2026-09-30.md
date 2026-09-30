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

