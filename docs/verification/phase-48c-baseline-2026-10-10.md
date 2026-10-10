# Phase 48C: read-only operational baseline and prerequisite status, 2026-10-10

**Status: observation only. Nothing was changed, started, indexed or loaded; indexing, retrieval and shadow remain OFF, and the 48B evidence window is open.** Taken 14:10 UTC from the running homelab with `free`, `df`, `docker stats`, `nvidia-smi` and read-only SQL counts. One idle sample, not a load measurement; the "fresh baseline" the closure report requires must be retaken immediately before any indexing activation.

## 1. Measurements

| Item | Value |
|---|---|
| Host | 20 logical CPUs, load average 0.95 / 1.43 / 1.79 |
| Memory | 31.3 GB total, 12.8 GB used, 18.5 GB available (13.9 GB buffers/cache); **swap 7.8 of 8.2 GB used** (little headroom, although memory itself is available; a swap-pressure source to explain before any bulk embedding) |
| GPU | 13.8 of 16.4 GB in use (vLLM Qwen2.5-7B); a bulk run must not need the GPU |
| Disk | 196 GB free on `/` (78% used) |
| PostgreSQL | database 11 MB; 4 connections at rest (1 active, 3 idle) of 100 via PgBouncer |
| Container memory at rest | core 85 MB, hub 753 MB, vLLM 1.0 GB, semantic router 1.3 GB of 3 GB, PostgreSQL 44 MB, PgBouncer 3.6 MB |
| Records by source | memories 1, notes 3, tasks 0, reminders 0, documents (chunks) 0, meetings 1 (complete) |
| Index | 81 `knowledge_items` (80 meeting parts, 1 note: the one-note trial row, preserved); `knowledge_outbox` 4 pending rows, 0 attempts, 0 failed (queued by triggers while indexing is off; never edit by hand) |
| Backups | local dumps only (`~/reachy-backups`, 3.4 MB, 43 files, 0600); keyring copy on `USB Storage/reachy-keys/` |

## 2. What this means for 48C

1. **The real corpus is tiny.** About 85 index rows would result from indexing today's owner data; the 80-row meeting backfill was already built once (2026-10-08) and the one-note trial passed. Indexing the real corpus is cheap; the risk is contention and operational readiness, not volume. A bulk-load contention test therefore needs a synthetic corpus on a disposable stack, not the owner's data.
2. **Prerequisite status** (closure report, section 3):

| Prerequisite | Status |
|---|---|
| Verified off-host backup | **Not met.** The backup programme is paused; the NAS offers no usable transfer path ([plan](../postgres-backup-implementation-plan.md)). A fresh local dump exists from the 48B activation (`reachy-before-phase48b-capture-*.dump`) |
| Isolated restore | Not done for this database state (the procedure exists in [deployment](../deployment.md)); cheap at 11 MB |
| Fresh memory/DB-connection/disk/CPU baseline | Idle sample above; retake before activation, under normal use |
| Bulk-indexing contention test | Done 2026-10-08 ([result](phase-44b-contention-result-2026-10-08.md): chat +10%, speech p95 +28%, indexer 30.6 items/s beside the foreground); repeat only if the embedding setup or hardware headroom changed, noting the swap level above |
| Rollback rehearsal | Done for 027/028 schemas; the flag rollback is the indexing rollback (`KNOWLEDGE_INDEXING_ENABLED=false`, outbox keeps queuing) |

3. **Candidate ceilings** (derived from the idle baseline and the 2026-10-08 contention result, to be confirmed in 48C, not yet accepted): chat p95 regression under 10%; no OOM or container restart; no dropped meeting job; PgBouncer-fronted backends under 25 of 100 during backfill; swap use not growing across the run.
4. **Decision for the owner before 48D:** whether the off-host backup waiver extends to indexing the (small) real corpus. Indexing writes only to the derived index and outbox and never to source tables, so the loss exposure is the rebuildable index; the source data's exposure is unchanged by indexing, which weakens the argument for blocking on it. This is the owner's call; the closure report currently requires the backup.

## 3. Not done (by instruction)

No indexing, no retrieval, no shadow, no load generation, no model swap, no restart.
