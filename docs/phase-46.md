# Phase 46: least-privilege database roles (plan)

Status: **plan written 2026-10-08. No role, credential, configuration or deployment change has been made, and none is authorised yet.** Opened as the first priority after the [Phase 45 pooling cutover](phase-45.md) was accepted at the infrastructure level. Phase 44 (knowledge indexing and retrieval) stays disabled and paused until the remaining acceptance and performance gates are reviewed.

## 1. Goal

No application connection runs as a PostgreSQL superuser. Each service can reach only its own tables; schema changes need a separate owner identity; PgBouncer has its own administrative and statistics identities that cannot reach the data; and the superuser remains for break-glass administration only.

Requested scope (owner, 2026-10-08): (1) distinct application roles for core, hub and coding-agent; (2) a migration owner role with schema-change privileges; (3) a dedicated PgBouncer administrative and statistics identity; (4) removal of superuser and administrative privileges from application identities; (5) regression testing of all source stores, migrations, triggers and indexing paths.

## 2. Current state (read-only inspection, 2026-10-08)

- One login role, `reachy`: superuser, createrole, createdb (the container's bootstrap role, `POSTGRES_USER`). It owns every object. It is used by core, hub, coding-agent, the `migrate` job, key rotation, `pg_dump`, the PgBouncer auth file and PgBouncer's `admin_users`/`stats_users`, and by `make-userlist.sh` (which reads `pg_authid`, a superuser-only catalog).
- 41 tables in `public`. Static inventory of the SQL in each service (migrations excluded): **core 27** (`action_receipts`, `alarms`, `calendar_events`, `coding_agent_notifications`, `confirmation_requests`, `document_chunks`, `email_drafts`, `email_received`, `google_accounts`, `google_oauth_states`, `google_reminder_delivery`, `knowledge_items`, `knowledge_outbox`, `llm_config`, `llm_usage_log`, `meeting_terms`, `meetings`, `memories`, `notes`, `persona_config`, `reminders`, `search_config`, `search_provider`, `search_usage`, `secrets`, `stations`, `tasks`); **hub 9** (`audit_log`, `notification_queue`, `robot_wake_arm`, `robots`, `sessions`, `telegram_chats`, `users`, `web_chat_turns`, `web_chats`); **coding-agent 4** (`coding_agent_events`, `coding_agent_projects`, `coding_agent_sessions`, `coding_agent_usage_snapshots`). The static scan is a starting point; 46B must confirm it with the tests, because a regex can miss dynamically built SQL. `alembic_version` is read by every service's start-up schema check.
- Extensions `vector` and `plpgsql`. The `knowledge_*_trg` triggers call `knowledge_enqueue`, which is **not** `SECURITY DEFINER`: it runs with the privileges of whoever writes the source row, so under least privilege every writer of a source table would need direct rights on `knowledge_outbox` unless the function is redefined as `SECURITY DEFINER` (owned by the owner role, with a fixed `search_path`). That is a design decision for 46B.
- Migrations take a session-level advisory lock and run on the direct path. Creating an extension needs a superuser (pgvector is not a trusted extension), so any future migration that adds one needs a break-glass step; the table-changing migrations do not.

## 3. Target role model

| Role | Login | Purpose and privileges |
|---|---|---|
| `reachy` (existing superuser) | local socket only | Break-glass administration, restores, extension creation, `pg_authid` reads. Not used by any service. Network logins rejected in `pg_hba.conf`. |
| `reachy_owner` | no | Owns the schema objects (tables, sequences, functions). Never logs in. |
| `reachy_migrate` | yes | Member of `reachy_owner`; used only by the migration job and key rotation. Can create, alter and drop objects, and grant. No superuser. |
| `reachy_core` | yes | SELECT/INSERT/UPDATE/DELETE on the 27 core tables, sequence usage, SELECT on `alembic_version`. No other tables, no DDL, no TRUNCATE, no catalog or admin functions. |
| `reachy_hub` | yes | Same, for the 9 hub tables. |
| `reachy_agent` | yes | Same, for the 4 coding-agent tables. |
| PgBouncer admin and stats identities | no (PgBouncer-only) | Entries in the PgBouncer auth file that exist only for its `pgbouncer` console database (`admin_users`, `stats_users`); they have no PostgreSQL role and cannot reach any data. The application roles stop being console users. |

Default privileges are set for `reachy_owner` so new migrations grant the right service automatically.

## 4. Consequences to design for

- **PgBouncer pools are per database and per user.** Three application roles mean three server-side pools. With `default_pool_size` 20 each, the cap becomes 60 plus the migrate role, which breaks the budget. 46D must set per-user pool sizes (about 8 to 10 each, reserve 3) and `max_db_connections` so the total stays well under 100; the measured peak of 13 server connections shows the room.
- **Auth file.** `make-userlist.sh` must write one SCRAM verifier line per role (it reads `pg_authid`, so it runs as the superuser through the local socket) and add the console identities. Passwords come from restricted, gitignored files and are never printed.
- **Triggers and the outbox.** Decide `SECURITY DEFINER` (preferred: one narrow function, fixed `search_path`, owned by `reachy_owner`) against granting `knowledge_outbox` writes to every source writer. Test both the normal write path and a revoked-privilege negative case.
- **Cross-service isolation.** The hub and coding-agent must be unable to read `secrets`, `google_accounts`, `llm_config` or any core table; core must be unable to read `users` or `sessions`.
- **Backups and restores.** Dumps run as the superuser through the local socket. A restore into a fresh server needs the roles created first (or `--no-owner --no-acl` followed by re-granting); the recovery runbook and the 027 rollback SQL (`rollback-027.sql`, run by the owner) must be updated and tested.
- **Rollback.** The superuser path stays available throughout. Reverting is changing the three `DATABASE_URL` users back and removing the new auth-file lines; the schema and data do not change.

## 5. Stages (each on disposable infrastructure first)

| Stage | Work | Evidence |
|---|---|---|
| 46A | This inventory and design, reviewed by the owner. Confirm the table lists with an instrumented run (log which relations each service touches under the full test suite). | Reviewed plan; measured table lists per service. |
| 46B | A role-creation script (not a schema migration, because it needs secrets and runs as superuser) plus a migration that sets ownership, grants, default privileges and the `SECURITY DEFINER` function. Idempotent. | Applies to a fresh database and to a restored production copy; re-runs cleanly. |
| 46C | Test harness: each service's Postgres-backed suite runs with its own role's DSN (core, hub, agent) and the migration suite with `reachy_migrate`. Negative tests: cross-service reads and writes fail; DDL, `COPY PROGRAM`, `pg_authid` reads, `pg_terminate_backend`, `CREATE EXTENSION` fail for application roles. | All suites pass; every negative test fails closed. |
| 46D | PgBouncer: per-role auth file, per-user pool sizes, `max_db_connections`, separate console identities; connection budget measured again at rest and under the 32-worker load. Compatibility matrix repeated per role. | Peak backends within the Phase 45 targets; no queueing regression. |
| 46E | Rehearsal on a restored production copy in an isolated network: migrate-as-owner from the current revision, run the three services as their roles, indexing worker and reconciliation (with the flag on, in the disposable copy only), document ingest and vector search, meeting claims, outbox leases, key rotation, dump and restore. | A dated verification record; any failure fixed before a production plan exists. |
| 46F | Production cutover plan (runbook, rollback, backups, downtime), for separate owner approval. Not authorised. | Owner decision. |

## 6. Regression coverage required (scope item 5)

Every source store (memory, documents, meetings, notes, tasks, reminders, alarms, planner receipts, persona, LLM settings and usage, web search, email, calendar, consent, accounts, coding-agent notifications and sessions, hub chat, sessions, users, audit, notification queue, wake-arm, robots, Telegram chats), the migrations from an empty database to head and the 026/027 upgrade and downgrade paths, legacy adoption, key rotation, all six knowledge triggers, the outbox claim, lease and reconciliation paths, the indexing worker, index upsert and delete, and retrieval-time revalidation reads. The existing suites already cover most behaviour; the new work is running them under the restricted roles and adding the negative cases.

## 7. Open decisions for the owner

1. Keep the bootstrap role named `reachy` as the break-glass superuser (proposed; renaming it is invasive) and create new names for the others.
2. `SECURITY DEFINER` function for the outbox (proposed) or direct grants.
3. Whether the knowledge indexer should later get its own role (it runs inside core today, so it shares `reachy_core`).
4. Acceptance of the proposed `pg_hba.conf` rule rejecting network logins for the superuser, which needs a one-time change to the PostgreSQL data directory and a reload.

## 8. Not in scope

Credential changes, role creation on the homelab, another production deployment, row-level security, encryption at rest, replacing PostgreSQL, and any Phase 44 functionality.
