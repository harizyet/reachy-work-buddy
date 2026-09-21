# ADR 0006: Deterministic Response Routing

- Status: Accepted
- Date: 2026-09-22

## Context

Per docs/plan.md §4, "the LLM may propose metadata, but a deterministic
policy engine has final authority over output routing" — particularly for
workplace privacy (a calendar detail spoken aloud in an open office is a
real leak, not a cosmetic issue). ADR 0002 already commits to this
direction: `AgentSession.interaction_mode` "drives the response router...
not the LLM prompt." This ADR makes that router's ownership and scope
concrete.

Two independent things determine where a response goes, and they land in
different phases:

1. **Which channel the session is currently using and what mode the user
   has set** (Desk/Office/Silent/Remote) — knowable from `AgentSession`
   alone, with zero dependency on what companion-core said. This is Phase
   6's scope.
2. **What the response itself is** — its `privacy`, `urgency`,
   `requires_confirmation` (`AgentResponse`, `shared/models/response.py`) —
   which can override or refine the mode-driven default (e.g. a sensitive
   answer must never go to Reachy's speaker even in Desk mode if the room
   isn't actually private). This is Phase 9's scope ("Privacy/response
   router: implement response metadata, deterministic routing, audit
   events") and is **not** implemented yet.

## Decision

`reachy-hub` owns response routing (ADR 0001: "routing" is explicitly
reachy-hub's, not companion-core's). `response_policy.py` implements a pure,
deterministic function of `(interaction_mode, active_channel) -> Channel`:

| Mode | Resolved channel |
|---|---|
| Desk | Reachy (private room; speaker output is fine) |
| Office | Phone (docs §4: "phone preferred" output in Office mode) |
| Silent | Whatever text-capable channel is already active; falls back to the web client if the active channel is Reachy (which has no silent/text-only output path) |
| Remote | Phone |

This function takes no `AgentResponse` content as input — this is the
literal meaning of Phase 6's exit criterion, "mode changes output routing
without prompt changes": swapping `interaction_mode` on an otherwise
identical turn changes the delivery channel, proving routing logic lives
outside reasoning/prompt engineering, not just as an assertion but as a
structural guarantee (the function signature has no `text` or `reply`
parameter to leak through).

## Consequences

- `POST /messages` computes `delivery_channel` after resolving/updating the
  session, independent of companion-core's reply. Today nothing actually
  *acts* on `delivery_channel` (no Telegram bot, no phone push, no
  WebRTC — those are Phases 7/15); it's returned in `MessageResponse` so the
  policy is observable and testable ahead of having real delivery
  mechanisms to plug into it.
- Phase 9 extends `response_policy.py` to take `AgentResponse` as a second
  input and override/refine the mode-driven default (sensitive content,
  urgent alerts, active-meeting suppression per docs §4's routing table).
  Until then, privacy/urgency fields on `AgentResponse` exist in the shared
  model but nothing reads them for routing purposes — don't wire that up
  early; it belongs to Phase 9 once there's real reasoning behind those
  fields worth routing on.
- Setting `interaction_mode` is a session-level action
  (`PATCH /sessions/{user_id}/mode`), not a per-message parameter — a user
  doesn't restate their mode on every turn any more than they restate which
  channel they're on.
