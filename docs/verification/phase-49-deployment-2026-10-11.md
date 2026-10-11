# Phase 49 deployment: migration 029 and coordinated cutover (2026-10-11)

Owner authorization: migration 029 and the Phase 49 cutover only, with the Phase 48 **boundary option**, a fresh backup taken with the writers stopped, `reachy-rollback/*:pre-049` tags before any change, and **`NOTEPAD_PROCESSING_ENABLED=false`**. Code: commit `3e17ad3`, images built from a clean `git worktree` of that commit (0 modified files). Engineering evidence: [Phase 49 verification record](phase-49-notepad-processing-2026-10-11.md). Rehearsal done the same day on a restored copy of this database (throwaway container on an `--internal` network, no ports, shredded afterwards): dump and restore with equal counts; migrate 029 twice; the live core image refuses a 029 database and the Phase 49 code accepts it; `rollback-029.sql` returns it to 028 with counts equal; restoring the pre-upgrade dump over a migrated copy gives 028 and can be re-migrated; the Phase 49 core booted on the copy with the flag off (Phase 49 routes 404) and on (200). **Result: deployed, all checks passed, feature OFF, no production note processed or modified, no task or reminder created.**

## Starting and ending state

| | Before | After |
|---|---|---|
| Schema revision | `028_memory_candidates` | `029_notepad_processing` |
| core image | `027ed2d6437e` (`48b-counters-9c8214a`, started 2026-10-10 15:02:31 UTC) | `cbf13868a429` (`p49-3e17ad3`, started 06:38:44 UTC) |
| hub image | `0e5f42fb8504` (`44-ca21d72`) | `eac6a24e3c6f` (`p49-3e17ad3`) |
| coding-agent image | `dc202e9038ed` (`44-ca21d72`) | `3d48b066b1bf` (`p49-3e17ad3`) |
| migrate image | `966642fe0c5a` | the core image `cbf13868a429` (as in earlier deployments) |
| Row counts (notes 3, tasks 0, reminders 0, meetings 1, memories 1, alarms 9, receipts 11, knowledge_items 83, candidates 0, llm_config 1, secrets 4) | stop snapshot | **identical** after migration and start |
| Notepad tables | none | 5 tables, 16 indexes, all empty |

Not touched (start times unchanged): PostgreSQL, PgBouncer, vLLM, Caddy, SearXNG, semantic router, transcription, diarization, the model manager and the robot. All Phase 48 flags are as before (`KNOWLEDGE_INDEXING/RETRIEVAL/SELECTIVE_SHADOW=true`, `MEMORY_CANDIDATES` and `_CAPTURE=true`); selective answering is still absent. New: `NOTEPAD_PROCESSING_ENABLED=false`, `NOTEPAD_PROCESSING_CONCURRENCY=1`.

## Timeline (UTC, 2026-10-11; host +08:00)

| Time | Step |
|---|---|
| 06:32:35 | Preflight: no alarm or reminder due in 45 minutes (no scheduled alarm at all), one `complete` meeting, no pending confirmation, 193 GB free, key files present (mode 0600, not touched) |
| 06:33 to 06:34 | Images built from the clean worktree (core, hub, coding-agent; before anything stopped); frozen capture-file hashes and revision 029 confirmed inside the new core image |
| 06:34:38 | `reachy-rollback/{companion-core,reachy-hub,coding-agent-service,migrate}:pre-049` created and verified against the running image ids |
| 06:34:45 | Phase 48 pre-boundary capture (below) |
| **06:34:54** | **core stopped gracefully (`docker stop -t 30`: exit 0, not OOM-killed, finished at once)**; hub and coding-agent stopped 06:35:01 |
| 06:35:34 | Fresh dump with all writers stopped, verified (below) |
| 06:35:43 | Dump restored into a throwaway container (internal network, no ports): revision 028 and all 12 row counts equal; container, network and password removed |
| 06:35:58 to 06:38:17 | Waited for PgBouncer's own idle pooled connection to close (the migration refuses while any client backend exists; 300 s idle timeout). PgBouncer was **not** restarted (an earlier deployment did restart it; waiting avoided touching it) |
| 06:38:23 | First migrate attempt failed to start: `SEARXNG_SECRET_KEY` missing from the manual Compose environment (documented requirement). Nothing ran; revision still 028 |
| 06:38:32 to :35 | `SEARXNG_SECRET_KEY` exported from its 0600 file; migrate ran: **029 applied** |
| 06:38:41 to :44 | `docker compose up -d --no-build --no-deps companion-core reachy-hub coding-agent-service` |
| **06:38:49** | core and hub answering `/health` |

**Downtime:** core 3 min 55 s (06:34:54 to 06:38:49), hub 3 min 48 s, coding-agent about the same. About 2 min 19 s of that was the deliberate wait for PgBouncer's idle connection; the migration itself took 3 s and the start 8 s. No alarm, reminder or meeting was affected (none was due; `alarms`/`reminders` fired since 06:34: 0, none left scheduled in the past).

## Phase 48 boundary (option chosen by the owner)

Both trial logs now carry the boundary row ([48B capture trial](phase-48b-capture-trial-2026-10-10.md), [48F selective shadow](phase-48f-selective-shadow-2026-10-10.md)). **Cohort A** is everything before 06:34:54 UTC, **cohort B** everything after 06:38:44 UTC. They are not to be summed as one uninterrupted trial; the image id, the core commit and the answer path for named-note questions differ between them.

| | Cohort A (closed 06:34:54) | Cohort B (opens 06:38:44) |
|---|---|---|
| core image / commit | `027ed2d6437e` / `9c8214a` (capture image `15ce11cf8ad9` / `d899e14` before 15:02 on 2026-10-10) | `cbf13868a429` / `3e17ad3` |
| capture counters (in-memory, last process from 2026-10-10 15:02:32) | `{"attempted":4,"no_match":2,"excluded_handled":2}` | starts at 0 |
| durable capture report since 14:06 | 0 proposed, 0 candidate rows, 0 suppressions, 0 memories from candidates | candidate rows still 0 |
| selective shadow file | read after the graceful stop: **admitted 6, processed_ok 6, all text, latency <=5 ms** (cumulative since the window opened 2026-10-10 14:56, which includes the two 48F verification probes), file sha256 prefix `db5f9bf741c2d6cf`, 799 bytes; copy kept at `~/reachy-backups/phase48-boundary-049/selective-shadow.pre-049.jsonl` (0600) | the same file continues to be appended by the new process; read it by subtracting the preserved cohort A copy and the probes below |
| Frozen items | capture files `candidate_service.py`, `candidate_rules.py`, `candidates.py`, `candidate_routes.py` match the trial log's sha256 values (also inside the new image); `knowledge/` router, registry, retrieval, evidence rules and answerer unchanged since `9c8214a` (the dev8/10/12/14 freeze tests pass) | same |

**Deployment probes in cohort B (not owner usage, to be subtracted):** my verification turns on channel `probe-049` between 06:39:23 and 06:39:45 UTC: 20 turns (6 API probes, then 14 for the 44H matrix). Capture classified all 20 `excluded_channel` (`{"attempted":20,"excluded_channel":20}`), so they reached no candidate logic; the shadow telemetry (modality text/voice only, no channel) may include them in its first cohort-B flush.

**Behaviour change inside cohort B to bear in mind:** the deployed core includes the grounding fix `14403a1`. A question that names a note or meeting ("What did I write in the note called …") is now answered by the record handler (stored text or a fixed not-found reply) instead of falling to the generic model, and a reply that credits "your notes" without a supplied record is withheld. The 48F shadow still classifies the same text with the same frozen classifier.

## Backup and rollback inventory

| Item | Value |
|---|---|
| **Pre-deployment dump** (writers stopped, `pg_dump -Fc`) | `~/reachy-backups/reachy-before-phase49-20261011-143534.dump`, 291,910 bytes, mode 0600, sha256 `964163c41ada3be895ac5bc1f360fed9c0678888936cf93e91ed9a4f3c105100`. `pg_restore --list` shows 44 table-data entries including `alembic_version`, `meetings`, `memories`, `notes`. Restore into a throwaway container reproduced revision 028 and all counts. **Keep until the owner accepts the deployment.** |
| Image tags | `reachy-rollback/companion-core:pre-049` = `027ed2d6437e`, `reachy-rollback/reachy-hub:pre-049` = `0e5f42fb8504`, `reachy-rollback/coding-agent-service:pre-049` = `dc202e9038ed`, `reachy-rollback/migrate:pre-049` = `966642fe0c5a` (each verified equal to the image that was running). Also kept: `…:48b-counters-9c8214a`, `…:44-ca21d72` version tags; new images also tagged `:p49-3e17ad3` |
| Schema rollback | `deploy/homelab/rollback-029.sql` (verified in rehearsal on a restored copy of this database: revision back to 028, all row counts equal, live core image accepts it again, the 029 code refuses it) |
| Cohort A evidence | `~/reachy-backups/phase48-boundary-049/selective-shadow.pre-049.jsonl` (0600) plus this record |
| Rehearsal copies | shredded and removed before the deployment (directory, network, containers) |
| Key files | untouched; `.env.secret-keys.json` and `.env.coding-agent-secret-key.json` still need the separate secure copy that earlier deployments required (not changed by this deployment) |

**To roll back** (a full rollback loses anything written after 06:38:44): stop core, then hub and coding-agent; `docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < deploy/homelab/rollback-029.sql` (final line must print `028_memory_candidates`); wait for PgBouncer's idle connection or restart it with the applications stopped; `docker tag reachy-rollback/companion-core:pre-049 reachy-homelab-companion-core:latest` (likewise hub, coding-agent; migrate), then `docker compose -p reachy-homelab --env-file .env up -d --no-build --no-deps companion-core reachy-hub coding-agent-service` (with `SEARXNG_SECRET_KEY` exported). Alternative: restore the dump with `pg_restore --clean --if-exists --no-owner`. No Postgres volume is ever deleted.

## Verification results

| Check | Result |
|---|---|
| Revision, tables, indexes | `029_notepad_processing`; `notepad_jobs`, `notepad_proposals`, `notepad_proposal_notes`, `notepad_provenance`, `note_meeting_links`; unique partial indexes `notepad_jobs_one_active_per_note`, `notepad_proposals_source_key`; all tables empty |
| Image identity, restarts, health | as in the table above; 0 restarts; core and hub `/health` 200 |
| Logs since start | core, hub, coding-agent: 0 tracebacks, exceptions or critical lines |
| Reads through core (service token) | `/tasks` 0, `/reminders` 0, `/notes` 3, `/meetings` 1, `/alarms` 9, `/memories` 0: all 200 |
| Chat | "What is the capital of France?" answered by the 7B; "what are my tasks?" -> "You have no open tasks." |
| 44H action boundary | 14 requests (7 phrases, text and voice): 10 x "I can't perform that action here, so I haven't made any changes.", 4 x "There is nothing waiting for your confirmation, and I haven't done anything."; row counts of 10 tables identical before and after; no hub log lines (the robot was not called) |
| Phase 49 OFF | core `/notepad-processing/config`, `/notepad-proposals`, `POST /notes/{id}/processing`, `/notes/{id}/meeting-links`: 404; the same routes without a service token: 401 |
| Owner-only / CSRF without an owner login | hub: anonymous and bearer-token requests refused (401) on all 9 Phase 49 routes, with and without the CSRF header; `/web/` and `/health` 200. The CSRF check with an owner session is covered by the hub tests (needs the owner's password, not exercised in production) |
| Grounding fix present | "What did I write in the note called 'zz probe 049 nonexistent'?" -> `I couldn't find a note or meeting called "zz probe 049 nonexistent".` |
| PgBouncer compatibility | The deployed Phase 49 store code, using the production `DATABASE_URL` through PgBouncer (`pgbouncer:6432`, transaction pooling, `DB_PREPARE_THRESHOLD=off`), ran every statement shape the feature uses on the empty tables (SELECTs, the `FOR UPDATE SKIP LOCKED` claim, `FOR UPDATE` inside a transaction, `ANY(array)` hydrate, `DELETE … RETURNING`) plus 30 concurrent pooled operations: all succeeded; no rows written. Connection settings were not changed |
| Existing note | "My Task for next week": not read through any Phase 49 path, not processed, not modified (`updated_at` 2026-10-09 02:45:24 UTC unchanged; no job, proposal or link rows exist anywhere) |
| Created records | none: tasks 0, reminders 0, notepad rows 0; the 20 probe turns changed no store |

## Residue and follow-ups

* The 20 probe turns are held only in the conversation store's memory and (possibly) the first cohort-B shadow flush's counters; they wrote no persistent row.
* Lessons for the runbook: manual Compose needs `SEARXNG_SECRET_KEY`, and the migrate step waits for PgBouncer's 300 s idle timeout unless PgBouncer is restarted with the applications stopped.
* Not done by design: enabling processing, indexing/retrieval/answering changes, the owner's browser and phone smoke test, processing of any production note. A separate owner approval is needed for each.
* Deployment is not yet accepted: keep the dump and the `pre-049` tags until the owner accepts.
