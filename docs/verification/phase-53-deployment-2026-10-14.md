# Phase 53 deployment: migration 034 and coordinated cutover, feature OFF (2026-10-14)

Owner authorization (2026-10-14): "commit push and deploy", then "ok i approve" after the first production step was blocked, and "ok approved" after the migration step was blocked. **It covers the cutover below only. It does not cover enabling `MEETING_MULTIMODAL_ENABLED`**, which stays false and needs a separate approval. The branch was pushed but **not merged** to `main`.

| | Before | After |
|---|---|---|
| Schema revision | `033_calendar_feed` | `034_meeting_multimodal` |
| core | `40bc6ba09ed9` | `e92463cc8334` (tag `p53-97fed63`) |
| hub | `567f16c77f0b` | `a88e77f55dfc` |
| coding-agent | `7ea5860efff1` | `7d8773f1e006` |
| document-worker | `2f601ff1df34` | `25afdac34614` (wider file types) |
| migrate | `6b005ef00d14` | `b9d01f4f6e75` |

Code: images built from commit `97fed63` (branch `feature/meeting-multimodal`, pushed to origin), which is also the Compose working tree (it adds the `MEETING_MULTIMODAL_ENABLED` pass-through, default false).

## Timeline (UTC, 2026-10-14)

07:36 preconditions (read-only): no alarm or reminder due within 30 minutes, two meetings both `complete`, no analysis run active, revision `033_calendar_feed`. Rollback tags created and checked against the running image IDs. Images built (about 10 minutes, running services untouched). 07:39:56 core, hub, coding-agent and document-worker stopped and PgBouncer restarted (so the migration finds no idle pooled connection); stop-time dump taken. The migration step was held up by the permission classifier until the owner approved it again, so the stack stayed down for that wait. Migration applied, services started 07:44:07. **Downtime from 07:39:56 to 07:44:07 plus the time the stack stayed stopped while approval was awaited** (the dump and approval waits dominate; the migration itself took seconds).

## Backup and rollback

| Item | Value |
|---|---|
| Stop-time dump (the rollback point) | `~/reachy-backups/reachy-before-034-stop-20261014-074007.dump`, 1,848,003 bytes, 0600, sha256 prefix `c0ba5df4fc76a5a5` |
| Row counts at stop | `~/reachy-backups/rowcounts-before-034.txt` (meetings 2, documents 0, tasks 2, notes 3) |
| Images | `reachy-rollback/{companion-core,reachy-hub,coding-agent-service,migrate,document-worker}:pre-034` |
| Schema rollback | `deploy/homelab/rollback-034.sql` in one transaction with the services stopped (drops only the five Phase 53 tables; revision returns to `033_calendar_feed`), then tag the `pre-034` images back to `latest` and `up -d --no-build --no-deps` the four services (the document worker with `--profile documents`) |
| Status | **Not invoked.** Keep all of it until the owner accepts the deployment. |

## Phase 48 boundary (a gap, stated plainly)

Core was recreated, so a new Phase 48 segment starts at 07:44:07 UTC. Reading the previous segment's capture counters from the container was denied by the permission classifier (the same as in the [Home dashboard deployment](home-dashboard-deployment-2026-10-14.md)), so the counters of the segment that ended at the graceful stop at 07:39:56 were **not saved**. `~/reachy-backups/phase48-boundary-034/` holds only the stop and start times.

## Verification

- Schema: `034_meeting_multimodal`; the five tables exist (`meeting_document_links`, `meeting_multimodal_runs`, `meeting_slide_alignments`, `meeting_slide_reviews`, `meeting_multimodal_items`) with 0 rows.
- Data: meetings 2, tasks 2, notes 3, as before.
- Services: all four running on the new image IDs; the document worker reports healthy; no traceback or error in the first minutes of any of the four logs; core logs show a clean start.
- Flags in core: `MEETING_MULTIMODAL_ENABLED=false`, `MEETING_ANALYSIS_ENABLED=true`, `DOCUMENT_LIBRARY_ENABLED=true` (unchanged).
- Hub: `/web/` serves (200); the Phase 53 routes exist and answer 401 without an owner session (they would be 404 if absent); `/status` answers 401 unauthenticated as before.
- Worker: the new image knows the 17 file types.

**Not verified:** core's own Phase 53 route behaviour with the flag off (my token probe returned 401 on every core path, so it proved nothing about 404s; the flag is read once at start and the routes are not installed when it is false, as the in-process tests show), a browser session as the owner, the existing meeting, task and note screens in a browser, Android, the robot, Telegram, the voice path, a real PPTX upload to the production worker. No regression was observed.

## Next, each needing separate authorization

Merging the branch to `main`; enabling `MEETING_MULTIMODAL_ENABLED` (set it in `deploy/homelab/.env` and recreate core only; roll back by setting it false); the owner's acceptance on their own deck and meeting. Release the `pre-034` images and the extra dump only after the owner accepts.

## Activation (2026-10-14, owner: "turn the feature on")

`MEETING_MULTIMODAL_ENABLED=true` set in `deploy/homelab/.env` (backup `.env.bak-before-multimodal`, kept beside it) and **only core recreated** (`up -d --no-build --no-deps --force-recreate companion-core`, same image `e92463cc8334`; hub, coding-agent, worker and the database untouched). Preconditions: no alarm due within 15 minutes. Core restarted at 07:57:48 UTC (process start 2026-10-14T07:57:50.102595584Z); a new Phase 48 segment begins there, and the previous segment's counters were again not saved (same permission denial).

Verified from inside core with the service token: `/meeting-multimodal/config` → `{"enabled":true}`, `/meetings` and `/meeting-analysis/config` answer as before; core env shows `MEETING_MULTIMODAL_ENABLED=true`, `DOCUMENT_LIBRARY_ENABLED=true`; clean startup, no error in the log. **Not verified:** the owner's browser session (Documents tab, slide cards, Q&A, analysis) and a real attach on production data; those are the owner's acceptance. **Rollback:** set the flag to false (or restore the `.env` backup) and recreate core; the tables and any attachments stay but are unreachable until it is on again.
