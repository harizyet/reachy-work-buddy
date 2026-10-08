# Phase 45E production cutover, 2026-10-08

Owner decision: adopt shared process-level connection pools and PgBouncer on the homelab, following the [runbook](../deployment.md#phase-45e-cutover-shared-pools-and-pgbouncer-runbook) and the benchmark in the [Phase 45 record](phase-45-2026-10-08.md). Knowledge indexing and retrieval stayed disabled throughout. **Software cutover passed every gate; no rollback was needed.** Times are Singapore time (UTC+8).

## What is deployed

Code: pinned commit `d4906c5` (images; the later commit `9d1cdf6` changed only compose and docs, which were applied). Built from a clean `git worktree` (0 modified files); the deployable diff from the previous deployment was only the reviewed Phase 45 work. Core, hub and coding-agent run the new images (`3dfd299d5e3b`, `68d9733ca8de`, `1f53a503a015`); `migrate` uses the core image. Each service has one `DatabaseManager` pool (1 idle, at most 8, 10 s acquisition timeout). PgBouncer 1.25.2 (`edoburu/pgbouncer:v1.25.2-p0`, digest `sha256:7d7a27d9...`), transaction pooling, pool 20 plus 5 reserve, `max_prepared_statements = 100`, runs as the auth file's owner. `.env` gained `DB_HOST=pgbouncer`, `DB_PORT=6432`, `DB_PREPARE_THRESHOLD=off`; `migrate` and recovery stay on `postgres:5432`. Core has a `model-cache` volume (`HF_HOME=/data/model-cache`). PostgreSQL, vLLM, the sidecars, Caddy and the robot host were not touched.

## Timeline and downtime

| Time | Step |
|---|---|
| earlier | PgBouncer started alongside the still-direct applications; its auth file permission fault and healthcheck fault found and fixed before cutover (commit `9d1cdf6`) |
| 15:43:10 | Key files encrypted to the USB drive and verified |
| 15:43:20 | Preflight (below) |
| 15:43:30 | Core stopped, then hub and coding-agent (stopped 15:43:31); 0 database clients |
| 15:43:38 | Dump taken, restore-verified, rollback tags and snapshots, `.env` copied |
| 15:44:31 to 15:44:43 | Retag, `.env` switch, `up -d --no-build` for the three applications |
| 15:44:43 | Hub and core healthy |

**Downtime of core, hub and coding-agent: 73 seconds.** The hub finished loading its speech model afterwards (two `voice provider ready` lines).

## Preflight

Revision `027_knowledge_index`; `KNOWLEDGE_INDEXING_ENABLED=false`; 80 index rows, outbox 0; no alarm or reminder due within 45 minutes; the one meeting `complete`; no voice session; model manager `ready_t1` with no transition; hub and core healthy; 248 GB free; PgBouncer healthy.

## Backups and rollback readiness

- **Key backup (gate 6):** the two key files were encrypted with GPG (AES-256, passphrase from a 0600 file the owner wrote) to `USB Storage/reachy-keys/offhost-keys-20261008-154310.gpg` (370 bytes, sha256 `6b9b186494aa3aa4...`). It was read back from the USB drive, decrypted, and both key files matched the originals by SHA-256; the temporary plaintext was shredded. The drive is attached to this machine, so this protects against file loss or corruption but not loss of the machine; moving the `.gpg` to another device is advised. The passphrase is kept by the owner, not here.
- **Database dump:** `~/reachy-backups/reachy-before-phase45e-20261008-154338.dump`, 276,525 bytes, mode 0600, sha256 `3cbc9ec1f6bea655...`, taken after the writers stopped. Restored into a throwaway container on an internal network: revision `027_knowledge_index` and identical row counts for all 41 tables; container and network removed.
- **Rollback:** images tagged `reachy-rollback/{companion-core,reachy-hub,coding-agent-service,migrate}:027-pre45` (`04fb9950447b`, `78176d66fc1a`, `bd150ee12f07`, `9f3f1e256dd4`) and container snapshots `:027-pre45-container`; `.env` copied to `~/reachy-backups/env-before-phase45e`. To roll back: remove the three `DB_*` lines from `.env`, retag the `:027-pre45` images to `:latest` (optional, the new images also connect directly with those lines gone), and `up -d --no-build --no-deps companion-core reachy-hub coding-agent-service`. The database schema is unchanged by this cutover.

## PgBouncer verification (gate 7)

Wrong password refused (`SASL authentication failed`); unknown user refused; unknown database refused (`no such database`, no wildcard in the production config); correct credentials accepted. `SHOW CONFIG`: transaction mode, `default_pool_size` 20, `reserve_pool_size` 5, `reserve_pool_timeout` 3, `max_client_conn` 300, `max_prepared_statements` 100, `query_wait_timeout` 10, `client_login_timeout` 10, SCRAM auth, `listen_addr` 0.0.0.0 inside the container. Exposure: no published port (`docker port` empty), nothing listening on the host's 6432, connection from the host refused. Any container on the compose network can reach `pgbouncer:6432` (as it can reach `postgres:5432`) and needs credentials. The application role is also PgBouncer's admin user (single role); see the follow-up item.

## Measurements (gate 10)

| | Before (direct, old pools) | After (shared pools + PgBouncer) |
|---|---|---|
| PostgreSQL backends at rest | 98 | **8** (2 PgBouncer server connections + 5 server background processes + 1 monitor) |
| Under 8 concurrent hub read workers (40 s, about 15,000 requests) | about 98 (flat) | **14** peak |
| Under 32 concurrent workers | about 98 (flat) | **19** peak |
| Read latency p50 / p95 / max at 32 workers | 66 / 177 / 549 ms (earlier, direct) | 67 / 192 / 506 ms |
| PgBouncer pool during the bursts | n/a | 14 server connections used of 20 plus 5 reserve, 0 clients waiting |
| Query latency, `select 1` x 200 | direct p50 0.11 ms, p95 0.22 ms | via PgBouncer p50 0.15 ms, p95 0.69 ms |

PgBouncer statistics since its restart in the drill (3,134 transactions, 6,300 queries): total wait time 16 ms, average transaction time 0.59 ms, average query time 0.19 ms. The cumulative counters before that restart (142,796 transactions across the burst runs) were reset by the restart and the wait figure for those bursts was not captured; the pools showed 0 clients waiting during them. About 8% of the burst requests return HTTP 4xx because a route in the load shape needs a parameter; the same share appeared in the pre-cutover runs and is unrelated to the database.

## Smoke and regression tests (gates 9, 11)

- **Regression suites on the deployed commit** (with a disposable pgvector server): core 936 passed, 7 skipped; hub 433 passed with the one known failure (`test_spoken_command_text_does_not_actuate_the_robot`, failing before this work); coding-agent 82 passed; lint clean. The pooler compatibility matrix (6 cases) and failure exercises ran on the disposable stack earlier and are not repeated against production.
- **Live smoke:** revision and all 41 table counts identical to the pre-cutover snapshot before and after the smoke records; hub UI and status 200; to-do created as `sensitive` with scope, text edit keeps both, an edit carrying `sensitivity` 422, an invalid value 422, delete 200; note created `work-private` and deleted; a reminder due in two minutes was claimed 21 s after it fell due (the hub's notify loop); alarms, receipts and robots reads 200; the meeting lists and opens with 78 transcript segments; a memory was created and recalled; a document was ingested (embedding) and a vector search returned it as the top hit in 0.08 s; the outbox triggers queued rows for the notes, tasks, memory, document and reminder writes (`knowledge_items` stayed at 80 and the flag at `false`, so nothing was indexed). All smoke rows were removed (tasks, notes, reminders, memories, document chunks, outbox) and the counts again equal the snapshot.
- **Model cache (gate 5):** the first document ingest downloaded the embedding model into the volume (88 MB, 45.8 s). After recreating the core container the volume still held it and an embed with `HF_HUB_OFFLINE=1` succeeded in 9.1 s (no download possible).
- **PgBouncer restart under load (gate 11):** with a probe writing a task and reading every 0.25 s, PgBouncer was restarted (11 s for the container): 0 errors, slowest call 7.4 s, 148 writes acknowledged, **148 present in the database, 0 missing, 0 duplicate rows** (each write has a unique text, and the hub and core do not retry statements). The hub logged `Connection refused` connection attempts during the restart and recovered on its own; all services stayed healthy.

## Open items

- **Pending, not waived:** robot connectivity and voice (not tested; nothing was sent to the robot); a browser pass through the web UI; the owner's confirmation that the Telegram push for the smoke reminder arrived.
- Move the encrypted key backup off this machine when convenient.
- The hub's speech model cache has the same re-download behaviour core's embedding model had; adding a volume is a small separate change.
- Follow-up item: replace application superuser access with least-privilege roles ([Phase 45 section 10](../phase-45.md#10-follow-up-least-privilege-database-roles)).
- Phase 44 stays paused; the repeat indexing trial can now be planned against the new connection budget when the owner chooses.

## Acceptance (owner, 2026-10-08)

Accepted at the infrastructure level: the connection reduction (98 to 8 at rest, 19 at 32 workers), the concurrency tests, PgBouncer restart recovery, the verified backup and the unchanged authoritative data satisfy the infrastructure acceptance criteria. **Kept open:** browser UI interaction, Telegram reminder delivery confirmation, voice integration, and physical robot testing. The cutover is not to be rolled back solely because these remain pending. Phase 44 indexing and retrieval stay disabled until these and the performance gates are reviewed. Next: [Phase 46, least-privilege database roles](../phase-46.md) (plan only; no credential changes or deployment yet).

## Telegram delivery confirmed

The owner confirmed on 2026-10-08 that the Telegram push for the smoke reminder (claimed 21 s after it fell due) arrived, closing that acceptance item. Still open: browser UI interaction, voice integration, physical robot testing.

## Availability observation: the 7.4 second call during the PgBouncer restart

Recorded as an availability observation, not a defect and not a rollback trigger. During the restart drill one hub call took 7.4 s while the rest were fast; nothing failed, nothing was lost or duplicated, and the hub's pool timeout (10 s) was not reached.

Evidence: the container restart took 11 s; PgBouncer logged `got SIGTERM, shutting down, waiting for all clients disconnect`; the image's entrypoint `exec`s PgBouncer, so it received the signal directly; the three services hold idle client connections in their pools, so a graceful shutdown waits for clients that never leave until Docker's 10 s stop timeout kills it. While PgBouncer was shutting down it accepted no new work, so a request that needed a connection waited for the restart. That explains an interruption of up to about 10 s on a planned restart; it is an interpretation of the evidence, not a measured proof. A second consecutive wait would run into the 10 s acquisition timeout and surface as an error rather than a hang. Options to evaluate on a disposable stack, none applied: a shorter `stop_grace_period`, a different stop signal (PgBouncer treats the signals differently, to be confirmed against the 1.25 documentation and by test), and a `reload` instead of a restart for configuration changes. Measure the interruption before and after; production stays as it is.
