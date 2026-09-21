# ADR 0001: Service Boundaries

- Status: Accepted
- Date: 2026-09-21

## Context

The system spans reasoning (LLM/tools/memory), transport (Telegram/WebRTC/web),
embodiment (robot behaviour/presence), and hardware control (Reachy daemon).
Jarvis (the reference project) couples these into one process. We need
independently deployable, independently failable services so that Reachy
remains expressive when the homelab is offline, and so reasoning logic never
has direct access to motor control.

## Decision

Four services, each with a single owner and explicit non-owned concerns:

| Service | Runs on | Owns | Must not own |
|---|---|---|---|
| `companion-core` | Homelab | Reasoning, tools, work memory, RAG, calendar/email/tasks, proactive workflows | Direct robot joints, UI transport |
| `reachy-hub` | Homelab | Sessions, Telegram, WebRTC, web UI, routing, authentication | Reasoning policy internals, raw motor control |
| `reachy-embodiment` | Reachy-side | Semantic behaviours, presence, gaze, local fallback, safety | Email/calendar/RAG, long-term work memory |
| Reachy daemon | Reachy | Hardware, media, low-level state/control | Work-agent cognition |

Core separation rules (see also `0002-agent-session.md`, `0003-embodiment-command-api.md`):

- Cognition ≠ embodiment
- Embodiment ≠ transport
- Transport ≠ session
- Session ≠ memory
- Memory ≠ RAG
- LLM suggestion ≠ permission

## Consequences

- `companion-core` and `reachy-embodiment` communicate only through the
  `EmbodimentCommand` API (ADR 0003) over HTTP; no shared process memory.
- `reachy-hub` is the only service with transport-specific code (Telegram
  bot, WebRTC signaling, web/PWA API). Adding a channel never touches
  `companion-core`.
- `reachy-embodiment` must function with `companion-core` and `reachy-hub`
  unreachable (local idle/fallback personality), per ADR 0004.
- Any Jarvis code reused into these services must be adapted to respect this
  boundary — e.g. Jarvis's `robot/controller.py` couples directly to the
  conversation loop and is not reused as-is (see `../jarvis-baseline.md`,
  which captures the Jarvis reuse decisions in place of a separate ADR).
