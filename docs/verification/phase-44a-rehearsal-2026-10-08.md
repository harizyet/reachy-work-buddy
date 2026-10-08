# Phase 44A migration 026: preflight and rehearsal, 2026-10-08

Evidence for the [deployment runbook](../deployment.md#applying-migration-026-phase-44a---runbook-prepared-and-not-executed). This is the preparation and the rehearsal only. **The live services were not stopped and the live database was not changed.** The only things done to production were read-only: queries, a `pg_dump` snapshot through `docker exec`, a reading of the model manager's state, and counting log lines. Pinned commit: `5d64d82` (pushed; `origin/main` equals it; the images were built from a clean tree at that commit).

## Push

`origin/main` was `ad69d1a`, an ancestor of `HEAD`; the three commits were pushed without force (`ad69d1a..5d64d82`) and `origin/main` now equals `HEAD`. The repository is public; the secret scan covered the change set before the push.

## Live preflight (read-only)

| Check | Result |
|---|---|
| Database revision | `025_meeting_description` |
| Size and rows | 10 MB, 39 public tables; `memories`, `document_chunks`, `notes`, `tasks`, `reminders` are empty; 1 meeting (complete), 4 secrets, 7 alarms, 5 web chats, 7 action receipts |
| Alarms and reminders | none scheduled-and-enabled alarm or pending reminder is overdue or due within 45 minutes |
| Meetings in flight | none (1 complete) |
| Deep-review job | the model manager reports `ready_t1`, no transition in progress, no error |
| Voice and meeting activity | no voice lines in the hub log and no meeting or deep lines in the core log in the last 15 minutes. The app's own robot state needs the owner's session, so "robot idle" is **re-checked at go time**, not established here |
| Postgres | image `pgvector/pgvector:pg16`, 16.15 |
| Disk | 274 GB free on `/`; the backup directory is 1.8 MB |

## Build

`docker compose -p reachy-44a-rehearsal build migrate companion-core reachy-hub coding-agent-service` (a separate project name, so production tags are untouched) completed with no errors. The production images are unchanged: `reachy-homelab-reachy-hub` `46f0a08e2e08`, `-companion-core` `cc5727d76bae`, `-migrate` `f85fb038da2c`, `-coding-agent-service` `784875d60f3a`.

## Rehearsal on an isolated restored copy

Copy: a throwaway production-image Postgres on an `--internal` Docker network (no egress), no published ports, random password; files in a 0700 directory at 0600; the production keyring mounted read-only into the migrate and core containers and never copied.

| Step | Result |
|---|---|
| Snapshot | per-table counts equal before and after the dump (39 tables); dump 108,068 bytes |
| Restore | revision `025_meeting_description`; counts identical to production for every table |
| Migrate #1 (new image, production keyring) | success in 1.7 s; revision `026_source_sensitivity` |
| Migrate #2 | success, no-op; every stored credential decrypts |
| Schema | the nine columns present with `'work-private'` defaults and no scope default; the check constraint rejects `'secret'` (checked by a direct insert) |
| Backfill and counts | the only populated table among the five is `meetings` (1 row): `work-private`, scope unchanged; all other counts identical to the snapshot |
| New core against the migrated copy | healthy; no errors in its log; lists the meeting; create with `sensitive` and scope returns them; an edit with only text keeps them; an edit that carries `sensitivity` returns 422; an invalid value returns 422; an old-style create gets `work-private` and no scope; a reminder keeps `sensitive`. The Ossie export validates inside the image (`jsonschema` 4.26.0). The hub image imports with the new create bodies |
| Old (current production) core against the 026 copy | refuses to start (revision gate), as intended |
| Rollback: restore the pre-upgrade dump over the copy | revision 025; counts identical to production; `sensitivity` column gone; the smoke-test rows gone |
| Old core against the restored copy | starts and serves the meeting |
| New core against the restored 025 copy | refuses until migrated |
| Migrate again after the rollback | success; revision 026 |

One rehearsal slip, harmless and now in the runbook: the first migrate attempt ran the image without a command, which starts the core web application (the image's default); it stopped at "ACCOUNTS_SERVICE_TOKEN is required" before touching the database (revision still 025). Compose passes the migration command explicitly, and the runbook now says to pass it.

## Disposal

Containers removed with `-v`, the internal network removed, every file in the rehearsal directory shredded (`shred -u -z`) and the directory removed, the four rehearsal image tags removed. Afterwards no container or network named for the rehearsal exists, `~/reachy-backups` holds no rehearsal file, and all nine `reachy-homelab-*` containers are still running unchanged.

## Alarm and reminder continuity

Alarms and reminders are claim-once rows (`due_at <= now` and not yet fired or notified), polled by the hub (alarms every 5 s, reminders every minute). Nothing is dropped during downtime: whatever fell due is claimed and delivered on the first poll after the hub returns, late and **with no staleness cutoff**. A repeating alarm rings late and is re-armed. Two gaps remain and are handled by timing: an alarm claimed but not yet delivered when the hub is killed is lost, and a long outage would ring old alarms at restart. This is accepted for the migration and recorded as technical debt in HANDOVER, not fixed in Phase 44A. The runbook therefore requires no alarm or reminder due within 45 minutes, stops core before hub, and adds a continuity report after start.

## What the rehearsal did not cover

Production's tables are nearly empty, so the row backfill on populated `notes`, `tasks`, `document_chunks` and `reminders` was proven by the seeded disposable-database tests ([Phase 44A record](phase-44a-2026-10-08.md)), not by this copy. The hub was import-checked, not run. Document ingestion (it needs the embedding model) was not run on the copy. The robot, Telegram, voice, the phone and the web UI are covered only by the live post-deployment smoke tests.

## Go/no-go

Rehearsal passed. The owner approved the deployment in principle on 2026-10-08, subject to a chosen quiet window and to repeating every Stage 0 check, including robot idle, immediately before live downtime. The pinned deployment commit is `5d64d82`; this record and the runbook update are a later documentation-only commit and are not part of what is deployed.
