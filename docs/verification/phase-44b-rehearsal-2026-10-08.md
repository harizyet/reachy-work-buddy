# Phase 44B migration 027: rehearsal and deployment readiness, 2026-10-08

Evidence for the readiness gates of [Phase 44B](../phase-44.md#11b-44b-unified-index-outbox-and-revalidation-2026-10-08). **The live services and database were not changed.** Production was touched only read-only: a `pg_dump` snapshot through `docker exec`, and a query of the revision. The live database is at `026_source_sensitivity`; migration 027 has been applied only to throwaway copies and databases. `KNOWLEDGE_INDEXING_ENABLED` stays `false` in production.

The rehearsal images (`migrate`, `companion-core`) were built from the working tree under a separate project name, which at that moment included another session's uncommitted edit to `shared/protocols/operator_api.py` (a new route constant, unrelated to knowledge). The deployment itself must build from a clean pinned commit.

## Rehearsal on a restored production copy

Isolated as in the 026 rehearsal: a throwaway production-image Postgres on an `--internal` network, no published ports, 0700 directory, files at 0600, the production keyring mounted read-only. For the indexing step the host's Hugging Face cache was mounted read-only with `HF_HUB_OFFLINE=1`, so no data and no network egress were involved.

| Step | Result |
|---|---|
| Snapshot of production | consistent: per-table counts equal before and after the dump (39 tables, 109,239 bytes), revision 026 |
| Restore | revision 026, identical counts |
| Migration 027 (new image, production keyring) | success; 1.75 s wall for the whole container run (the in-database work is about 0.1 s); revision `027_knowledge_index`; 2 derived tables, 7 functions, 6 triggers; backfill queued 1 source (the one meeting); authoritative counts unchanged; a second run is a no-op |
| New core with indexing **off** | healthy; after 8 s no index rows and the queued event untouched; no knowledge lines in the log |
| New core with indexing **on** (first build of the copied records) | outbox drained in 5.4 s; 80 index rows (78 meeting segments, 1 summary, 1 minutes), all with 384-dimension MiniLM vectors; 472 kB for index and table; the log contains none of the transcript text |
| Rollback with `rollback-027.sql` (services stopped) | 0.09 s; 0 derived tables, functions or triggers left; revision 026; authoritative data intact |
| 026-era production image against the rolled-back copy | starts and is healthy |
| New image against the rolled-back (026) copy | refuses to start, as intended |
| Restoring the pre-027 dump over a 027 database | **fails** without the rollback script first (`cannot drop extension vector because other objects depend on it`); succeeds, with counts identical to the production snapshot, after `rollback-027.sql` |
| Disposal | containers removed with `-v`, network removed, every file shredded, rehearsal image tags removed, no rehearsal file left in `~/reachy-backups`; the nine `reachy-homelab-*` containers and the live revision unchanged |

## Real application write paths (core's HTTP API, worker running)

Run twice: against the container on the restored copy (above), and as an automated test on Postgres with the real stores (`test_the_real_application_write_paths_keep_the_index_right`).

| Write | Effect on the index |
|---|---|
| Create a note | indexed 2.6 s later (the worker polls every 5 s) |
| Edit a note | new text indexed on the next pass |
| Delete a note, task or reminder | row gone in the same transaction, before any worker pass |
| Create a memory, then request and confirm forgetting | the request changes nothing; the confirmation removes the row at once |
| Restore a forgotten memory | indexed again on the next pass |
| Create a task with `sensitive`, then complete it | classification carried to the index; the "(done ...)" text follows; delete removes the row at once |
| Ingest a document | every chunk indexed with its classification |
| Correct a meeting segment | the corrected text, not the raw transcript, is indexed; the raw transcript is untouched |
| Raise a meeting's classification (no API exists; done in SQL as an operator would) | the index label follows in about 3.6 s, and revalidation enforces the new label immediately |
| Delete a meeting | database and index rows gone at once |
| Cancel a meeting | **cannot be exercised on an indexed meeting through the API**: a meeting is indexable only once transcribed, and from then on its status is `aligning` (which the worker completes within seconds) or `complete`, neither of which can be cancelled. The trigger rule for `cancelled` and `failed` is a safety net for other writers and is covered at store level |

No failed outbox rows and no traceback in the core log across these runs.

## Measurements

`benchmarks/knowledge_retrieval/index_overhead.py` on a disposable Postgres (20 CPU development host, load average about 2.5, throwaway container on local disk). Synthetic database: 2,000 notes, 2,000 tasks, 2,000 memories, 2,000 document chunks, 40 meetings of 140 segments (13,600 indexable parts).

**Migration duration.** 0.09 s in the database with 6,440 sources to queue; production today has one.

**Trigger write overhead.** The same workload with the triggers disabled and enabled, alternating over 5 rounds of 500 operations, medians. Each operation is its own transaction, as the application does it, so about 1.2 ms of every figure is commit latency.

| Operation | without triggers | with triggers | added |
|---|---|---|---|
| note / task / memory insert | 1.19 to 1.22 ms | 1.39 to 1.44 ms | 0.19 to 0.22 ms |
| note update, memory forget, meeting correction | 1.17 to 1.23 ms | 1.58 to 1.63 ms | 0.40 to 0.41 ms |
| note / task delete | 1.15 ms | 1.54 to 1.57 ms | 0.38 to 0.42 ms |
| memory read (`last_accessed` stamp; the trigger does not fire) | 1.16 ms | 1.27 ms | 0.11 ms (noise) |

An earlier single-pass comparison showed 3 ms on updates; a control pass with no migration showed the same swing, so it was storage jitter, not the triggers, and the alternating design above replaced it.

**Storage.** After indexing all 13,600 parts: `knowledge_items` 61.8 MB in total (table 13.2 MB, indexes 30.5 MB, the rest TOAST), about 4.5 KB per row and 4.1 times the size of the source tables (14.4 MB); `knowledge_outbox` 3.9 MB, which is bloat from deleted rows and returns to nothing after a vacuum. Linear projection: about 45 MB per 10,000 parts, 450 MB per 100,000.

**Indexing cost** (real MiniLM, 2 torch threads, one worker): 213 s for 13,600 parts (64 parts per second), 303 CPU-seconds, 547 MB peak resident memory. A first build of the 100,000-part scale would take about 26 minutes; production's roughly 80 parts took 5.4 s.

**Embedding contention.** Event-loop stall while embedding stayed under 2 ms (44B verification). The effect on the speech, language and diarization services is not measured: the controlled test is prepared in `tools/knowledge_contention_test.py` (three phases: speech and chat alone, with indexing, and indexing alone; reports latency p50/p95/max, errors, chat tokens per second and embedding throughput; refuses to run against real services without `--confirm-owner-approved`; its self-test against stub servers passes). It has **not** been run against the homelab and needs the owner's approval, the robot idle, and indexing off in core while it runs.

## Retention and deletion of indexed data

What is copied: the full text of each indexed part (`match_text`, including speaker names and, for sensitive records, sensitive text), a 384-dimension embedding of it, and its classification, scope, confidence and validity. The outbox holds only a source type and id, a counter and timing, and a failure reason.

| Question | Answer |
|---|---|
| When a record is forgotten, deleted, cancelled or fails | its index rows are deleted in the same transaction as the change (triggers) |
| When a record's text or classification changes | the row is rewritten by the worker, typically within 5 s; until then revalidation uses the source's text and the stricter label, so the stale copy cannot be returned |
| When a memory expires | nothing announces the passage of time: the stale text stays in the index until the next reconciliation (hourly by default, `KNOWLEDGE_RECONCILE_SECONDS`), and revalidation refuses to return it in the meantime. Retention is bounded by that interval |
| Embeddings | derived from the text and treated as equally sensitive; they are deleted with the row; they are not exported (the Ossie export describes structure only) |
| Failure text | an exception message can quote the row being indexed, so only the exception class, database error code and code location are stored and logged (tested) |
| Removing the whole index | `deploy/homelab/rollback-027.sql` (or `DELETE FROM knowledge_items`; reconciliation rebuilds it) |
| Dead rows and backups | deleted text remains in dead tuples until vacuum, as for the source tables, and a forgotten record persists in older database dumps exactly as the source row does. `~/reachy-backups` is not pruned automatically; a retention rule for dumps is the owner's decision |
| Logs | no transcript text in the core log across the rehearsal's indexing run |

No gap that needs code was found beyond the failure-text fix already committed. Two decisions remain the owner's: how long old dumps are kept, and whether the hourly bound on expired text is short enough (it can be lowered with `KNOWLEDGE_RECONCILE_SECONDS`).

## Deployment readiness for 027

Ready on the engineering side; **not authorised and not scheduled.** To apply it: the 026 runbook sequence (quiet window, repeat the preflight, stop core first, verified dump, rollback images, build from a clean pinned commit, migrate, start), with these differences. The hub must be rebuilt as well as core, migrate and coding-agent (every service shares the revision check). `KNOWLEDGE_INDEXING_ENABLED` stays `false`; the backfilled outbox rows simply wait. A rollback is `rollback-027.sql` with the services stopped, then the previous images. Run the contention test only when separately approved, and turn indexing on only as its own decision.
