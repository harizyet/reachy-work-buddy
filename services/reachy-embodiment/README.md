# reachy-embodiment

Runs on Reachy-side hardware. Owns: semantic behaviours, presence, gaze, local
fallback, safety/watchdog.

Must not own: email/calendar/RAG, long-term work memory (see [docs/adr/0001](../../docs/adr/0001-service-boundaries.md)).

Exposes the HTTP API defined in [shared/protocols/embodiment_api.py](../../shared/protocols/embodiment_api.py)
and [docs/adr/0003](../../docs/adr/0003-embodiment-command-api.md). Must remain
functional when companion-core/reachy-hub are unreachable — see
[docs/adr/0004](../../docs/adr/0004-offline-fallback.md).

Not yet implemented — scaffolding only (Phase 0). Implementation starts in Phase 2.
