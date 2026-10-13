# ICS calendar feed and meeting reminders: MS-01 deployment record (2026-10-13)

Owner authorization: "Commit push build and deploy", then, after the first migration step was blocked by the permission classifier and the old services were restarted, "i give permission" (2026-10-13). Commit `7c681ea` (branch `feature/ics-calendar-meeting-reminders`, **not merged to main**). Design: [ADR 0035](../adr/0035-read-only-ics-calendar-and-meeting-reminders.md); local verification: [record](ics-calendar-meeting-reminders-2026-10-13.md).

| | Before | After |
|---|---|---|
| Schema | `032_meeting_analysis` | `033_calendar_feed` (table `calendar_feed`, one empty owner row) |
| core | `3f792ddf4d35` | `22b26023e1c7` (tag `cal033-7c681ea`) |
| hub | `bb72e8f83964` | `5ada81bd1f98` |
| coding-agent | `9c20355f64cc` | `7ea5860efff1` |
| migrate | `f0e063e40124` | `6b005ef00d14` |

Images were built from a clean worktree of `7c681ea` (removed afterwards). Untouched: PostgreSQL, PgBouncer, vLLM, document worker, Caddy, SearXNG, router, transcription, diarization, the robot, every flag and `.env`.

## Timeline (UTC)

04:55 first graceful stop (core exit 0, not OOM-killed) and dump; the migration step was then blocked, and at about 05:01 the old containers were restarted unchanged (about 5 minutes of downtime, schema untouched). 05:05 second graceful stop, fresh dump; waited for PgBouncer's idle connections to close (05:10:39); **migrate applied 033**; 05:10:56 core, hub and coding-agent started on the new images. Second downtime about 5 minutes.

## Backup and rollback

Dumps (0600): `~/reachy-backups/reachy-before-033-stop-20261013-125539.dump` (330,139 bytes, sha256 prefix `d1b2b0afdc4235f7`, restore verified into a `--network none` container: revision 032, 53 tables) and `reachy-before-033-stop2-*.dump` (taken after the restart). Images `reachy-rollback/{companion-core,reachy-hub,coding-agent-service,migrate}:pre-033`. Rollback: stop the three services, `deploy/homelab/rollback-033.sql`, retag the `pre-033` images as `latest`, `up -d --no-build --no-deps`. Keep until the owner accepts.

## Phase 48 boundary

Two restarts today. Segment ended 04:55 (core started 2026-10-13 00:41:36) with counters `{}`; second segment (05:01:06 to 05:05) `{}`; both saved in `~/reachy-backups/phase48-boundary-calendar/` with a copy of the selective-shadow file. **New segment from 2026-10-13 05:10:57 UTC**, counters `{}`; no conversation turns were made.

## Verification

Core `/health` 200 on the new image; no traceback in the first minutes of core, hub or coding-agent logs; revision 033 and the `calendar_feed` owner row present with no secret; core `/calendar/feed` reports not configured, `/calendar/events` and `/calendar/meeting-reminders` answer (empty), meetings (1) and tasks (2) unchanged; hub `/calendar-feed` and `/calendar-feed/reminders` answer 401 without an owner session.

**Not verified:** setting a real feed (no URL was entered; none was supplied), the Settings card in a browser, the phone, the real calendar's format. Next for the owner: Settings > Accounts > Calendar feed, add the link and your email addresses; install the debug APK.
