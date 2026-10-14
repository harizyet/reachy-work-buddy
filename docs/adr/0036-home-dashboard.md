# ADR 0036: Home dashboard and the extended daily briefing

- Status: Accepted (built locally 2026-10-13, not deployed)
- Date: 2026-10-13
- Extends: [ADR 0015](0015-daily-briefing.md) (the daily briefing). Related: [ADR 0033](0033-llm-assisted-read-routing.md), [ADR 0035](0035-read-only-ics-calendar-and-meeting-reminders.md), [Phase 31](../phase-31.md), [Phase 49](../phase-49.md), [Phase 51](../phase-51.md).

## Context

The Web landing page was system status and the Android app opened on Talk. The owner wants one screen for the day: the calendar, tasks, reminders, what is waiting for review and the weather. ADR 0015 already
defined a briefing as a pure, on-demand composition over stores that exist; Home is the same idea with more sources and a screen.

## Decisions

**One read-only aggregation in core, no new storage.** `GET /home` (companion-core, proxied by the hub for the owner session only) composes a structured snapshot from the existing calendar store (one feed revision),
`TaskStore`, `PlannerStore`, the Notepad proposal store and the meeting-analysis item store. No schema change, queue or scheduler. It never accepts, dismisses, creates or schedules anything. `GET /briefing` and the hub's
`POST /briefing/{user_id}` are unchanged; `briefing.py` gains categories and `home_items`, which the Home brief shares with it.

**Authorisation before aggregation.** The caller's `AccessContext` is built from the hub's ceiling header exactly as for `/conversation`. Every record is filtered by sensitivity ceiling and project scope *before* any
list or count is made, so a record the caller may not read changes nothing it sees. At the public ceiling every section is `{"status": "restricted"}`: no content and no counts. The hub sends no ceiling for the
owner dashboard, so core reads at work-private and sensitive records never appear on a glanceable screen. This is deliberately narrower than the document library, where the owner's trusted surfaces read sensitive documents.

**Confirmed and suggested never mix.** Tasks and reminders are the owner's records. Note proposals and meeting action candidates are model-generated suggestions: they appear in their own "waiting for your review" section,
every item carries `pending_review`, and the briefing announces them by count with the words "not tasks until you accept". A meeting action the owner confirmed *is* a task: it is listed once in the tasks section, with its
origin read from the accepting item (`record_id`), and is not also a suggestion. Counts of pending items use status `pending` only (an in-flight accept is not awaiting review).

**Sections fail alone.** Each section carries `status` (`ok`, `empty`, `stale`, `partial`, `off`, `unavailable`, `restricted`, `not_configured`), `partial` is derived from the sources, and a failing source returns a fixed
code, never the exception text. A review queue that fails marks the section `partial`, not zero. `GET /home?sections=a,b` returns only those sections so a client refreshes one card.

**Calendar facts are the calendar's.** Events come from one revision (`generation`, `snapshot_revision`), in the owner's local day. Leave and all-day events are separate banners; a Busy-only, redacted or `busy_private` event
shows the title "Busy" and no location, and the view has no field in which a description could be invented. Cancelled and declined events are not on the schedule. Tasks have no due dates (schema 029), so none is shown or implied.

**Weather is provider data.** `weather.py` calls Open-Meteo (no key; non-commercial use; CC BY 4.0 attribution travels with every answer) with the persona's free-text location (geocoded once per process) and timezone, and
nothing else about the owner. Numbers are validated and displayed as received; weather codes are looked up in a table. Configurable: `WEATHER_ENABLED`, `WEATHER_CACHE_MINUTES` (30), `WEATHER_TIMEOUT_SECONDS` (5),
`WEATHER_STALE_HOURS` (6), optional `WEATHER_LATITUDE`/`WEATHER_LONGITUDE`. A failed refresh shows the last answer labelled `stale` until it is too old, then `unavailable`. One provider call at a time. Weather is never a dependency of another section.

**The wording is optional and checked.** `POST /home/brief` returns the deterministic lines (each `confirmed`, `pending_review` or `info`) and, when asked, the local model's rewording of exactly those lines. The model is
local-only (the Notepad provider, so private records never reach a cloud model), receives only the already-authorised lines, and cannot act. Its answer is used only if non-empty, bounded, and every number, time and spelled
count in it already occurs in the lines; otherwise the deterministic briefing is returned with a fixed `fallback` reason. The lines are always shown beside the wording as the record.

**Clients.** Web: Home is the index route; the former Overview is `#/system` (Assistant menu), unchanged. Android: five primary destinations with Home first and the default; tapping any item opens the screen that already
holds it (Tasks open the Reminders screen, which lists them). The saved copy of the last snapshot is app-private and removed on sign-out. Scheduled notifications and spoken briefings are not part of this decision.

## Consequences

- No schema, migration, queue or background task. Deploying means core and hub only, plus the Android release; a core restart is a Phase 48 cohort boundary as usual.
- The Open-Meteo call is the first outbound request core makes for an owner convenience with the owner's location name; `WEATHER_ENABLED=false` removes it.
- Android navigation tests and the web landing tests changed because the default destination changed; the Phase 18 endpoints did not.
