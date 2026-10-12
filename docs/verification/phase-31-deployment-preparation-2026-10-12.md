# Phase 31 controlled deployment: preparation and pre-deployment checks (2026-10-12)

**Status: prepared and verified; NOT deployed.** The production database is at `031_documents`, core, hub and coding-agent run the images listed below, and `MEETING_ANALYSIS_ENABLED` is unset (off). Nothing in production was stopped, restarted, migrated, changed or enabled while preparing. Stages 4 to 7 wait for the owner's deployment approval.

## 1. Branch, migration and frozen files

| Check | Result |
|---|---|
| Branch / tree | `phase-31-meeting-analysis`, clean; images built from a clean `git worktree` of commit `e6b24d4` (`../reachy-work-buddy-deploy-032`, 0 modified files). After that one more commit adds only the Compose pass-through below and docs. |
| Migration | One Alembic head, `032_meeting_analysis`, `down_revision = 031_documents`; `SCHEMA_REVISION` is `032_meeting_analysis`. Adds two tables and one trigger function calling the existing `knowledge_enqueue`; no foreign keys; changes no existing table. |
| Frozen Phase 48 files, `memory/`, `benchmarks/`, `notepad_processing/` | No diff against `main`. **Stronger check:** the sha256 of all 53 `.py` files under `knowledge/`, `memory/` and `notepad_processing/` in the branch were compared with the files inside the **running production core container**: 51 identical; the 2 that differ are the intended, non-frozen `knowledge/runtime.py` and `knowledge/sources.py`. |
| Only code files that differ from production | `app.py`, `knowledge/runtime.py`, `knowledge/sources.py`, `meetings/outputs.py`, `shared/database.py`, hub `app.py`, new `meeting_analysis/`, `meeting_analysis.py` (hub), the 032 migration, `rollback-032.sql`, the shared route constants, and web files (hub image). |

## 2. Backup and rollback images

- **Rollback images, tagged by immutable ID and verified equal to the running containers:** `reachy-rollback/companion-core:pre-032` = `sha256:92a81c773dd8…`, `reachy-rollback/reachy-hub:pre-032` = `d438f87dc181…`, `reachy-rollback/coding-agent-service:pre-032` = `44b6fa237c0e…`, `reachy-rollback/migrate:pre-032` = `4498cc0870b8…`.
- **Prepared dump (live, read-only `pg_dump -Fc`):** `~/reachy-backups/reachy-prepared-before-032-20261012-213302.dump`, 324,014 bytes, mode 0600, sha256 prefix `2adb17fe1ed8f7ab`, 51 table-data entries. **Restore verified** into a throwaway `pgvector/pgvector:pg16` container with `--network none` and no published port: revision `031_documents`, per-table counts identical to production for all 51 tables (`~/reachy-backups/rowcounts-before-032.txt`). This is the preparation dump; the rollback point is a second dump taken with the three writers stopped, as in the 030 deployment.
- Free disk 133 GB of 937 GB. Existing backups and document-source archives are untouched.

## 3. Rehearsal on the restored copy, with the real images (all disposable, then removed)

Images built under a separate project name (`reachy-p31-rehearsal`; production tags untouched): core `484b1495d55c`, hub `af30ec4c0a1e`, coding-agent `9c20355f64cc`, migrate `f0e063e40124`. On the copy of production data:

- Migrate image run twice: first applies 032, second is a no-op; revision `032_meeting_analysis`; the two tables and the one trigger exist; no foreign keys; **all 51 pre-existing tables have identical counts**; `knowledge_outbox` untouched (0 rows).
- Revision gate: the production (`pre-032`) core and hub **refuse** the 032 copy, the new core and hub **accept** it, which is why core, hub and coding-agent deploy together.
- `rollback-032.sql` in one transaction: counts identical again, both tables and the function gone, revision `031_documents`; the `pre-032` images accept it and the new images refuse it.
- The new core image booted against the migrated copy with the analysis flag off: `/health` ok; `/meeting-analysis/config` **404** (nothing built, routes absent); `/meetings`, `/notes`, `/tasks`, `/reminders` returned the copied data.
- Rehearsal containers, network, temporary password and token files removed; the rehearsal images are kept as the exact tested bits to retag at deployment.

## 4. Pre-deployment state (read-only, 21:3x local on 2026-10-12)

Schema `031_documents`; no alarm and no reminder due in the next 30 minutes; the one meeting is `complete`; counts: memories 2, notes 3, tasks 2, reminders 0, meetings 1, knowledge_items 85, documents 1, document_chunks 0. Running image IDs as above. Core started `2026-10-12T07:42:51Z`; Phase 48 capture counters of that segment right now `{"attempted":21,"excluded_attachment":11,"no_match":7,"excluded_handled":3}` (read again immediately before the stop). Production flags: indexing, retrieval, selective shadow, candidates and capture, Notepad processing and the document library are on; `MEETING_ANALYSIS_ENABLED` is not set. The model manager is not running (started and stopped by hand for the model diagnostic); the production vLLM is back on the 7B, healthy.

## 5. Exact production changes the deployment makes

1. Schema `031_documents` to `032_meeting_analysis`: two new empty tables and one trigger function. No existing data is modified.
2. Images: core, hub, coding-agent recreated from `e6b24d4` builds (`484b1495d55c`, `af30ec4c0a1e`, `9c20355f64cc`); the migrate image is the new core build. Downtime about 6 to 10 minutes, mostly waiting for PgBouncer's idle connections as in the 030 deployment; web, Telegram, voice, alarm delivery and reminder pushes pause meanwhile (nothing due in the window).
3. Compose: `MEETING_ANALYSIS_ENABLED: ${MEETING_ANALYSIS_ENABLED:-false}` added to core. Result: the flag is explicitly **false**, no routes, no runner, no table read, no index entries from analysis.
4. **One change visible outside the feature, for the owner to accept or reject:** speaker labels such as `speaker_0` now display as "Speaker 1" in meeting views and, in the Phase 44 index, in the speaker field and match text of the one meeting's 78 transcript segments. The index rewrites those rows at the next reconcile (hourly) or earlier; it changes what a retrieved meeting segment says, not the retrieval code (the Phase 48 frozen files are unchanged). Alternative: revert that one function, rebuild and retest before deploying.
5. Phase 48: a new segment ("cohort") starts at the new core start. The old segment ends at the graceful stop; its counters and the selective-shadow file copy are saved first.
6. Not touched: PostgreSQL, PgBouncer, vLLM, the model manager, Caddy, SearXNG, router, transcription, diarization, document worker, the robot, all feature flags.

## 6. Procedure after approval (stages 4 to 7)

Run from `deploy/homelab` with `-p reachy-homelab --env-file .env`, `SEARXNG_SECRET_KEY` exported from its 0600 file and never printed.
1. Re-check preconditions (no alarm or reminder due within 30 minutes, meeting not mid-pipeline, no deep-review job, robot idle, no voice conversation). Read the capture counters.
2. Retag the tested images (`reachy-p31-rehearsal-*`) to the production names (`p31-e6b24d4` and `latest`); verify the IDs.
3. `docker stop -t 30` core, then hub and coding-agent; copy the selective-shadow file to `~/reachy-backups/phase48-boundary-031/`; take the **stop-time dump** (verify by restore with `--network none`), row counts.
4. Wait for PgBouncer's idle connections to close; run the migrate image; confirm revision 032.
5. `up -d --no-build --no-deps` core, hub, coding-agent. Check health, image IDs, no tracebacks in 5 minutes of logs.
6. Verify (stage 5): revision, counts identical, `/meeting-analysis/config` 404 through core and `{"enabled": false}` through the hub, meetings list and detail, a note read, tasks list, a reminder read, a conversation turn and a knowledge retrieval turn through the hub (no durable write beyond what an ordinary question makes), Notepad processing state, document library list.
7. Write the deployment record with the cohort boundary (old segment counters and time, new segment start), the dump hash, image IDs and what was and was not verified.

## 7. Abort and rollback

Any failed precondition or rehearsal step stops the deployment before anything is stopped. After the stop: if migration fails, 032 is transactional and the old images start unchanged; if the new services fail health, stop them, run `rollback-032.sql`, retag the `pre-032` images and start them, and restore the stop-time dump only if the schema or data cannot be trusted. Release the `pre-032` images only after the owner accepts; keep the latest verified dumps.
