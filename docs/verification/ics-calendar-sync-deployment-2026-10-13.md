# Calendar screens and immediate synchronisation: MS-01 deployment record (2026-10-13)

Owner approval (2026-10-13): a controlled homelab deployment of the core and hub changes and a versioned debug APK, as two separate acceptance gates. Commit `69bb9f7` (branch `feature/ics-calendar-meeting-reminders`, **not merged to main**). Earlier: [feature deployment](ics-calendar-deployment-2026-10-13.md), [screens and sync verification](ics-calendar-screens-and-sync-2026-10-13.md), [navigation](ics-calendar-navigation-2026-10-13.md).

| | Before | After |
|---|---|---|
| Schema | `033_calendar_feed` | unchanged (no migration; the gate was not run) |
| core | `22b26023e1c7` | `0e962d744772` (tag `calsync-69bb9f7`) |
| hub | `5ada81bd1f98` | `b8a5eab5220e` (tag `calsync-69bb9f7`) |

Built from a clean worktree of `69bb9f7` (removed afterwards). Core was stopped gracefully (`docker stop -t 30`, exit 0, not OOM-killed), then hub; the stop-time dump was taken; then `up -d --no-build --no-deps` for core and hub. Untouched: PostgreSQL, PgBouncer, coding-agent, vLLM, document worker, Caddy, SearXNG, router, transcription, diarization, the robot, every flag, `.env`. Preconditions: no alarm or reminder due within 45 minutes, no meeting in the pipeline. Downtime about 10 seconds.

## Backup and rollback

Dump `~/reachy-backups/reachy-before-calsync-stop-*.dump` (330,354 bytes, 0600, sha256 prefix `0ad6382ebd7b24da`; the 033 deployment dumps are also kept). Images `reachy-rollback/{companion-core,reachy-hub}:pre-calsync` (equal to the previous running images) plus the earlier `pre-033` set. Rollback: tag `pre-calsync` back as `latest` and `up -d --no-build --no-deps companion-core reachy-hub`; no schema step. Keep until the owner accepts.

## Phase 48 boundary

The segment that started 2026-10-13 05:10:57 UTC ended at the graceful stop (12:55:11 UTC) with counters `{}`, saved with a copy of the selective-shadow file in `~/reachy-backups/phase48-boundary-calsync/`. **New segment from 2026-10-13 12:55:18 UTC** (core `process_started_at`), counters `{}`. No conversation turns were made.

## Verification (against the deployed core, with its service token)

The owner had no feed set, so the checks used a synthetic calendar through core's routes and then removed it (the encrypted source deleted: `secrets` rows for `ics` 0, `calendar_feed` back to unset; the revision counter moved on, which is harmless).
1. Upload of 5 events plus a hidden one: all shown at once, classified (4 meetings, 1 personal appointment, 1 Busy); the Busy entry showed "Busy" and its time only (no title, no location anywhere in the response); reminders only for the 4 meetings; the schedule's revision equalled the reminders' revision.
2. Replace with 3: the other events and their reminders gone.
3. Move a meeting one hour: its reminder time moved with it.
4. Cancel a meeting: its reminder gone.
5. Malformed file: refused (`not_calendar`), the 2 events and the revision kept, error and state "error" recorded.
6. Valid empty calendar: 0 events, no error, state "ok", no reminders.
Also: core `/health` 200, no traceback in core or hub logs, hub `/calendar-feed`, `/schedule`, `/reminders` and `/upload` answer 401 without an owner session.

**Not verified:** the owner-session path (the hub routes with a login) on the deployed hub, the Web pages in the owner's browser, and anything on the owner's physical phone.

## Android APK (gate 2, not yet accepted)

`~/reachy-releases/reachy-companion-0.18.0-calendar-debug.apk` (versionName 0.18.0, versionCode 2; the earlier APKs are untouched), sha256 `c94fd166863ce523278b1c5cd8dfe9f9906f93663223e2be6a4a9cbaae7c8b18`. It contains the Calendar screen, the four-destination navigation and the stale-notification fix. Not installed on a physical phone by me (none is attached to this machine).

## Owner acceptance checklist (physical phone)

1. Install over the current app (same signing key); allow notifications; sign in.
2. Web: Settings > Accounts > Calendar feed: add the link or upload a file, add your email addresses; Planner > Calendar shows the events.
3. Phone: Meetings (or Planner > Calendar) shows the events; a meeting reminder arrives 5 minutes before; **Start recording** opens Meetings with the meeting prepared and does not record until you tap Record.
4. Replace the calendar with the app open on the Calendar tab (updates within about 20 seconds) and with the app in the background (updates at the next background check, up to about 15 minutes; there is no push).
5. **Release criterion:** move and cancel a meeting whose notification is showing; after the phone has synchronised, no obsolete notification may remain (verified on the emulator, both foreground and background).
