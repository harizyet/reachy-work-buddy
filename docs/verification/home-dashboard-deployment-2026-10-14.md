# Home dashboard: MS-01 deployment record (2026-10-14)

Owner instruction "Build and deploy" (2026-10-14) for the Home dashboard, commit `4c0e2db` (branch `feature/home-dashboard`, **not merged**). Design and test evidence: [ADR 0036](../adr/0036-home-dashboard.md), [verification](home-dashboard-2026-10-13.md).

| | Before | After |
|---|---|---|
| Schema | `033_calendar_feed` | unchanged (no migration) |
| core | `0e962d744772` | `40bc6ba09ed9` (tag `home-4c0e2db`) |
| hub | `b8a5eab5220e` | `567f16c77f0b` (tag `home-4c0e2db`) |

Built from a clean worktree of `4c0e2db` (removed afterwards). Core stopped gracefully (`docker stop -t 30`, exit 0, not OOM-killed), then hub; stop-time dump taken; then `up -d --no-build --no-deps` for core and hub. Untouched: PostgreSQL, PgBouncer, coding-agent, vLLM, document worker, Caddy, SearXNG, router, transcription, diarization, the robot, `.env` and every flag. Compose now passes `WEATHER_*` with defaults (weather on, needs the persona location). Preconditions checked first: no alarm or reminder due within 45 minutes, no meeting in the pipeline. Downtime about 20 seconds. Core started 2026-10-14 00:41:19 UTC.

## Backup and rollback
Dump `~/reachy-backups/reachy-before-home-stop-20261014-084101.dump` (525,481 bytes, 0600, sha256 prefix `aed2e5848828c62e`). Rollback images `reachy-rollback/{companion-core,reachy-hub}:pre-home` (the previous running images, preserved by immutable ID before the build). Rollback: tag `pre-home` back as the service image and `up -d --no-build --no-deps companion-core reachy-hub`; no schema step. Keep until the owner accepts.

## Phase 48 boundary (a gap, stated plainly)
The capture-counters read needs core's service token, and the permission classifier denied reading it from the container; the owner then said "Deploy" without allowing that read, so the counters of the segment that ended at the graceful stop (2026-10-14 00:41 UTC; it began 2026-10-13 12:55:18 UTC) **were not saved**, and the shutdown log held no summary line. That segment's tally is an accepted gap, like the 2026-10-10 14:06 to 14:34 one. New segment from the core start above, counters `{}`. No conversation turns were made. Stop time and the last core log lines are in `~/reachy-backups/phase48-boundary-home/`.

## Verification on the deployed stack (no credential was read)
Core `/health` 200; hub `/health` 200; no traceback in either log since start; hub `/home`, `/home?sections=`, `POST /home/brief` and `/status` answer 401 without an owner session; the served web bundle contains the Home page ("Brief me on today"). **Not verified on the live system:** the owner-session path (`GET /home` through the hub), the weather card against the real Open-Meteo and the persona location, the briefing with the real local model, and the owner's browser and phone. Those are the owner's acceptance checks.

## Android APK (separate acceptance gate)
`~/reachy-releases/reachy-companion-0.19.0-home-debug.apk` (versionName 0.19.0, versionCode 4; earlier APKs untouched), sha256 `8f0257bb85e5eb437743ef2b4e76724021103d20d0b6a39f1941178dc5bfc45a` (also in the `.sha256` file). Built from the same commit; not installed (no phone attached here). It also carries 0.18.1's keyboard bar change: check on the phone that the bottom bar is visible (it was not on the emulator).

## Owner acceptance checklist
1. Web: sign in lands on Home; cards fill; Refresh on one card; "Brief me on today"; System (Assistant menu) shows the old status page. Settings > Assistant: set the location for weather.
2. Phone: install 0.19.0 over the current app; Home is the first screen; bottom bar visible; tap-through; briefly background and reopen; airplane mode shows the saved copy.
3. Confirm suggestions are not counted as tasks, and that no sensitive task appears on Home.
