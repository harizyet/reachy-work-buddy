# Phase 44B production deployment, 2026-10-08

Migration `026_source_sensitivity` to `027_knowledge_index`, applied to the homelab under owner decision D13 (supervised, `KNOWLEDGE_INDEXING_ENABLED=false`, physical robot acceptance deferred), following the [026 runbook](../deployment.md#applying-migration-026-phase-44a---runbook-prepared-and-not-executed) after the [rehearsal](phase-44b-rehearsal-2026-10-08.md). **Software deployment passed. Knowledge indexing and retrieval are off. The robot acceptance gate is pending, not waived.** Times are Singapore time (UTC+8).

## What was deployed

Code: the pinned commit `5f7f3ab` (main, pushed). The shared checkout holds another session's uncommitted Android and hub edits, so the images were built from a clean `git worktree` of `5f7f3ab` (zero modified files), with plain `docker build` from the repository root using each service's Dockerfile and tagged as the compose image names; the worktree was removed afterwards. `git diff --stat bdc9efd 5f7f3ab -- services shared deploy` (excluding tests and benchmarks) shows only the reviewed 44B/44D changes: the knowledge package, migration 027, store additions, `shared/database.py` (`SCHEMA_REVISION`), `rollback-027.sql`, and the compose flag. New images: migrate `9f3f1e256dd4`, core `04fb9950447b`, hub `78176d66fc1a`, coding-agent `bd150ee12f07`; core and hub report schema revision `027_knowledge_index`. Not touched: PostgreSQL (dry run and the live start both showed it "Running"), vLLM, the model manager, the sidecars, Caddy, the robot host.

## Timeline and downtime

| Time | Step |
|---|---|
| 13:17 | Preflight |
| 13:19:29 | Core stopped, then hub and coding-agent (all stopped 13:19:31); 0 database clients |
| 13:19:37 | Dump taken and verified by isolated restore; container snapshots taken |
| 13:20:32 | Migration (exit 0, a few seconds) |
| 13:20:38 | `up -d --no-build` for core, hub and coding-agent |
| 13:20:46 | Hub and core healthy |

**Downtime of core, hub and coding-agent: about 77 seconds.** The reminder lateness seen afterwards is a reliability issue, not a deployment fault (smoke test 10).

## Preflight

Pinned commit `5f7f3ab` equals the pushed head; its deployable diff from the 026 deployment base is reviewed code only. Database at `026_source_sensitivity`. No scheduled alarm or pending reminder due within 45 minutes; the one meeting `complete`; 265 GB free; core, hub and coding-agent healthy; `KNOWLEDGE_INDEXING_ENABLED` not set in the running (026-era) core. Start-up dry run: PostgreSQL not recreated. Rehearsal of the same migration on a restored production copy was already recorded.

## Backup and restore check

`~/reachy-backups/reachy-before-phase44b-20261008-131937.dump`, 102,933 bytes, mode 0600, sha256 `4e3a4eecc4ed738e...`, taken after the writers were stopped. `pg_restore --list` shows 39 table-data entries. Restored into a throwaway container on an internal network with no ports: revision 026 and identical row counts for all 39 tables against the at-stop counts; container and network removed. The keyring files still have no off-host copy (open from 44A).

## Rollback readiness

Images tagged `reachy-rollback/{migrate,companion-core,reachy-hub,coding-agent-service}:026` (`cb4438e68a05`, `8053200d800c`, `b4942102a147`, `da55768ae7f8`, the images running before this deployment) and container snapshots `:026-container` (`aff12742cd26`, `c3810db68117`, `561aa28ee1d1`). Rollback is `deploy/homelab/rollback-027.sql` with core, hub and coding-agent stopped (027 holds only derived data and loses nothing authoritative), then the `:026` images; a full restore of the dump needs that SQL first. Keep the dump and the tags until the owner accepts the deployment; the `:025` tags and the 44A dump are also still present.

## Smoke tests

| # | Check | Result |
|---|---|---|
| 1 | Revision | `027_knowledge_index` |
| 2 | Objects | `knowledge_items` and `knowledge_outbox` exist; 6 triggers (memories, notes, tasks, reminders, document chunks, meetings) |
| 3 | Counts | all 39 pre-existing tables' counts identical to the at-stop snapshot, before and after the smoke tests |
| 4 | Indexing off | core env `KNOWLEDGE_INDEXING_ENABLED=false`; `knowledge_items` has 0 rows throughout; no indexing worker lines in core logs |
| 5 | Backfill | `knowledge_outbox` holds one row (`meeting`, the single existing record) queued by the migration |
| 6 | Health and logs | hub and core `ok`; zero error, exception or traceback lines in core, hub and coding-agent logs for the first eight minutes |
| 7 | Web UI and bearer API | `/hub/ui/` serves (200); owner-bearer API calls work |
| 8 | Trigger firing | a to-do created through the hub queued exactly one outbox row for it; its edit and delete queued more; no index row was ever written |
| 9 | Classification round-trip | created as `sensitive` with scope `smoke`; a text edit kept both; an edit carrying `sensitivity` returned 422; an invalid value returned 422 |
| 10 | Reminder continuity | a reminder due in two minutes (13:23:47) was claimed at 13:24:44, 57 s late. Analysis afterwards: the hub's reminder loop sleeps first and then polls once every 60 s (`reminder_notify_loop`, interval `coding_agent_notify_interval`), and the hub started at about 13:20:41, so its polls fell at :41 each minute and the next one after 13:23:47 was 13:24:41. That is the poll cadence, not the voice-provider warm-up (which I first suspected; the warm-up runs in a separate thread task). Recorded as a [reliability issue](../../HANDOVER.md#open-unverified-or-worth-watching). No alarm fired and none is scheduled-and-overdue (0 and 0). Telegram receipt of that push is not confirmed by me |
| 11 | Command turn through core | `/conversation` with `/help` returned 200 (1,069 characters). A model-backed turn was not sent |
| 12 | Robot | not tested; `nano-1` is still listed by the hub; nothing was sent to the robot |

All smoke-test records were removed: the to-do and reminder through the API, then the three outbox rows they queued (task, reminder) by SQL; tasks, notes and reminders are 0 again, and the outbox holds only the migration's meeting row. The throwaway verification container and network are gone.

## Acceptance

- **Software deployment: complete and passed**: revision 027, indexing and retrieval off, counts identical, no errors, classification working through core and hub.
- **Pending, not waived:** physical robot connectivity, movement and voice; a browser pass through the web UI; Telegram receipt of the smoke reminder.
- Not done by design: no indexing, no retrieval, no 44E, no promotion of B1a or B1b; the contention test (D14) is prepared and not run ([plan](phase-44b-contention-test-plan-2026-10-08.md)).
