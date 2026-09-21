# reachy-hub

Runs in the homelab. Owns: sessions, Telegram, WebRTC, web UI, response routing,
authentication.

Must not own: reasoning policy internals, raw motor control (see [docs/adr/0001](../../docs/adr/0001-service-boundaries.md)).

Not yet implemented — scaffolding only (Phase 0). Implementation starts in Phase 4
(minimal control plane) and Phase 5 (AgentSession).
