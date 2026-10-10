# Phase 48C/48D: indexing readiness and production activation, 2026-10-10

**Status: knowledge indexing is ON in production (`KNOWLEDGE_INDEXING_ENABLED=true`, 14:35 UTC); retrieval, selective answering and selective shadow are OFF and unset. The small real corpus indexed completely in under 20 s and verified clean. Stopped here: 48E (retrieval) is not started and needs the owner's approval.** The 48B evidence window continues in parallel with capture frozen (one logging finding below).

## 1. Owner decision recorded (2026-10-10)

The off-host backup requirement is **waived for this small 48D index activation only**: about 85 index rows; indexing writes only to the derived, rebuildable index and outbox and never to authoritative source tables. It does not remove the general off-host-backup requirement for operations that mutate or materially risk authoritative owner data. Conditions set by the owner: a fresh local dump immediately before activation and a readability check, source row counts recorded before, retrieval/selective/shadow flags off, a synthetic bulk benchmark on a disposable stack, a production idle baseline, and a rehearsed disable/rebuild/rollback.

## 2. Preconditions

| Requirement | Result |
|---|---|
| Fresh local dump | `~/reachy-backups/reachy-before-phase48d-indexing-20261010-2234.dump` (0600, 286 KB), taken 14:34 UTC |
| Dump readable | `pg_restore -l` lists 214 entries; restored into a throwaway server (internal network, removed): every checked table's count equals production (memories 1, notes 3, tasks 0, reminders 0, document chunks 0, meetings 1, index 81, outbox 4, candidates 0, alarms 9) |
| Source tables before activation | counts plus an MD5 over each table's rows: memories 1, notes 3, tasks 0, reminders 0, document_chunks 0, meetings 1, alarms 9, memory_candidates 0 |
| Flags | retrieval, selective answering and shadow are not set in core (and not in Compose); candidates review and capture unchanged |
| Synthetic benchmark, disposable | below (section 3) |
| Production idle baseline | below (section 4) |
| Rehearsed disable, rebuild, rollback | below (section 5) |
| Preflight tool | `tools/knowledge_indexing_trial.py preflight` still demanded revision 027; it now accepts 027 or 028. Its three remaining FAILs were understood and accepted: revision (the tool's stale check), outbox not empty (4 expected trigger-queued rows while indexing was off), and model manager unreachable (the host process is not running; no deep-review job exists to protect) |

## 3. Synthetic bulk and contention benchmark (disposable scratch Postgres, `--cpus 2 --memory 2g`, removed)

`tools/knowledge_contention_test.py`, 90 s phases, real `IndexingWorker` with real MiniLM (2 embed threads, nice 10) over a synthetic 2,000-row corpus, small.en Whisper on host CPU (4 threads, a synthetic 7.4 s clip), chat to the production vLLM (64 tokens, one in flight; the same method as the [2026-10-08 run](phase-44b-contention-result-2026-10-08.md)). Report: [phase-48c-contention-2026-10-10.json](phase-48c-contention-2026-10-10.json). No abort fired; production health checks 58, 0 failed (max 9 ms); no service restarted; the scratch database was dropped.

| | A: foreground | B: + indexing | change A to B | R: recovery |
|---|---|---|---|---|
| Chat latency p50 / p95 | 1.50 / 1.63 s | 1.63 / 1.74 s | **+8.7% / +6.4%** | 1.49 / 1.61 s |
| Chat TTFT p50 | 36 ms | 36 ms | 0% | 34 ms |
| Chat errors / speech errors | 0 / 0 | 0 / 0 | none | 0 / 0 |
| Speech p50 | 12.6 s | 13.2 s | +4.2% | 12.6 s |
| Indexing | | 39 items/s | | alone: 89 items/s |
| Host CPU mean (max) | 25% (31) | 34% (40) | | |
| Available RAM, minimum | 16.3 GB | 16.4 GB | | 16.5 GB |

Swap activity during the run (`vmstat 2`, 169 samples, about 5.6 minutes): swap in 1,364 KB in total (largest sample 324 KB/s), swap out 77 KB in total (the 77 is the since-boot first sample), and swap in use did not grow (7,970,672 KB at the start, 7,968,180 KB at the end). The 7.8 GB of swapped cold pages is therefore static, not churn.

## 4. Production idle baseline (before activation, 14:15 UTC, with capture ON and no indexing)

CPU 93 to 94% idle over a 60 s vmstat sample (load 1.0); available RAM 18.5 GB; swap in/out 0 in 11 of 12 samples (first sample is the since-boot average); PostgreSQL via PgBouncer 3 connections (1 active, 2 idle) of 100; **chat latency (20 requests, 64 tokens, short prompt) p50 0.36 s, p95 0.69 s, TTFT p50 43 ms**; restart counts 0 on all 11 containers (core's own start 14:06 UTC from the 48B activation).

## 5. Rehearsal on a restored copy (internal network, no published ports, removed; the rehearsal dump was shredded)

The production image against a restored copy of the dump with the real keyring mounted read-only and the model cache mounted read-only (offline). All of these were observed:

| Step | Result |
|---|---|
| Indexing ON | outbox drained, 82 then 83 rows; the cold first run took about 5 minutes only because of a failed model download attempt on the no-egress network (the second start used the production model cache: 12 to 75 s) |
| Read-only validator (`tools/knowledge_index_validate.py`) | `expected_rows=83 indexed=83 missing=0 extra=0 stale_version=0 wrong_model=0 orphan_sources=0`, all embeddings 384-wide |
| Indexing OFF, then a note edited | the edit was queued in the outbox (1) and stayed queued, index unchanged, for 15+ s |
| Indexing back ON | queue drained in about 12 s; validator clean (the edit is reflected) |
| Delete the whole index (`DELETE FROM knowledge_items`), then indexing ON | validator showed `missing=83` while empty; after the restart all 83 rows were rebuilt from the authoritative sources in 16 s, validator clean |
| Rollback | the flag off stops all processing and leaves the index and source data intact; removing the index is `DELETE FROM knowledge_items` (reconciliation rebuilds it) or `deploy/homelab/rollback-027.sql` (schema, rehearsed 2026-10-08) |

## 6. Production activation

Preceded by a graceful stop of core to read the 48B in-memory summary (see the finding in section 8: no summary line exists in the logs). `.env` gained `KNOWLEDGE_INDEXING_ENABLED=true`; `up -d --no-build --no-deps companion-core` at 14:34:59 UTC (same image `15ce11cf8ad9`). Core was down about 22 s. Rollback: set the flag to `false` (or remove the line) and repeat the same command; `DELETE FROM knowledge_items` only if the index itself should go.

## 7. Verification after activation (production, read-only except the worker's own writes)

| Check | Result |
|---|---|
| Outbox | 4 queued rows drained within 20 s; 0 rows, 0 failed |
| Index counts | 83 rows: 78 meeting segments, 1 meeting summary, 1 meeting minutes, 3 notes. Expected by source adapters: the same, 83 (memory 0: the single memory is forgotten and so not indexed; documents, tasks, reminders 0) |
| Source tables unchanged | counts and MD5 checksums of memories, notes, tasks, reminders, document_chunks, meetings, alarms, memory_candidates are **byte-identical** to before activation |
| Drift and orphans | `missing=0 extra=0 stale_version=0 wrong_model=0 orphan_sources=0`; direct SQL: 0 index rows for a note or meeting that no longer exists; embeddings 384-wide, model `all-MiniLM-L6-v2` |
| Forgotten, expired, deleted data | the forgotten memory has no index row; revalidation at retrieval and the immediate removal on forget, delete and cancel pass on real Postgres (`test_knowledge_postgres.py` three revalidation tests; `test_knowledge_retrieval.py` 30 passed, 1 failed: the known historical-mode baseline failure). No production data was mutated to test this |
| Sensitivity and scope | every index row is `work-private` with no project scope, matching the sources (3 notes and 1 meeting all `work-private`, no scope); production has no sensitive or scoped records yet, so inheritance for those is covered only by the automated tests |
| Meeting corrected text | the meeting has 2 accepted corrections (segments 3 and 4); the corrected text is in the index (1 matching row each) and the raw transcript text is in none |
| Summaries and minutes | indexed with kinds `meeting_summary` and `meeting_minutes`, separate from `meeting_segment` evidence rows, so generated text stays distinguishable from transcript evidence |
| Delete and rebuild from sources | demonstrated on the restored copy (section 5), not repeated on production |
| Retrieval, selective answering, shadow | not set; core environment shows only `KNOWLEDGE_INDEXING_ENABLED=true` |

Impact after activation (about 14:37 to 14:44 UTC): chat p50 0.35 s, p95 0.37 s (baseline 0.36 / 0.69); swap in/out 0 in all 5 samples; swap in use 7,780 MB (unchanged); PostgreSQL connections 3 (1 active, 2 idle); restart counts 0 on all containers; core memory 410 MB (the loaded MiniLM, about +325 MB); core CPU about 0.8% of a core in steady state over 30 s (an early `docker stats` reading of 15 to 25% was the startup reconciliation); no error or traceback in core logs; the bounded monitor (900 s) raised nothing after the restart. No stop condition (chat p95 >10%, restart, swap churn, dropped meeting jobs, 25 or more PgBouncer-fronted backends) was reached.

## 8. Findings

1. **48B end-of-window procedure does not work as written.** Core's `capture summary` is logged at INFO under `companion_core.memory_candidates`, and nothing configures logging, so the line is never emitted (a graceful stop at 14:34 UTC printed only uvicorn lines). The in-memory tally for 14:06 to 14:34 UTC (duplicates, caps, exclusions) is lost; the durable counters show 0 proposed in that period. The capture code was **not** changed. Proposed for owner decision: raise that one log call to WARNING (it is in `app.py`, not one of the four frozen capture files, and it adds no content), or add a read-only counters route, applied at a defined point in the window.
2. The bounded monitor aborts on a core restart unless `planned-restart` is called first; I forgot to, so the first monitor run stopped itself at the activation restart and was restarted.
3. The model manager is not running on the host (preflight). It is not needed for indexing; it is the owner's separate deep-review component.
4. The real corpus is small (83 rows: three notes and one meeting), so indexing it was cheap and the measured contention margin is large (chat +6 to 9% under a deliberately heavy synthetic load).

## 9. Not done, by design

Retrieval, selective answering, shadow and the production real-corpus retrieval quality set (48E). A production delete-and-rebuild was not performed (rehearsed on a restored copy). No robot involvement.
