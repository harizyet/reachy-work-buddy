# Brain provenance edges: production deployment (2026-10-11)

Owner-approved, core-only: commit `d34ad51` ([change and tests](phase-49-brain-provenance-2026-10-11.md)). No migration, no frontend or hub rebuild, no indexing or feature change. **Result: deployed, every check passed, no record changed.**

## Before

| | |
|---|---|
| Commit / build inputs | `d34ad51` = `origin/main`; image built from a clean `git worktree` (0 modified files). Core-affecting delta from the running image's commit `3e17ad3`: `app.py`, `brain.py`, `notepad_processing/store.py`, `notepad_processing/postgres_store.py` (plus tests) |
| Schema | `029_notepad_processing` |
| Running core | image `cbf13868a429` (`p49-3e17ad3`), started 2026-10-11 07:27:07 UTC, 0 restarts, `/health` 200 |
| Flags (kept as they were) | `KNOWLEDGE_INDEXING/RETRIEVAL/SELECTIVE_SHADOW=true` (log `/data/shadow-router/selective-shadow.jsonl`), `MEMORY_CANDIDATES` and `_CAPTURE=true`, `NOTEPAD_PROCESSING_ENABLED=true`, concurrency 1; selective answering absent |
| Quiet window | no alarm or reminder due in 45 minutes, no meeting processing |
| Record counts | notes 3, tasks 2, reminders 0, meetings 1, memories 1, alarms 9, receipts 13, knowledge_items 85, candidates 0, notepad jobs 2, proposals 2, provenance 2, links 0 |
| Rollback image | `reachy-rollback/companion-core:pre-brain` = `cbf13868a429` (verified equal to the running image before the stop); older tags (`pre-049` = `027ed2d6437e`, `48b-counters-9c8214a`, `p49-3e17ad3`) and the pre-049 dump are still kept |
| New image | `1c3290c4d993` (`p49-d34ad51`); the four frozen Phase 48 capture files inside it match the trial log's hashes; schema head 029 |

## Phase 48 boundary 3 (cohorts kept separate)

Cohort C (2026-10-11 07:27:07 to 10:08:47 UTC, image `cbf13868a429`) is closed and cohort D opens at 10:08:51 UTC (image `1c3290c4d993`). Read before the stop: capture counters `{"attempted":6,"excluded_channel":6}` (my six probes; durable report 0 rows, no candidate rows), and after the graceful stop (10:08:47, exit 0, not OOM-killed) the shadow telemetry flushed to cumulative `admitted 32, processed_ok 32` = cohort A's 6 plus the 20 probes of cohort B plus exactly the 6 probes of cohort C, so **cohort C also contains no owner usage** (copy `~/reachy-backups/phase48-boundary-049/selective-shadow.cohortC-end.jsonl`, sha256 prefix `77d160f8c4c3ef44`). Cohort D so far holds 5 verification probes (below), subtracted as non-owner. Both trial logs carry the boundary row. Do not merge the cohorts.

## Deployment

Image built from the clean worktree before anything stopped; rollback tag created and verified; core stopped gracefully 10:08:47 (`docker stop -t 30`), telemetry copied; `docker compose up -d --no-build --no-deps companion-core` recreated core only; `/health` 200 at 10:08:54. **Core downtime about 7 s.** Hub, PostgreSQL, PgBouncer, vLLM and the rest were not touched. Environment and feature flags are identical to before.

## Verification (production, read-only except five probe turns)

| Check | Result |
|---|---|
| Core | image `1c3290c4d993`, 0 restarts, 0 tracebacks, hub log clean |
| `/brain/edges` over every visible node (3 notes, 2 tasks, 1 meeting) | exactly 2 edges: "refactor clickhouse migration" -> "My Task for next week" (`derived_from:c910a964…`) and "spin up gitlab repo" -> "GIT" (`derived_from:9e875118…`); `kind: derived_from`; basis names the processed version, not the note text; nothing crossing, nothing to "Reachy Project" |
| `/brain/summary` | `edges: 2`, equal to the edge list; total 6 (note 3, task 2, meeting 1) |
| Scope | tasks alone: 0 edges; notes alone: 0 edges; a repeated request returns identical output |
| Absent endpoints | edges requested with absent task or note ids (or a real task with an absent note): empty, and the two responses are identical in shape |
| Restricted and deleted endpoints | production holds no restricted or deleted endpoint with provenance, and no synthetic record was created to make one. Covered by the unit and PostgreSQL tests (a sensitive note or task and a deleted note or task give no edge, no count and no id; a restricted end is indistinguishable from a missing one) and by the absent-id check above |
| Conversation | "put the robot in standby" (text) and "delete all my memories" (voice): the 44H fixed reply; "What tasks do I have?" -> "You have 2 confirmed tasks: refactor clickhouse migration; spin up gitlab repo. 1 note has not been processed, so I can't say whether it holds other commitments."; a missing named note -> "I couldn't find a note or meeting called …"; "What is the capital of France?" -> Paris |
| Writes | all 13 record counts identical before and after; provenance still the 2 original rows (`c910a964`, `9e875118`); revision `029_notepad_processing`; "My Task for next week" has the same hash and `updated_at` (2026-10-09 02:45:24 UTC) |
| Capture | cohort D counters `{"attempted":5,"excluded_channel":5}`: probes only |

## Rollback (not needed)

`docker tag reachy-rollback/companion-core:pre-brain reachy-homelab-companion-core:latest`, then `docker compose -p reachy-homelab --env-file .env up -d --no-build --no-deps companion-core` (with `SEARXNG_SECRET_KEY` exported). Nothing in the database changed, so no schema step. Keep the tags and the dump until the owner accepts.

## Limits

The hub's `/brain/edges` path (owner-session only) was not exercised in production because it needs the owner's login; it forwards to the core route verified above and its tests pass. In the 3D view the two links show for the selected record unless "Show all links" is on.
