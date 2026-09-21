# ADR 0002: Cross-Channel AgentSession

- Status: Accepted
- Date: 2026-09-21

## Context

Reachy voice, Telegram, a WebRTC phone call, and the web/PWA client must all
address the same conversation. A user starting a conversation at their desk
and continuing it on Telegram must not lose context or trigger a second
assistant instance.

## Decision

`reachy-hub` owns a single `AgentSession` per user (see
`shared/models/session.py`). Every inbound message from every channel is
normalized to a `(session_id, channel, payload)` tuple before being handed to
`companion-core`. `companion-core` is channel-agnostic: it only ever sees a
`session_id` and conversation history, never "this came from Telegram".

Channel switching updates `AgentSession.active_channel` but never creates a
new `conversation_id`. `interaction_mode` (Desk/Office/Silent/Remote) is
tracked on the session and drives the response router (ADR 0004... see
`0006-response-routing.md`), not the LLM prompt.

## Consequences

- Session state (active channel, interaction mode, privacy context) lives in
  `reachy-hub`'s datastore (Postgres), not in `companion-core`.
- `companion-core` must not persist channel-specific formatting (e.g.
  Telegram markdown) — that is a `reachy-hub` responsibility applied at
  output time.
- Two clients open on the same session (e.g. web + phone) both observe state
  changes; `reachy-hub` is responsible for fan-out, not `companion-core`.
