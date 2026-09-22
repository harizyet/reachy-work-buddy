# ADR 0010: Calendar Tool Boundary and Reminder Routing

- Status: Accepted
- Date: 2026-09-22

## Context

docs/plan.md's Phase 10 row: "Read-only next/list/free-busy first; later
writes behind confirmation," exit criterion "'What's next?' works and
meeting reminders route appropriately." Per ADR 0001, calendar is
exclusively companion-core's — reachy-hub and reachy-embodiment never touch
calendar data directly.

No external calendar credential (Google Calendar, CalDAV, ICS feed) was
available when this phase was built. Following the same
graceful-degradation-without-credentials approach used for Telegram (ADR
none, see Phase 7 README) and TTS (Phase 8, tts.py), the concrete
`CalendarStore` is a local Postgres-backed store, not a stub — real,
durable, genuinely answering "what's next" from stored data. A real
provider (Google Calendar, CalDAV) implements the same `CalendarStore`
protocol later without any caller changing.

## Decisions

**companion-core owns a database connection for the first time.**
Every prior phase kept companion-core entirely stateless beyond an
in-memory conversation transcript (`conversation.py`) — this is the first
time it needs durable storage. It shares the same Postgres instance as
reachy-hub (`deploy/homelab/docker-compose.yml`), different tables — a
single-tenant homelab has no reason to run two database containers, and
docs/plan.md §8 already describes "PostgreSQL | Homelab" as one shared
resource, not one per service.

**The agent's calendar access is read-only; event creation is a separate,
explicitly-administrative API.** `POST /calendar/events` exists only
because there's no external sync in this V0.1 default — something has to
put events into the store. It is not part of the read path
(`next_event`/`list_events`) the placeholder reasoning in `/conversation`
uses, and it is not gated by any confirmation flow the way docs §4
describes calendar *writes* eventually needing to be (that gate is
deferred: this phase doesn't yet have anything that writes to the calendar
*as an agent action*, only as an operator/setup action).

**"What's next" is answered by real data through a placeholder intent
matcher, not a stub.** `calendar_intent.is_next_event_query` is a keyword
matcher (same honesty-about-scope as `privacy_classifier.py`) — Phase 10's
exit criterion is that the *answer* is genuinely computed from real
calendar data, not that the question-understanding is sophisticated. Phase
10+ reasoning replaces the matcher, not the read path it calls.

**Calendar content is always `work-private`, determined by the source, not
inferred from keywords.** When `/conversation` answers a calendar query,
`privacy` is set to `Privacy.WORK_PRIVATE` unconditionally — not run
through `classify_privacy(text)` — because we know for certain the reply
reveals schedule details, regardless of whether the query text happened to
contain a privacy keyword. This is more precise than the generic
placeholder-reply path, which still infers privacy from the *input* text
since it has no other signal.

**Meeting reminders reuse Phase 6/9's routing exactly; no new routing
logic, no scheduler.** `reachy-hub`'s `POST /calendar/check-reminders/{user_id}`
is a pure on-demand query: it asks companion-core which events are due
(`companion_core/calendar/reminders.py`), then runs each through the exact
same `resolve_delivery_channel` + `apply_privacy_override` + `audit_log`
pipeline `POST /messages` uses. There is no background poller, no queue, no
push-notification infrastructure — that's proactive-notification
infrastructure explicitly scoped to Phases 17-18 in docs/plan.md, not
Phase 10. "Meeting reminders route appropriately" is satisfied by proving
the routing decision is correct when the check is invoked, not by making
the check happen automatically on a schedule.

**Free/busy reveals only time blocks, not event details.**
`GET /calendar/free-busy` returns `{start, end}` pairs only — no title, no
location — a narrower privacy surface than `GET /calendar/events`, matching
the conventional meaning of "free/busy" (share availability without
disclosing what's actually on the calendar).

## Consequences

- `deploy/homelab/docker-compose.yml`'s `companion-core` service now has a
  `DATABASE_URL` and a `depends_on: postgres` — the compose stack's first
  change to companion-core's dependency graph since Phase 4.
- An existing Phase 5 test (`test_two_test_clients_share_one_conversation_state_across_channels`)
  and a Phase 6 test broke when this landed: both used calendar/"what's
  next"-flavored example text, which Phase 10's intent matcher or privacy
  classifier now correctly intercepts. Both tests' example text was fixed,
  not the new behavior — the same pattern as Phase 9's ADR 0006 addendum.
- `delivered: false` on a reminder-routing result is not an error — it
  means the resolved channel has no real delivery path configured (e.g.
  Telegram enabled but no `chat_id` learned yet, or the channel isn't
  Telegram at all — Phone/Remote have no real push mechanism yet). The
  routing decision itself is still computed and audited regardless.
