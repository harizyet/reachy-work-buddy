# reachy-embodiment

Runs on Reachy-side hardware. Owns: semantic behaviours, presence, gaze, local
fallback, safety/watchdog.

Must not own: email/calendar/RAG, long-term work memory (see [docs/adr/0001](../../docs/adr/0001-service-boundaries.md)).

## Status (Phase 8)

Implements the `GET /health`, `GET /state`, `GET /behaviours`,
`POST /behaviour/{name}`, `POST /heartbeat` slice of the API defined in
[shared/protocols/embodiment_api.py](../../shared/protocols/embodiment_api.py),
[docs/adr/0003](../../docs/adr/0003-embodiment-command-api.md), and
[docs/adr/0004](../../docs/adr/0004-offline-fallback.md), against a
`SimulatedRobotBackend` (no hardware required — see
[robot.py](src/reachy_embodiment/robot.py)). `/gaze`, `/pose`, and
`/audio/play` are part of the ADR 0003 contract but not implemented yet —
they land with real hardware.

**Speech (Phase 8)**: [audio/vad.py](src/reachy_embodiment/audio/vad.py) is
a real Silero VAD wrapper adapted from the Jarvis baseline (fixed 512-sample
chunks at 16kHz — a Silero model requirement, not a choice). It's not wired
into a live audio stream: there's no physical Reachy microphone in this
project's dev/test environment, and the presence loop doesn't have a
`vad_energy` signal input surface yet either. It's implemented and tested
against real synthesized speech now (see `tests/test_vad.py`) so that
wiring, whenever real hardware/streaming exists, is plumbing, not new
detection logic — same treatment as `/gaze`/`/pose`/`/audio/play` above.
STT and TTS live in `reachy-hub`, not here — see
[docs/plan.md §8](../../docs/plan.md) ("STT | Homelab initially") and
`services/reachy-hub/README.md`.

A real `RobotBackend` wrapping the `reachy_mini` SDK (the way Jarvis's
`RobotController` does — see [docs/jarvis-baseline.md](../../docs/jarvis-baseline.md))
plugs in behind the same `RobotBackend` protocol once hardware is available to
test against; nothing above `robot.py` needs to change.

`presence.py` runs a `PresenceLoop` on its own background thread
(started/stopped via the FastAPI app's lifespan), independent of
companion-core/reachy-hub:

- **Idle animation**: while the standing state is `IDLE` or `DISCONNECTED`,
  it cycles through `idle_breathing` / `subtle_scan` / `antenna_twitch` on
  its own, so the robot is never fully static.
- **Watchdog**: any `POST /behaviour/{name}` or explicit `POST /heartbeat`
  counts as proof the homelab is reachable. If none arrives within the
  timeout, state flips to `DISCONNECTED` — animation continues regardless.
  The next heartbeat flips it straight back to `IDLE`.

Safety/watchdog for motion limits is not implemented yet — it lands with the
real `RobotBackend` (Jarvis's `HEAD_LIMITS` clamp is the reference for that).

## Run it

```
uv sync --all-packages
uv run uvicorn reachy_embodiment.app:app --app-dir services/reachy-embodiment/src --reload
```

```
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/behaviours
curl -X POST http://127.0.0.1:8000/behaviour/greeting
curl http://127.0.0.1:8000/state       # keep polling — last_behaviour advances on its own
curl -X POST http://127.0.0.1:8000/heartbeat
```

## Test

```
uv run --group dev pytest services/reachy-embodiment/tests
```

`tests/test_presence.py` unit-tests the `PresenceLoop` state machine
(including one real-background-thread test proving continuous animation
across a simulated disconnect). `tests/test_app_presence_loop.py` proves the
same thing through the actual FastAPI app with its lifespan running, the way
uvicorn would run it. `tests/test_vad.py` feeds real synthesized speech
(via `espeak-ng`, resampled to 16kHz) padded with real silence through the
real Silero VAD model and checks the detected speech boundaries — not tones
or noise, which wouldn't exercise what Silero is actually trained to
detect. Marked `@pytest.mark.slow` (loads a real model) and skips cleanly
without `espeak-ng` on `PATH`:

```
uv run --group dev pytest services/reachy-embodiment/tests -m "not slow"
uv run --group dev pytest services/reachy-embodiment/tests -m slow
```
