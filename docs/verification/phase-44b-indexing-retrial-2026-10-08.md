# Phase 44B supervised indexing re-trial, 2026-10-08 (evening)

Owner authorisation: a bounded re-trial of the existing indexing worker now that Phase 45 (shared pools, PgBouncer) is deployed; no conversational retrieval, no synthetic production data. Times are Singapore time (UTC+8). Follows the [first trial](phase-44b-indexing-trial-2026-10-08.md), which hit PostgreSQL's connection limit. Raw samples: [the monitor log](phase-44b-indexing-retrial-2026-10-08.tsv) (142 samples, one every 4 to 5 s; the first rows before 23:09:30 have no PgBouncer columns because the monitor's helper script was lost when core was recreated, and was copied back in).

**Outcome: passed. No gate fired. The flag is `false` again and the worker is stopped.** This trial proved the connection fix and the idle steady state. It did **not** exercise the worker on new work (see limits).

## Preflight (23:04 to 23:06)

Database revision `027_knowledge_index`; core, hub, PgBouncer (healthy, 8 clients, 2 server connections), vLLM (healthy) and the model manager answering; no reminder pending; the only alarm is disabled and in the past; the one meeting `complete`; no hub log line about a robot or voice session in the previous 30 minutes (robot treated as offline); `knowledge_items` 80 (78 `meeting_segment`, 1 summary, 1 minutes), `knowledge_outbox` 0 rows; PostgreSQL 8 of 100 connections. The core image was built after `a969b87` (indexer pools `min 1, max 2`) and runs on the shared pool through PgBouncer (`DB_POOL_MAX_SIZE=8`). Stop and rollback: write the stop file next to the monitor log, or run `docker compose -p reachy-homelab --env-file .env up -d --no-build --no-deps companion-core` without the variable (the flag was set on that command only; `.env` and the compose file were not edited).

## Execution

| Time | Event |
|---|---|
| 23:06:47 | `KNOWLEDGE_INDEXING_ENABLED=true` for core only, `KNOWLEDGE_EMBED_THREADS` unset (default 2). Core healthy about 10 s later. |
| 23:06:55 to 23:17:34 | Monitor: PostgreSQL connections, PgBouncer pools, health latency of core, hub and vLLM, load, memory, core CPU and memory, index and outbox counts. |
| 23:10 | Read-only validation (below). |
| 23:19:59 | Flag removed by recreating core without the variable. `KNOWLEDGE_INDEXING_ENABLED=false` confirmed in the container. |

Stop conditions in force: PostgreSQL connections 85 or more; PgBouncer clients waiting on 3 consecutive samples or `maxwait` 2 s or more; core or hub health failing twice or slower than 3 s; load above 14; available memory below 3 GB; stop file. None fired.

## Measurements (10.5 minutes with the worker running)

| | Before (flag off) | With worker |
|---|---|---|
| PostgreSQL connections (of 100) | 8 | 10 at most, 7 at least (idle pool members time out) |
| PgBouncer clients waiting | 0 | 0 on every sample; `maxwait` 0 |
| PgBouncer server connections | 2 | at most 2 |
| Core health latency | 93 to 150 ms | p50 105 ms, max 196 ms, 0 failures in 137 samples |
| Hub health latency | 89 to 110 ms | p50 106 ms, max 231 ms, 0 failures |
| vLLM health latency | 10 to 16 ms | p50 12 ms, max 32 ms, 0 failures |
| Load average (1 min) | 1.9 to 2.1 | 3.1 at most |
| Available memory | 11.8 GB | 11.55 GB at least |
| Core memory | 100 MB | 280 MB (the pools, no model: nothing needed embedding) |
| Core CPU | 0.2% | 3.2% at most (the startup reconcile) |
| Index rows / outbox rows / failed | 80 / 0 / 0 | 80 / 0 / 0 throughout |

The indexer's two extra connections (pools `1..2`) are what the first trial's fix predicted (the first trial added eight). No client ever queued at PgBouncer, which the first trial could not have said.

## Validation (read-only, before and after; a one-off container from the production image, 1 CPU, writing nothing)

- **Reconciliation against the authoritative stores:** 1 source, 80 rows expected, 80 indexed, 0 missing, 0 extra, 0 stale versions, 0 rows from another embedding model, 0 orphan sources. Identical after the flag was restored. The worker's own start-up reconcile found no drift (the outbox stayed empty and the index count did not move).
- **Retrieval-time revalidation on the live index (library call in the container; no route, no flag, nothing given to the assistant):** owner on a private channel got the meeting for "meeting summary" and "decisions and action items", work-private and local-only; a query with no match ("budget") returned nothing; a shared (non-private) channel got nothing; with the index pre-filter switched off for a shared channel, the one candidate was dropped `over_ceiling` and none returned.

## Acceptance (owner, 2026-10-08)

Recorded as **passed** for: connection stability, PgBouncer behaviour, source consistency and access filtering, under an idle indexer. Production indexing stays disabled. **A separate production indexing-workload acceptance gate remains open:** the real MiniLM load and the outbox claim, lease and complete path have not run on production. It is to be satisfied by a real write once indexing is separately approved, never by a direct outbox insert or any bypass of the session's permission rules.

## Limits (what this does not show)

1. **The worker did no work.** The index was already complete, so the claim, lease and complete cycle and the embedding model were not exercised on production in this trial; core never loaded MiniLM (hence 280 MB). I attempted to enqueue the existing meeting by a direct insert into `knowledge_outbox` to exercise the claim path; the action was denied by the session's permission classifier and not retried or worked around. The claim, upsert and delete paths are covered by the 44B tests, the restored-copy rehearsal and the [contention test](phase-44b-contention-result-2026-10-08.md); a real write (a new meeting, memory or document) will exercise them once indexing is on.
2. No chat or speech latency probe ran against a user-facing path (only health endpoints), and no voice session, alarm or meeting was in flight by design.
3. One source (one meeting) is the whole corpus; query results above show the access rules, not retrieval quality.
4. Another session restarted the hub at about 23:00 (before this trial); it is unrelated to the worker.

## End state

Revision `027_knowledge_index`; core recreated with the flag `false`, healthy; 80 index rows, 0 outbox rows; PostgreSQL 9 of 100 connections shortly after the restart; hub, PgBouncer and vLLM unchanged and healthy; no temporary container left; `.env` and the compose file untouched; repository tree unchanged apart from this record. Retrieval stays off; turning indexing on permanently is a separate owner decision.
