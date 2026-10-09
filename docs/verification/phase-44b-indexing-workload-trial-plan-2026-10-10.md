# Phase 44B production indexing-workload trial: plan and runbook (prepared 2026-10-10; NOT YET RUN)

Owner authorisation (2026-10-10): a supervised trial of the existing indexing worker on production, closing **only** the basic production indexing-workload gate. **It is executed only when the owner confirms they are present and the preflight passes.** No direct outbox insert, no artificial production record, no conversational retrieval, no shadow mode. Passing does not approve retrieval, the shadow or any later step. Tooling: [`tools/knowledge_indexing_trial.py`](../../tools/knowledge_indexing_trial.py) (read-only: preflight, monitor with abort gates, 4 Hz outbox watch, snapshot, verify) and [`tools/knowledge_index_validate.py`](../../tools/knowledge_index_validate.py). Earlier evidence: [first trial](phase-44b-indexing-trial-2026-10-08.md), [re-trial](phase-44b-indexing-retrial-2026-10-08.md) (idle indexer only; the worker never did real work).

## What is being observed, and how

| Observation | Method |
|---|---|
| MiniLM loading and initialisation | The worker loads the model lazily, on the first item that needs an embedding; a restart with an unchanged index loads nothing (as in the re-trial: core stayed at about 280 MB). Core memory and CPU are sampled every 6 s; the time from the owner's write to the index row covers load plus embedding for the first job. |
| Transactional outbox creation | The database trigger enqueues when the owner's write commits (it also does so with indexing off). The 4 Hz watch records the row appearing: source type, attempts, lease and failure flags. |
| Worker claim, lease and completion | The same watch sees `leased=true` then the row disappearing (completed), with `attempts`; a failure would show `failed=true` and aborts the trial. The worker polls every 5 s, so a claim follows the write within about 5 s. |
| Index row creation and source consistency | `knowledge_items` count and `indexed_at` in the watch; afterwards `verify` (a throwaway read-only container) compares the index with the stores: expected, indexed, missing, extra, stale versions, embedding model, 384-wide vectors, orphans, and revalidation for an owner and a shared speaker. |
| PostgreSQL and PgBouncer connections | Every 3 s: PostgreSQL backends (of 100), PgBouncer clients and servers, waiting clients and `maxwait`. |
| Throughput, latency, contention | Latency of the claim and completion from the watch; core CPU and memory; health latency of core, hub and vLLM every 3 s; host load and available memory. One item is not a throughput measurement: a second genuine edit by the owner gives a warm (model already loaded) latency. |
| Recovery after restoring the flag | After the flag is set back to `false` and core recreated: core memory and PostgreSQL connections return to baseline, the outbox is empty, the index is unchanged and consistent, services healthy. |

## Safety limits and abort criteria (unchanged from the earlier trials)

Abort immediately, restore the flag, and record why, on: PostgreSQL connections at or above 85; PgBouncer clients waiting on three consecutive samples, or `maxwait` of 2 s or more; core, hub or vLLM health failing or slower than 3 s twice running; host load average above 14; available memory below 3 GB; an outbox row marked failed; the stop file `/tmp/knowledge-indexing-trial.STOP`; or the owner's word. `KNOWLEDGE_EMBED_THREADS` stays at its default of 2. The time cap for the window is 15 minutes.

## Preconditions (all must hold; `preflight` checks the machine-checkable ones)

1. **The owner is present and says so.** Nothing starts without it.
2. Revision `027_knowledge_index`; indexing flag `false`; shadow flag unset; core, hub, PgBouncer and vLLM healthy; PgBouncer idle; PostgreSQL connections about 8 of 100; host load below 6 and 6 GB available.
3. No alarm or reminder due within 45 minutes; no meeting in progress or processing; no voice session; robot offline or idle; no deep-review transition; outbox empty with no failed rows.
4. A pre-trial dump exists: `docker exec reachy-homelab-postgres-1 pg_dump -U reachy -Fc reachy_hub > ~/reachy-backups/reachy-before-phase44e-indexing-trial-$(date +%Y%m%d-%H%M).dump`.
5. The owner has decided which **one genuine write** to make through an existing path, and will make no other writes (no new meeting, task, document, reminder) during the window. Suggested: a real note typed in the web UI (`/web/`, Notes) or a real memory ("remember ..." in a private chat) that the owner is happy to keep. Anything work-private is fine; nothing sensitive. If the owner wants a second edit afterwards for a warm-latency reading, it is the same kind of genuine write.

## Procedure

1. `python tools/knowledge_indexing_trial.py preflight` (all PASS) and `snapshot`; record the output. Verify the rollback command works as a dry read (below).
2. Start `monitor --seconds 900 --log <file>` and `watch --seconds 900 --log <file>` in the background.
3. Enable indexing for core only, with nothing else changed (the same command the earlier trials used; `.env` and the compose file are not edited):
   `cd deploy/homelab && export SEARXNG_SECRET_KEY=$(cat .env.searxng-secret) && KNOWLEDGE_INDEXING_ENABLED=true docker compose -p reachy-homelab --env-file .env up -d --no-build --no-deps companion-core`
   Confirm health, the flag in the container, and that the start-up reconcile finds no drift (index count stays 80, outbox 0, core memory about 280 MB: the model is not loaded yet).
4. **The owner makes the one genuine write.** Watch the outbox row appear, the lease, MiniLM load (core memory rises by roughly 400 to 500 MB), the new index row and the outbox row disappearing; expect completion within about 5 to 15 seconds of the write.
5. Wait about two minutes for any retries or reconciliation; optionally the owner makes a second genuine edit for the warm reading.
6. Stop the monitors. **Restore the flag:** the same compose command without the variable; confirm `KNOWLEDGE_INDEXING_ENABLED=false` in the container and health.
7. `verify`, then `snapshot`: index consistent with the stores (80 plus the owner's new rows, nothing missing or extra), outbox empty, connections and memory back to baseline.
8. Write the dated record (preflight output, timeline from the two logs, table of the observations above, connection and contention figures, recovery, gaps) and commit it. The derived index rows of the owner's write stay unless the owner wants them removed with the documented rollback (`deploy/homelab/rollback-027.sql` removes the whole index machinery; deleting only the new rows is a separate, owner-approved step).

## Pass / fail

**Pass** when: the outbox row for the owner's write was created, claimed under a lease and completed with no failed row; the index row exists, is 384 wide, labelled with the right sensitivity and local-only flags, and agrees with the source; PostgreSQL stayed within the bound with no waiting PgBouncer clients; no health or abort gate fired; and recovery after restoring the flag is clean. **Fail or inconclusive** otherwise, recorded as found. A pass closes only the basic production indexing-workload gate. It does not enable retrieval, the shadow or indexing permanently.

## Rollback

Set the flag back to `false` and recreate core (about 30 seconds); no schema change is involved; the backup is the pre-trial dump. The derived index rows are harmless with retrieval off.
