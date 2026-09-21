# reachy-embodiment

Runs on Reachy-side hardware. Owns: semantic behaviours, presence, gaze, local
fallback, safety/watchdog.

Must not own: email/calendar/RAG, long-term work memory (see [docs/adr/0001](../../docs/adr/0001-service-boundaries.md)).

## Status (Phase 2)

Implements the `GET /health`, `GET /state`, `GET /behaviours`,
`POST /behaviour/{name}` slice of the API defined in
[shared/protocols/embodiment_api.py](../../shared/protocols/embodiment_api.py)
and [docs/adr/0003](../../docs/adr/0003-embodiment-command-api.md), against a
`SimulatedRobotBackend` (no hardware required — see
[robot.py](src/reachy_embodiment/robot.py)). `/gaze`, `/pose`, and
`/audio/play` are part of the ADR 0003 contract but not implemented yet —
they land with the presence loop (Phase 3) and audio pipeline (Phase 8),
where they'll have real behaviour behind them.

A real `RobotBackend` wrapping the `reachy_mini` SDK (the way Jarvis's
`RobotController` does — see [docs/jarvis-baseline.md](../../docs/jarvis-baseline.md))
plugs in behind the same `RobotBackend` protocol once hardware is available to
test against; nothing above `robot.py` needs to change.

Presence loop, idle/fallback state machine, and safety/watchdog (Phase 3) are
not implemented yet.

## Run it

```
uv sync --all-packages
uv run uvicorn reachy_embodiment.app:app --app-dir services/reachy-embodiment/src --reload
```

```
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/behaviours
curl -X POST http://127.0.0.1:8000/behaviour/greeting
curl http://127.0.0.1:8000/state
```

## Test

```
uv run --group dev pytest services/reachy-embodiment/tests
```
