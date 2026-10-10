# Phase 44 production deployment, 2026-10-10 (migration 028; all new features disabled)

Owner decision, 2026-10-10: *deploy pinned commit `ca21d726110f3e3005312cc04ec3732704bcc5b2`; the owner accepts the risk of no new PostgreSQL backup because the database holds disposable test data; backup and isolated-restore prerequisites are waived for this deployment; keep every new knowledge and memory-candidate flag OFF; do not touch the robot, change models, enable indexing, activate retrieval or start capture.* **Result: deployed and verified. Features disabled pending activation.**

## What was deployed

- **Code:** images built from a **clean `git worktree`** of `ca21d72` (zero modified files) with plain `docker build`, tagged `:44-ca21d72` and `:latest`: core and migrate `966642fe0c5a`, hub `0e5f42fb8504` (includes the React build with the Memory page), coding-agent `dc202e9038ed`. Verified before the swap: migration `028_memory_candidates.py` and the new `SCHEMA_REVISION` are in the core, migrate and coding-agent images; `memory_candidates.py` and a bundle containing the Memory page are in the hub image.
- **Schema:** `027_knowledge_index` to **`028_memory_candidates`** by the existing `migrate` job (`docker compose run --rm migrate`, direct to PostgreSQL). Tables `memory_candidates`, `memory_candidate_suppressions`, `memory_candidate_counters` and the index `memories_candidate_source_uq` exist; `memory_candidates` is empty.
- **Recreated:** `companion-core`, `reachy-hub`, `coding-agent-service` (`up -d --no-build`). **Not touched:** PostgreSQL, vLLM and every model, transcription, the semantic router, SearXNG, Caddy, the model manager and the robot. PgBouncer was restarted once (below).
- **Flags:** the only knowledge variable in the core environment is `KNOWLEDGE_INDEXING_ENABLED=false`; none of `KNOWLEDGE_RETRIEVAL_ENABLED`, `KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED`, `KNOWLEDGE_SELECTIVE_SHADOW_ENABLED`, `MEMORY_CANDIDATES_ENABLED`, `MEMORY_CANDIDATES_CAPTURE_ENABLED` is set in core or hub. Compose and `.env` were not changed.

## Preflight (before anything stopped)

Revision 027; PostgreSQL accepting connections (11 MB database); 206 GB free; core, hub, coding-agent, PgBouncer, vLLM, Caddy running; no meeting in progress (one `complete`), no pending reminder, no pending confirmation; the only scheduled alarm was a stale 2026-10-07 test alarm. Counts: 3 notes, 8 alarms, 1 meeting, 0 memories/tasks/reminders, 81 index rows, 2 outbox rows, 9 receipts.

## Timeline (host clock, UTC) and downtime

| Time | Event |
|---|---|
| 10:49:47 | core, hub and coding-agent stopped (outage begins) |
| 10:50:05 | first migrate attempt **refused**: "Stop hub/core and other database clients before upgrading". Cause: PgBouncer's own idle pooled server connection (it would have closed itself after the 300 s idle timeout). Nothing changed in the database |
| 10:50:33 | PgBouncer container restarted with all applications stopped (released the connection; healthy within seconds) |
| 10:50:40 to 10:50:43 | migration applied: revision 028 |
| 10:50:47 to 10:50:52 | the three services recreated and started; hub answering by 10:50:51; core "application startup complete" |

**Downtime of core, hub and coding-agent: about 1 minute 5 seconds** (10:49:47 to about 10:50:52). A first compose invocation also failed on `SEARXNG_SECRET_KEY` (normally exported by `scripts/start-homelab.sh`); the secret was read from the existing `.env.searxng-secret` for the migrate and up commands. No data change resulted from either deviation.

## Verification on the running production stack

| Check | Result |
|---|---|
| Revision, tables | `028_memory_candidates`; the three candidate tables and the unique index present; 0 candidate rows; `knowledge_items` still 81 |
| Service status | core, hub, coding-agent up on the new image ids, 0 restarts, 0 tracebacks/exceptions in their logs; PgBouncer, PostgreSQL, vLLM, Caddy healthy; 4 database connections |
| Chat | "What is the capital of France?" answered by the 7B: "The capital of France is Paris." |
| Handlers | "what are my tasks?" "You have no open tasks."; "what alarms do I have?" listed the existing alarm; the 44H boundary still returns its fixed reply to "Delete all my memories"; a candidate-shaped sentence ("I prefer written summaries...") got an ordinary model reply and created **no** candidate (capture off) |
| Meetings | `/meetings` lists the 1 existing meeting; notes list 3, alarms 8 (unchanged) |
| Memory | create, recall (1 hit), two-step forget confirmation (soft delete): all 200 |
| Reminder | create then delete: 200 / 200; 0 reminders afterwards |
| Alarm | create then delete: 200 / 200 (the create writes the usual `alarm.created` receipt) |
| New flags OFF | `GET /memory-candidates` on core with the service token: **404** (route not registered); the knowledge index and outbox are not being processed |
| Unauthorised access | core `/memories` and `/memory-candidates` without the service token: 401. Hub (direct and through Caddy `/hub`): `GET /memory-candidates`, `POST .../accept`, `.../reject`, `.../forget-conversation`, `GET /privacy/state` with no login: **401**; `GET` and `POST` memory-candidate routes with the `REMOTE_UI_TOKEN` bearer alone: **401**; `/privacy/state` with a wrong bearer: 401 |
| React app | `/hub/web/` serves (200); the production bundle `assets/index-ClkXyyhJ.js` (200) contains the Memory page and its API calls |
| Privacy-state read | `GET /privacy/state` with the bearer: `{"privacy_mode": true, "robots": 1}` (the registered robot is not armed, so privacy mode reads on). Read only; the robot was not contacted |

**Not verified (needs the owner):** the Memory page rendered in a logged-in owner browser (it needs the owner's login; with the flag off the page shows its empty or unavailable state), Telegram receipt, voice, and any robot behaviour. No robot, model, voice or Telegram action was performed.

## Residue of the checks (disclosed)

One soft-deleted (forgotten) test memory row; two new knowledge outbox rows (the memory insert and forget; indexing is off, they stay queued; outbox now 4); two audit receipts (receipts are append-only: `alarm.created` and the alarm deletion's receipt); a cancelled test alarm row and a deleted reminder. Conversation probe sessions `p44-*` live in core's memory only until restart.

## Rollback state (preserved)

- **Images:** `reachy-rollback/companion-core:027-pre-phase44-028` (`3c1d48c3c873`), `reachy-rollback/reachy-hub:027-pre-phase44-028` (`a61de4d26f19`), `reachy-rollback/coding-agent-service:027-pre-phase44-028` (`1f53a503a015`), `reachy-rollback/migrate:027-pre-phase44-028` (`368b27865459`); earlier rollback tags are untouched.
- **To roll back** (the previous images refuse revision 028, so the schema step comes first): stop core, hub and coding-agent; restart PgBouncer if it holds an idle connection; `docker exec -i reachy-homelab-postgres-1 psql -U reachy -d reachy_hub -v ON_ERROR_STOP=1 --single-transaction < deploy/homelab/rollback-028.sql` (the last line must print `027_knowledge_index`; accepted memories, if any existed, stay); retag the four `:027-pre-phase44-028` images to `:latest`; `docker compose -p reachy-homelab --env-file .env up -d --no-build companion-core reachy-hub coding-agent-service`. **No database backup exists for this deployment (waived by the owner)**; rollback loses nothing except the candidate bookkeeping tables, which are empty.

## Status

**Phase 44 is DEPLOYED with every new feature disabled, pending activation.** Activation of anything (indexing, retrieval, selective answering, shadow, candidate capture) remains the owner's separate decision and is subject to the operational prerequisites in the [closure report](../phase-44-closure-report.md) (backup and capacity items were waived for this deployment only, not for indexing the owner's real records).
