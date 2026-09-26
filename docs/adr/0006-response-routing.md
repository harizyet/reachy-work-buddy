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
   events") and is now implemented — see the Phase 9 addendum below.

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
  session, independent of companion-core's reply. It's returned in
  `MessageResponse` so the policy is observable and testable.
- **`delivery_channel` does not gate a direct reply to a direct message.**
  A channel integration that receives an inbound message (Phase 7's
  Telegram bot; Phase 15's WebRTC phone call) always replies on that same
  channel — ordinary chat-bot UX, and the only way a fresh session (which
  defaults to Desk mode, whose `delivery_channel` is always `reachy`) can
  ever get its first Telegram reply at all. `delivery_channel` is for
  content that doesn't already have an originating channel — proactive
  notifications, alerts, briefings (Phases 17-18) — where the policy is the
  *only* signal for where to push it. This split wasn't obvious until Phase
  7 actually built a channel integration against it; earlier phases only
  had simulated channels and couldn't surface the gap.
- Setting `interaction_mode` is a session-level action
  (`PATCH /sessions/{user_id}/mode`), not a per-message parameter — a user
  doesn't restate their mode on every turn any more than they restate which
  channel they're on.

## Phase 9 addendum: privacy override + audit

`response_policy.apply_privacy_override(base_channel, privacy, active_channel)`
is a **second, separate function**, not a modification of
`resolve_delivery_channel` — that function's narrow signature (mode,
active_channel only) is itself a structural guarantee with its own test
(`test_policy_is_pure_and_ignores_anything_but_mode_and_channel`), and a
privacy override must not erode it. `apply_privacy_override` can only ever
veto a `Reachy` delivery `resolve_delivery_channel` already chose; it never
introduces routing to a channel the mode policy didn't pick.

Privacy is proposed by companion-core (`privacy_classifier.py` — a
placeholder keyword classifier, same honesty-about-scope as every other
placeholder in this codebase; Phase 10+ replaces the classification logic,
not the contract) and enforced here:

| `privacy` | Effect on a `Reachy` base delivery |
|---|---|
| `public` | No change |
| `work-private` | Vetoed — falls back to the active channel (or `web` if that's also Reachy) |
| `sensitive` | Vetoed — same fallback |

Both non-public levels are treated the same and the veto applies
**regardless of mode** — including Desk, which Phase 6 treats as "private
room" for mode-only routing purposes. Docs §4's routing table says
sensitive content goes to "a private channel only," full stop; this system
has no way to verify Desk mode actually means a private room right now, so
the override doesn't carve out an exception for it. This was confirmed to
matter, not just a theoretical concern: an earlier Phase 6 test used
calendar-flavored example text and started failing once this classifier
landed, because Desk mode no longer spoke it aloud — the test's text was
fixed, not the policy.

Urgency-driven behavior (phone alert + Reachy attention gesture) and
active-meeting/DND-driven queueing, both in docs §4's routing table, are
**not** implemented — they need infrastructure (push notifications, a
queue) this phase's exit criterion didn't require. `AgentResponse.urgency`
is round-tripped as metadata (audit-logged) but nothing acts on it yet.

Every routing decision is recorded via `audit_log.py`
(`AuditEntry`: user, session, channel, mode, privacy, base_channel,
delivery_channel, whether an override fired) and exposed at
`GET /audit/{user_id}` — the "audit events" half of Phase 9's deliverable,
and the mechanism that makes "the policy engine has final authority"
checkable after the fact, not just trusted at request time.

## Carried privacy expires with the model's context (2026-09-26)

Core carries a conversation's strongest privacy label into later replies,
so a follow-up such as "tell me more" cannot speak earlier calendar, email
or sensitive content aloud. Since Phase 24d, a keyword in the model's own
wording labels only that reply; private data in the history keeps
carrying. In the 24e physical run, one typed question containing "meeting"
labelled the whole conversation work-private, and the robot stayed silent
in Desk mode until core restarted.

**Decision (owner, 2026-09-26):** a carried label applies only while the
message it came from is still in the context the model sees
(`CONTEXT_MESSAGES`, the last 39 messages). After that the model cannot
repeat it, so later replies are labelled on their own content again. A
label on the current turn is unaffected, and private content still in
context keeps the conversation private.
