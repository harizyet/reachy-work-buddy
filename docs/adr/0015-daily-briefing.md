# ADR 0015: Daily Briefing

- Status: Accepted
- Date: 2026-09-22

## Context

docs/plan.md's Phase 18 row: "Combine calendar/tasks/email/reminders/project
events into prioritized arrival briefing." Exit criterion: "Reachy greets;
detailed briefing is privately delivered."

ADR 0014's Consequences section already named this as the next producer for
the interruption engine: "Phase 18's daily briefing will be the next one,
reusing the same `decide_action`/`ReminderRoutingResult`-shaped flow."

## Decisions

**Two independent acts, not one.** "Reachy greets" (an embodied arrival
gesture) and "detailed briefing is privately delivered" (the actual
content) are handled by different code paths inside one endpoint,
`POST /briefing/{user_id}`:

- The greeting (`Behaviour.GREETING`) is unconditional — fired whenever a
  robot is reachable, regardless of DND/meeting/occupied state. A wave
  costs nothing and isn't itself private information, unlike the content.
- The detailed text is routed through the *exact* same
  `resolve_delivery_channel` / `apply_privacy_override` / `decide_action` /
  `downgrade_for_presence` pipeline `POST /calendar/check-reminders/{user_id}`
  (Phase 17) already established — no new routing logic. If the user is
  occupied, the briefing can be `QUEUE`d exactly like a routine reminder
  would be, and later flushed by the same DND/privacy-context hooks
  (ADR 0014).

**Privacy is forced, not classified per-request.** The whole briefing is
always submitted as `Privacy.WORK_PRIVATE` to `apply_privacy_override` —
it's an aggregate of calendar/tasks/email content, which this codebase
already treats as work-private everywhere else (see `check_reminders`,
the memory-capture conversation path). This is the literal mechanism
behind "privately delivered": `apply_privacy_override` vetoes Reachy's
speaker for `WORK_PRIVATE` content regardless of interaction mode.

**One urgency for one delivery decision.** `decide_action` takes a single
`Urgency`, but a briefing is a list of items with different urgencies.
`reachy-hub`'s `_overall_urgency` takes the *highest* urgency among the
briefing's items (URGENT beats NORMAL beats LOW) — one imminent meeting is
enough to earn the whole briefing a `GESTURE` while occupied, matching
docs §4's "Urgent event -> phone alert plus Reachy attention gesture." An
empty briefing (nothing to report) grades LOW, not NORMAL, so it never
out-competes a real notification for the same interruption cooldown.

**companion-core composes the list; reachy-hub only formats and routes
it.** `companion_core/briefing.py`'s `build_briefing` is a pure function
(same shape as `calendar/reminders.py`'s `due_reminders`) over four stores
that already exist — no new storage, no background scheduler, same
"callable on demand" discipline ADR 0010/0014 established. `GET /briefing`
exposes it; `reachy-hub`'s `POST /briefing/{user_id}` is the one caller,
turning the list into one delivery decision and one piece of text.

**Concrete source mapping for each plan.md input:**

| input | source |
|---|---|
| calendar | `CalendarStore.list_events` for the next 24h — the day's whole schedule |
| reminders | `calendar/reminders.due_reminders` + `reminder_urgency` (Phase 10/17), reused verbatim, not reimplemented — see below |
| tasks | `TaskStore.list_tasks(OPEN)` (Phase 11) |
| email | `EmailStore.list_received()` filtered to the last 24h — `EmailMessage` has no read/unread flag (no real inbox sync exists), so "received recently" is the honest stand-in for "unread" |
| project events | recent (48h) `MemoryRecord`s of type `EPISODIC` with a non-null `project_scope` (Phase 12) — this codebase has no dedicated "project events" store; docs/plan.md names it as an input to combine, not a phase of its own, so project-scoped episodic memory is the honest existing source, the same scope-to-what-exists discipline ADR 0014 used for "presence" |

**Reminders and calendar deliberately overlap.** An event starting within
15 minutes appears twice: once as a `REMINDER` item (urgency-graded via the
same 5-minute proximity rule `/calendar/reminders/due` uses — extracted
into `reminders.reminder_urgency` so neither call site duplicates the
constant), once as part of the day's full `CALENDAR` schedule. This is not
de-duplicated: a reminder is a *subset* of the calendar highlighted for
urgency, not a separate source of truth.

**Prioritization is a fixed sort, not a scored ranking.** `briefing.py`
sorts by urgency rank first (URGENT/NORMAL/LOW), then by a fixed category
order (REMINDER, CALENDAR, TASK, EMAIL, PROJECT) — reminders lead since
they're the one category already urgency-graded for "starting very soon";
project context trails since it's the least time-bound. No numeric scoring
model — nothing in the exit criterion asks for one, and a fixed,
inspectable order is easier to reason about and test than a weighted score.

## Consequences

- No new companion-core storage and no new reachy-hub storage — the
  briefing reuses `notification_queue`/`audit_log`/`AgentSession.dnd`/
  `last_interruption_at` exactly as ADR 0014 left them. No Postgres schema
  change, so none of HANDOVER.md's "needs `docker compose down -v`"
  caveat applies to this phase.
- `calendar/reminders.py` gained `reminder_urgency` (extracted from
  `app.py`'s `/calendar/reminders/due` handler) purely so `briefing.py`
  doesn't duplicate the 5-minute urgency constant. `/calendar/reminders/due`'s
  behavior is unchanged — same inputs, same outputs.
- `companion_core/briefing.py` — new module, `BriefingItem`/
  `BriefingCategory` (companion-core-only, not `shared/models`, same ADR
  0001 reasoning as `ReminderPayload`) and `build_briefing`.
- `GET /briefing` (companion-core) and `POST /briefing/{user_id}`
  (reachy-hub) — new endpoints, no changes to any existing route's
  contract.
- This engine has no notion of "arrival" beyond an explicit call to
  `POST /briefing/{user_id}` — there is no presence sensor or scheduler in
  this codebase (same honesty-about-scope as ADR 0014's presence mapping).
  A future channel (a Telegram command, a voice phrase, or eventually a
  real arrival signal) can call this endpoint; none is wired up by this
  phase, matching the "no background scheduler" precedent.
