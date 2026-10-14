# ADR 0035: Read-only ICS calendar feed, deterministic event classification and meeting recording reminders

- Status: Accepted (deployed 2026-10-13, merged to `main` 2026-10-14)
- Date: 2026-10-13
- Extends: [ADR 0010](0010-calendar.md) (the calendar tool boundary). Related: [ADR 0027](0027-alarms-and-presence-gated-delivery.md), [ADR 0029](0029-android-companion-app.md).

## Context

ADR 0010 left the calendar a local store with a seam for a real provider. The owner wants meetings from an external iCalendar feed, a phone notification before each real meeting, and a
way from that notification to the existing meeting recorder, without a third-party cloud, calendar writes or Google OAuth.

## Decisions

**A read-only HTTPS ICS provider behind the existing `CalendarStore`.** `FeedCalendar` wraps the existing store (and the Google one) and adds feed events; writes go only to the inner
store. Parsing is the `icalendar` and `recurring-ical-events` libraries (two new dependencies; no hand-written RFC 5545). Recurrence, EXDATE, RECURRENCE-ID exceptions, cancellations
(STATUS and METHOD:CANCEL), time zones, floating times, DATE versus DATE-TIME and VFREEBUSY come from them.

**The feed URL is a credential.** It goes through the existing encrypted `secrets` store (provider `ics`); the new `calendar_feed` table (migration 033, one row) holds only the reference.
No route returns it, every error is a fixed code, and httpx's request logging is suppressed while a feed downloads. The fetcher accepts only `https` (or `webcal`), port 443, no credentials in
the URL, resolves the host itself, refuses any non-public address (loopback, private, link-local, CGNAT such as Tailscale, multicast, reserved, NAT64/6to4/Teredo, IPv4-mapped), connects to the
checked address, follows at most three redirects that each pass the same checks, caps the size after decompression, and requires a calendar. `CALENDAR_FEED_ALLOW_LOCAL_FOR_TESTING=1` relaxes
the address rules for local fixtures only and must never be set in a deployment.

**Snapshot and freshness.** Each refresh replaces the snapshot with `EventFacts` (no description; a hidden event keeps only its time). A failed refresh keeps the last good snapshot and records a
fixed error code; the status reports `fresh`, `stale` (older than two intervals plus five minutes), `never` or `not_configured`, and spoken answers say when they rest on a stale copy.

**Classification is deterministic and independent of the model** (`calendar/classify.py`). Classes: `meeting`, `personal_appointment`, `leave_or_ooo`, `all_day`, `unknown_timed`,
`busy_private`. All-day is the DTSTART value type (DATE), never the length, and an all-day DTEND is exclusive. Leave is an out-of-office busy status or a configurable whole-word list, unless the
event plainly is a meeting. A timed event is a meeting on explicit evidence (other attendees, a conferencing property or link, an organiser who is not the owner), a configurable title rule second,
a personal appointment on its own word list, otherwise `unknown_timed`: it is not guessed to be a meeting. CLASS:PRIVATE/CONFIDENTIAL, free/busy blocks and a publisher's "Busy" title are
`busy_private` and keep their details hidden whatever the owner chooses. Each result carries its basis (`explicit`, `rule`, `owner`) and reason codes. The owner can override one occurrence or a
series; rules and overrides apply at read time, so changing them needs no download.

**Recording reminders** exist only for a meeting (explicit, rule when allowed, or the owner's choice), never for cancelled, declined, all-day, leave, personal, unknown or hidden events. A leave day
does not suppress meetings unless the owner turns that on. Identity is the series key (hash of the UID) plus the original recurrence start, so a moved instance keeps its key; one-off events use a
fixed token. A reminder is `due = start - lead` (default 5 minutes, 1 to 120). The existing channel-routed `/calendar/reminders/due` ignores feed events.

**Interruption signal.** The hub's "is an event in progress" check now asks core for `occupying=true` events only, so a leave day or all-day banner no longer silences alarms and reminders.

**Android.** The phone fetches the bounded set (72 hours by default) from the hub over the owner session, schedules each with AlarmManager (exact when allowed, approximate otherwise), keeps
the set in app-private storage, re-arms after reboot, app update and clock change without a network, and reconciles on app launch, on opening Meetings, and in the existing 15-minute job. The
notification is its own category (not an alarm), shows no title on the lock screen, and has **Start recording** and **Dismiss**. Start recording only opens the Meetings tab with the meeting
prepared; the owner taps Record. A recording started that way is titled from the calendar, and the owner's title and the scheduled time are set after the existing upload. A map from the occurrence
key to the meeting it became, and a note beside any clip waiting to upload, stop a second record. Nothing is uploaded except by the existing Stop-and-save flow. Transcription, diarization,
summaries and analysis are unchanged.

**Hub.** An owner-session-only proxy under `/calendar-feed` (CSRF on every change, no bearer path, fixed errors that never echo input).

## Consequences

- One migration (`033_calendar_feed`, `rollback-033.sql`); `SCHEMA_REVISION` is `033_calendar_feed`, so a deploy is backup, then core, hub and coding-agent together, on owner approval.
- Two new Python dependencies (four packages with `tzdata` and `x-wr-timezone`).
- Duplicate-record prevention is on the phone: a second phone, or a recording uploaded by another path, is not seen. A server-side idempotency key would need a schema change and was not made.
- Calendar titles and times are stored on the phone (app-private, not backed up, removed on sign-out or when reminders are turned off); the title is the only calendar text in the notification.
- Google events are classified by title and the all-day flag only and get no phone reminders in this version.
- Single owner, single feed. Not built: calendar writes, event creation, push from a cloud service, per-occurrence "never remind for this series" beyond a classification override.

## Addendum 2026-10-13: Calendar screens and immediate synchronisation

**One publication path.** Every change of source (a new link, an uploaded `.ics` file, a manual or periodic refresh) obtains the bytes, parses and validates the WHOLE calendar, and only then publishes it: one atomic store write (the encrypted source, the snapshot and the status together), after which the epoch, the caches and the revision move. A link or file that fails validation changes nothing except the recorded error, so the last valid snapshot stays available (a link is now downloaded and validated before it is stored). A calendar that parses with no events is a valid, intentional empty snapshot.

**Revision.** `generation` (status) advances only when something the owner would see changed: the published content (a fingerprint of the occurrences), the source, or a rule, setting or override. A repeated upload or an unchanged refresh does not move it. The Web and Android both read `GET /calendar-feed/schedule`, which returns the events and the feed's status from one state, together with `generation` and `snapshot_revision`; the reminder payload carries the same pair.

**Concurrency.** A refresh remembers the source epoch it started under and is discarded if a newer source was published meanwhile, so an older download can never overwrite a newer upload. Concurrent refreshes share one download, identical concurrent uploads share one parse, and different concurrent uploads end as exactly one whole calendar. An uploaded file is kept encrypted in the same secret store (kind `upload` in the status, no new column or migration) and re-read, not re-downloaded, by the periodic refresh, so its recurrences keep expanding.

**Delivery to clients, without push.** There is no push transport. The Web page polls every 20 seconds and on focus and is also refreshed by its own actions. The phone reconciles when the app opens (it re-arms stored reminders first, because a force-stop clears every alarm), while the Calendar tab is open (every 20 seconds, and at once when the revision differs from the one its reminders were built from), in the existing 15-minute job and after a restart. A phone that is offline reconciles on its next connection; nothing here claims instant device delivery.

**Two clocks.** The screens show the source's last successful refresh (server clock) separately from the last time this client successfully read the server, plus the state (`ok`, `refreshing`, `error`, `stale`, `never`, `not_configured`), the source (host of the link, or the uploaded file's name, never the path of a link), the event count and the last error. A copy that is stale, failed its last refresh, or was read from the phone's saved copy because the hub was unreachable is labelled cached.

**Known limits.** A cold start with the hub unreachable still lands on the sign-in screen (existing behaviour, not changed): the saved calendar is shown when the hub drops while the app is open, not from a cold offline start. Android cannot upload a file; the Web can. Keys of events never collide across sources because exactly one source is active and event keys are namespaced `ics:` (Google and local ids are different).
