# ADR 0014: Interruption Intelligence

- Status: Accepted
- Date: 2026-09-22

## Context

docs/plan.md's Phase 17 row: "Inputs: calendar, presence, meeting, DND,
urgency, privacy, last interruption. Actions:
ignore/queue/text/gesture/interrupt." Exit criterion: "Routine
notifications defer correctly while user is occupied."

ADR 0006's Phase 9 addendum and ADR 0010 both explicitly deferred this to
here: urgency-driven alerts and meeting/DND-driven queueing "need
infrastructure (push notifications, a queue) this phase's exit criterion
didn't require." Until this phase, `POST /calendar/check-reminders/{user_id}`
routed every due reminder through `resolve_delivery_channel` +
`apply_privacy_override` unconditionally — those two functions decide
*where* a notification goes, never *whether/how aggressively* to deliver it
right now.

## Decisions

**A third pure policy function, not a modification of the first two.**
`interruption_policy.py` (reachy-hub) adds `is_occupied`, `decide_action`,
and `downgrade_for_presence` — deterministic, side-effect-free, composed by
an impure handler in `app.py`, the exact pattern ADR 0006 established for
`response_policy.py`. Routing (where) and interruption (whether/how) stay
two independent axes: a `QUEUE`d notification still has a computed
`delivery_channel` recorded in its audit entry, it just isn't used yet.

**Scope boundary: proactive notifications only.** This engine is never
consulted for `/messages` or `/voice/turn`. ADR 0006's addendum already
established that `delivery_channel` "does not gate a direct reply to a
direct message" — the same reasoning applies to *when*, not just *where*: a
reply to something the user just said is never deferred. Today the only
producer feeding this engine is calendar reminders
(`POST /calendar/check-reminders/{user_id}`); Phase 18's daily briefing
will be the next one, reusing the same `decide_action`/`ReminderRoutingResult`-
shaped flow.

**Concrete signal mapping for each plan.md input:**

| input | source |
|---|---|
| DND | new `AgentSession.dnd: bool`, explicit `PATCH /sessions/{user_id}/dnd` |
| meeting | `AgentSession.privacy_context == MEETING`, now settable via `PATCH /sessions/{user_id}/privacy-context` — manual, since this system has no room-presence sensor |
| calendar | a calendar event in progress *right now*, via `CompanionCoreClient.events_in_progress` — reuses the existing `GET /calendar/events` range query with a 1-second window, no new companion-core endpoint |
| presence | whether a registered robot is actually reachable to perform a gesture (`downgrade_for_presence`) — this codebase has no human-presence sensor either, so "presence" is honestly scoped to *robot* presence, the one thing already modeled (`EmbodimentState`) |
| urgency | `shared.models.response.Urgency`; companion-core's `reminders_due` now grades it (URGENT within 5 minutes of start, NORMAL otherwise) instead of hardcoding URGENT for every reminder — with a hardcoded URGENT, the engine could never demonstrate deferral using real calendar data, since URGENT always wins the occupied carve-out |
| privacy | `shared.models.response.Privacy`, unchanged, already routed by `apply_privacy_override` |
| last interruption | new `AgentSession.last_interruption_at`, set only when `decide_action` returns `INTERRUPT` — drives a cooldown so back-to-back proactive interruptions don't become annoying (docs/plan.md's risk table: "Excessive proactive interruptions... add interruption engine late with conservative defaults") |

**`decide_action`'s five branches, and why each is reachable, not
speculative** (docs/plan.md names all five as in-scope for this phase, so
none is left as dead vocabulary):

- occupied + LOW urgency -> `IGNORE`: routine stuff isn't even worth
  queueing for replay once the user is free again.
- occupied + NORMAL urgency -> `QUEUE`.
- occupied + URGENT urgency -> `GESTURE`: docs §4's explicit carve-out
  ("Urgent event -> phone alert plus Reachy attention gesture" pairs with
  "Active meeting/DND -> queue or silent notification").
- free + LOW urgency, or free + NORMAL urgency within the cooldown of the
  last real interrupt -> `TEXT`.
- otherwise -> `INTERRUPT` (today's original always-deliver behaviour).

**No background poller — flush reuses hooks that already fire.** Matching
ADR 0010's explicit "no background scheduler" stance, there is no timer
that watches for DND turning off or a meeting ending. Instead,
`PATCH /sessions/{user_id}/dnd {"dnd": false}` and
`PATCH /sessions/{user_id}/privacy-context` (when leaving `MEETING`) both
call the same `flush_notifications` helper `POST /notifications/{user_id}/flush`
uses — delivering everything queued the moment the occupied condition that
caused the queueing ends, without inventing a poller.

**A flush is not re-gated.** `flush_notifications` always records
`action=INTERRUPT` and delivers directly — the whole point of a flush is
"the user asked, or stopped being occupied"; re-running `decide_action` on
already-queued content would risk re-queueing it forever.

**`AuditEntry.action` is optional (`None` by default).** `/messages` and
`/voice/turn` never set it — only the reminder/notification/flush path
does. This keeps every other `audit_log.record(...)` call site's signature
unchanged rather than forcing a fake "n/a" value through it.

## Consequences

- `postgres_session_store.py`'s `sessions` table gains `dnd BOOLEAN NOT
  NULL DEFAULT false` and `last_interruption_at TIMESTAMPTZ`;
  `postgres_audit_log.py`'s `audit_log` table gains `action TEXT` (nullable).
  This codebase has no migration framework yet — an already-running dev
  Postgres volume needs `docker compose down -v` to pick up the new
  columns, the same caveat ADR 0010 documented for its own schema addition.
- A new `notification_queue` table/store (`notification_queue.py` +
  `postgres_notification_queue.py`) — same Protocol + InMemory + Postgres
  shape as `audit_log.py`, holding `QueuedNotification`s until flushed.
- `GET /notifications/{user_id}` exposes what's currently deferred, so a
  future client (or the user, via Telegram: "what did I miss?") can inspect
  or trigger delivery of it directly, without waiting on the auto-flush
  hooks.
- `Behaviour.IMPORTANT_NOTICE` (already in the vocabulary, unused until
  now) is what a `GESTURE` action triggers on every registered robot —
  single-tenant/personal-assistant scope, same as `heartbeat_loop`'s
  `for robot in await reg.list()`, not a per-user robot mapping (none
  exists in `robot_registry.py`).
