# Phase 44B production indexing-workload trial, 2026-10-09 (supervised; PASSED)

Owner authorisation: the supervised trial in the [plan](phase-44b-indexing-workload-trial-plan-2026-10-10.md), closing **only** the basic production indexing-workload gate. Executed with the owner present, 10:14 to 10:21 SGT (02:14 to 02:21 UTC; logs below are UTC). Retrieval and the shadow stayed off; nothing was inserted into the outbox by hand; the note content was never read or printed. Raw data: [`phase-44b-indexing-workload-trial-2026-10-09-data/`](phase-44b-indexing-workload-trial-2026-10-09-data/) (preflight, 72 monitor samples, the 4 Hz outbox watch around the claim).

**Outcome: passed.** One genuine owner write was indexed end to end on production by the real worker with the real MiniLM, with no abort gate triggered by the work, no failed or retried outbox row, no waiting PgBouncer client, services healthy throughout, a consistent index afterwards and a clean recovery. The indexing flag is `false` again.

## What happened, in order

| Time (UTC) | Event |
|---|---|
| 02:14:26 | The owner created one real note in the web UI (work-private, unscoped, 14-character title, 201-character body) and edited it four seconds later. The database trigger enqueued one outbox row (`note`, generation 2: the edit was coalesced into the same row). **Indexing was still off**, so the row waited: the owner wrote before the monitoring window was opened. The trigger moment is therefore evidenced by the row's timestamps, not watched live. |
| 02:15 | Preflight: every check passed except "outbox empty", which showed the one expected row (the owner's note). Pre-trial dump taken and listed with `pg_restore -l` (201 entries, includes the knowledge tables): `~/reachy-backups/reachy-before-phase44e-indexing-trial-20261009-1015.dump`, 276,847 bytes, mode 0600. Revision 027, 10 of 100 PostgreSQL connections, PgBouncer idle, load 1.8, 8.9 GB available. |
| 02:15:50 | Monitor and 4 Hz outbox watch started. |
| 02:16:10 | `KNOWLEDGE_INDEXING_ENABLED=true` for core only (existing default of 2 embedding threads; `.env` and compose untouched). |
| 02:16:13 | Core container started. |
| **02:16:17.3** | **The worker claimed the row: `leased=true`**, about 4 s after the container started (start-up reconcile found no drift, then the first outbox pass). Core CPU 94% and memory 272 MB in the sample at 02:16:16. |
| 02:16:17 to 02:16:30 | The lease was held for **13.2 s** (MiniLM load from disk plus embedding the one item). |
| **02:16:30.55** | **Completed: the outbox row was deleted and `knowledge_items` went 80 to 81** in the same 0.25 s step. `attempts` stayed 0 and the row was never marked failed. |
| 02:16:50 to 02:19:20 | Two and a half more minutes with indexing on: no new rows, no retries, no errors, memory steady at 600 MB. Read-only `verify` run during this time. |
| 02:19:46 | Flag removed: core recreated without the variable; `false` confirmed in the container. |
| 02:20 to 02:21 | Recovery checked (below). |

## Observations

| Item | Result |
|---|---|
| **MiniLM load** | Core memory 84 MB before; 272 MB at the first sample of the load; **600.6 MiB** once loaded and steady (+516 MB); CPU peaked at 93.7% of one core during the load. The worker loaded the model lazily on its first item, not at start. The host logged a Hugging Face "unauthenticated requests" warning at load: the model load contacted the hub (a note for deployment, below). |
| **Trigger and outbox** | One row for the note, generation 2, `enqueued_at` 02:14:26.5 (edit coalesced), never attempted before the flag; claimed with a lease at 02:16:17.3; deleted at completion. |
| **Claim, lease, completion** | Claim 4 s after start; lease 13.2 s; completion visible at 02:16:30.55; one claim, no retry, no failure. |
| **Index row** | `note` kind, `work-private`, no project scope, not local-only, confidence 1.0, 384-dimension embedding labelled `sentence-transformers/all-MiniLM-L6-v2`, `indexed_at` 02:16:17.27, 216 characters of match text. |
| **Source consistency** (read-only `verify`) | 2 sources (the meeting and the note), 81 expected rows, 81 indexed, **0 missing, 0 extra, 0 stale versions, 0 wrong embedding model, 0 orphans**; 81 embeddings all 384 wide. Revalidation for an owner and a shared speaker returned nothing for a generic query and dropped nothing: the retrieval path was exercised as a library only. |
| **PostgreSQL and PgBouncer** | 10 to 11 of 100 connections throughout (the worker's pools add about 1); PgBouncer **0 waiting clients, 0 maxwait on all 72 samples**; server connections at most 3 idle. |
| **Contention and latency** | Health latency: core median 93 ms (max 175), hub median 96 ms (max 133), vLLM median 1 ms (max 8). Load average at most 3.5, available memory at least 7.7 GB. Throughput is one item in 13 s including the cold model load; a warm per-item latency was not measured (a second edit would give it). |
| **Recovery after the flag was restored** | Core memory back to 81.7 MiB; PostgreSQL connections 10; outbox empty; index 81 rows intact and consistent; core, hub and vLLM healthy; the preflight passes in full, including "outbox empty". |

## Deviations and defects, stated plainly

1. **The owner wrote before the window opened** (an overlap of my instruction to signal first). Consequence: the trigger moment was not observed live; the outbox row's timestamps, its generation counter and the later claim show it. Nothing else changed: the claim, lease, MiniLM load, upsert and completion were all observed with the monitor running.
2. **The monitor's own abort gate fired at the planned restart.** Core was unreachable for two consecutive 3-second samples while its container restarted, which the tool treats as "service health failing twice" and stops. It was the intended restart, not a fault of the work; I restarted the monitor straight away (part 2, then part 3 after the flag was restored) and recorded the stop (`trial-mon-part1` ended at 02:16:16). Total monitored window: about 5 minutes of the 15 allowed. The tool should ignore the planned restart window (a follow-up).
3. **A leftover watcher.** Ending the 4 Hz `psql` watch left its server-side session idle (two such sessions, one from an earlier 3-second test). I terminated them; the tool now names the session and closes it on exit (fixed and tested).
4. The trial used the existing production image and the existing database; no code ran that was not already deployed except the read-only `verify` container.

## What this does and does not close

Closes the basic production indexing-workload gate: the real MiniLM load and the outbox claim, lease and complete path ran on production for a genuine write, with consistent data and clean recovery. It does **not** approve permanent indexing, conversational retrieval or the shadow, and it does not measure steady-state throughput or a large backfill. The derived index row for the owner's note remains (harmless with retrieval off); removing it is a separate owner decision.

## Notes for any permanent enablement

- The first index operation after each core restart pays about 13 s and +516 MB for the model load; core has no memory limit today (30 GB host).
- The load contacts the Hugging Face hub even though the model is cached: set the offline switch (`HF_HUB_OFFLINE=1`) and bake the model into the image before relying on it unattended.
- A planned restart trips the monitor's health gate; give it a grace period.
