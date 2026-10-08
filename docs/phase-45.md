# Phase 45: Database connection architecture and pooling

Status: **audit, plan and disposable-infrastructure implementation done 2026-10-08 (see section 8); nothing changed on the homelab.** Opened by owner decision on 2026-10-08, after the Phase 44B indexing trial exhausted PostgreSQL's connection limit ([trial record](verification/phase-44b-indexing-trial-2026-10-08.md)). Phase 44 work (44E, 44F, further indexing trials) waits for this phase to reach a stable database layer.

## 1. Owner decisions (2026-10-08)

| # | Decision |
|---|---|
| D1 | Reachy is a development and personal-use system with one developer who is also its only user. Prefer the right long-term architecture over minimal change or short-term uptime; planned downtime and refactoring are acceptable. |
| D2 | Target: one shared, process-scoped Psycopg `AsyncConnectionPool` per application service, injected into its stores; PgBouncer as the common intermediary (transaction pooling where compatible); direct PostgreSQL access reserved for migrations, key rotation, maintenance and emergency recovery; explicit budgets, lifecycle, bounded queueing and reconnection. |
| D3 | Benchmark shared pools alone against shared pools plus PgBouncer and choose by evidence; complexity is not a goal. |
| D4 | Disposable infrastructure first; the homelab only after the result is reviewed and a coordinated cutover is approved. |
| D5 | Data integrity is not negotiable: no loss of meeting recordings, encryption keys, credentials or durable memories. Verified backups before cutover; no volume is deleted. |
| D6 | PostgreSQL stays (with pgvector). No new Phase 44 functionality during this phase. |
| D7 | Acceptance targets are provisional: fewer than 15 idle backend connections, fewer than 40 under representative workloads, no functional regression, no unbounded waiting or silent transaction loss, automatic recovery after intermediary restart, migrations and key rotation independent of PgBouncer. |

## 2. Why: what was measured (read-only, 2026-10-08)

The homelab PostgreSQL has `max_connections = 100` (`superuser_reserved_connections = 3`). `pg_stat_activity` grouped by client address:

| Service | Connections | State | Why |
|---|---|---|---|
| companion-core | 56 | idle | 14 store pools of 4 |
| reachy-hub | 32 | idle | 8 store pools of 4 |
| coding-agent-service | 4 | idle | 1 pool of 4 |
| background workers and a monitoring session | 5 | n/a | server processes |

The library default (`min_size = 4`, `max_size` equal to it) is a fixed 4 per pool, and each store class builds its own pool, so the stack holds 92 connections at rest and 93 to 98 with a monitoring session. Nothing else on the host connects. The 44B indexer added two pools (8 connections) and hit the limit.

Actual need is far lower. A read-only GET burst through the hub (8 and 32 concurrent workers, 40 s each, 15,000 requests per run, `pg_stat_activity` sampled every 100 ms on one connection) peaked at **9 simultaneously busy (active or idle in transaction) connections for core, 7 for hub and 1 for coding-agent**, out of 56, 32 and 4 held. At rest none were busy.

A rehearsal on a restored production copy with isolated containers (current images, default pools) reached 101 client connections with the indexer on, reproducing the incident. The interim pool helper below (images built from `37c5d0d`) held 52 connections at rest and 60 at peak under 8 and 32 concurrent readers plus 2 to 4 incremental writers. That run's indexer could not load the embedding model (the rehearsal network had no internet and no Hugging Face cache), so it shows the connection effect of the helper but not a working indexer; this evidence is superseded by 45D. The core container has no volume for the Hugging Face cache, so it fetches the model into its writable layer after each recreate; an item for 45E.

## 3. Audit of the code (2026-10-08)

**Pool creation.** 25 sites (16 in core including the two 44B knowledge pools, 8 in the hub, 1 in coding-agent), all `AsyncConnectionPool(dsn, open=False)` inside a store's `connect(dsn)` classmethod. Core: coding-agent notifications, planner, persona, LLM settings, LLM usage, calendar, consent, tasks, email, accounts, RAG documents, web search, memory, meetings, plus the 44B knowledge index and outbox. Hub: chat, wake-arm, Telegram chat registry, audit log, notification queue, robot registry, sessions, users. Coding-agent: its session store. Each store takes the pool in its constructor already (`cls(pool)`), so injection needs no change to query code. Each pool is bound to the event loop that opened it. Stores are opened one by one in the FastAPI lifespan of each service and closed one by one on shutdown; the knowledge indexer opens its own.

**Other connections.** `migrations/__main__.py` (SQLAlchemy and psycopg, `SET LOCAL lock_timeout/statement_timeout`), the legacy adoption path, key rotation (`secrets.py`, transactional with `FOR UPDATE`), and the email sender (a short-lived connection). These are the direct-path candidates.

**Constructs that matter under transaction pooling.**

| Construct | Found | Consequence |
|---|---|---|
| Session-level `SET` / `set_config` / `RESET` | none; every `SET` is `SET LOCAL` inside a transaction (retrieval's `hnsw.iterative_scan` and `ef_search`, account locks, migrations) | Safe under transaction pooling. A rule and a test must keep it that way. |
| Advisory locks, `LISTEN`/`NOTIFY` | none in application code | Safe. Forbidden through the pooler by rule. |
| Temp tables, `WITH HOLD` or named cursors, `PREPARE` | none | Safe. |
| `SELECT ... FOR UPDATE [SKIP LOCKED]` inside a transaction | meetings queue claim, outbox leases, alarms, accounts, LLM and persona config, chat, key rotation | Safe: the lock lives in one transaction. Leases are rows (`locked_until`), not connection state. |
| Server-side prepared statements | Psycopg 3 prepares a statement after 5 executions (`prepare_threshold = 5`) | Breaks transaction pooling unless PgBouncer supports protocol-level prepared statements (1.21 and later with `max_prepared_statements`) or preparation is disabled. Must be decided and tested in 45C. |
| pgvector adapter | `configure=register_vector_async` on the RAG and knowledge pools | Per-connection type registration. A shared pool must register it for every connection, or those two stores keep a distinct pool. |
| Transactions across awaits | `conn.transaction()` used in accounts, chat, outbox, index, search | Connections are held for the transaction's duration only; verify nothing holds one across a model call (45A). |
| Session state assumed by tests | tests open pools on the test's own loop | Injection makes tests simpler, not harder. |

**Two behaviours to preserve.** The schema check (`check_schema`) runs at start-up per store; with injection it runs once per service. Core and hub refuse to start on a revision mismatch; that stays.

## 4. Target architecture

```
Companion Core ── one shared AsyncConnectionPool ──┐
Reachy Hub ────── one shared AsyncConnectionPool ──┼─> PgBouncer (transaction pooling) ─> PostgreSQL + pgvector
Coding-agent ──── one shared AsyncConnectionPool ──┘            ^
Migrations, key rotation, maintenance, recovery ── direct ──────┘ (never through PgBouncer)
```

- **`DatabaseManager`** (in `shared/`): owns one pool per service process, `start()` / `stop()`, schema check once, optional vector registration, sized by configuration; the only code allowed to construct a pool (the existing guard test generalises to it). Stores receive the pool, or a thin handle, and never open or close it. Component-specific exceptions (a dedicated pool for a long-running worker) are explicit and justified in code.
- **Budget.** PgBouncer's server-side pool for the application user is the one number that bounds PostgreSQL connections; client-side pools can be larger because PgBouncer queues for them. Starting proposal, to be tuned in 45D: PgBouncer `default_pool_size` 20, `reserve_pool_size` 5, `max_client_conn` 200, `server_idle_timeout` and `query_wait_timeout` set so waiting is bounded; per-service app pools `min_size` 1, `max_size` 8 for core and hub, 3 for coding-agent. Direct administrative sessions use the reserved slots.
- **Lifecycle.** Pools close on shutdown, `check` on checkout so a restarted intermediary heals itself, `max_lifetime` and `max_idle` bounded, acquisition `timeout` explicit (seconds, not the 30 s default silently), errors surface as clear failures rather than hangs.
- **Direct path.** `DATABASE_ADMIN_URL` (or the existing `DATABASE_URL` for those jobs) goes straight to PostgreSQL for `migrate`, key rotation and recovery; application services use `DATABASE_URL` pointing at PgBouncer. Authentication from PgBouncer to PostgreSQL uses SCRAM, with the secret kept in a permission-restricted, gitignored file like the other credentials.

## 5. Stages

| Stage | Work | Evidence and gate |
|---|---|---|
| 45A | Audit (this page), then refactor: `DatabaseManager`, stores take an injected pool, one pool per service, ordered start and stop in each lifespan, indexer on the shared pool, guard test that nothing else constructs a pool. The interim `connection_pool` helper (commit `37c5d0d`, 1 idle and at most 3 per pool, tunable by `DB_POOL_MIN_SIZE` and `DB_POOL_MAX_SIZE`) stays as the guard until this lands. | All three service suites pass; Postgres-backed store tests pass on a disposable server; connection counts measured at rest and under load; shutdown closes every connection (checked in `pg_stat_activity`). |
| 45B | PgBouncer in the homelab Compose file: version-pinned image (digest recorded), config under `deploy/homelab/`, credentials in a restricted file, health check, no host port, resource limits. Application services stay on direct PostgreSQL until 45E. | `docker compose config` clean (without printing it), stack starts in a separate project name, PgBouncer authenticates and proxies, `SHOW POOLS` and `SHOW STATS` readable by an admin user. |
| 45C | Compatibility tests through PgBouncer in transaction mode on a disposable stack: Psycopg 3 prepared statements (either PgBouncer's protocol support or `prepare_threshold = None`, chosen by test), pgvector registration and an HNSW query with `SET LOCAL`, outbox leases with `SKIP LOCKED` from two workers, meeting claims, notification claims, memory and meeting transactions, alarm claim-once semantics, key rotation and migrations confirmed to use the direct path. | A test matrix with one pass or fail per construct in section 3; any failure either fixed in code or keeps that construct off the pooler, recorded. |
| 45D | Benchmark shared pools alone against shared pools plus PgBouncer on a restored production copy and a synthetic load: backend connections over time, acquisition latency (p50, p95, max), request latency, throughput, queueing and timeouts, CPU and memory of PgBouncer, with the indexer working (embedding model available) and incremental writes. | A table of both configurations against the provisional targets in D7; the decision rule is written before the run: PgBouncer is adopted only if it meets the targets and the shared pool alone does not, or it is clearly better on headroom without a compatibility or latency cost. |
| 45E | Select the winning configuration and cut over the homelab in one coordinated, approved window: verified dump and keyring copy first, rebuild images, switch the services' `DATABASE_URL`, keep migrations direct, repeat the smoke tests of the 44B deployment, then restore the Phase 44 indexing trial plan. Also give core a volume for the model cache. | Deployment record with downtime, backup checksum, rollback readiness (old images and `DATABASE_URL` retained), connection counts at rest and in use. |
| 45F | Failure exercises on the disposable stack, then confirmed on the homelab only as far as the owner allows: PgBouncer restart, PostgreSQL restart, connection exhaustion (more clients than the budget), a rolled-back transaction, a killed backend mid-transaction, PgBouncer unavailable at service start. | Services recover without manual action; no unbounded waits; no silent loss of a committed or acknowledged write; failures are logged with a clear cause. |

## 6. Data safeguards

Before any cutover: a verified `pg_dump` restored into a throwaway database (as for 026 and 027); the credential and coding-agent key files copied to an off-host location the owner chooses (still open from 44A); the meeting-audio and other Docker volumes untouched; PostgreSQL's volume never removed or recreated. Rehearsal copies of production data live in a 0700 directory on an internal Docker network and are shredded after use. Every change is reversible by restoring the previous images and `DATABASE_URL`.

## 7. Out of scope

Replacing PostgreSQL, read replicas, high availability, sharding, and any Phase 44 functionality. Raising `max_connections` is not needed by this design and is not planned; if the evidence shows a need it is a separate decision.

## 8. Status, results and recommendation

Status 2026-10-08: **45A, 45B (repository artifacts only), 45C, 45D and 45F are done on disposable infrastructure; 45E (homelab cutover) awaits the owner.** Evidence: [verification record](verification/phase-45-2026-10-08.md). Summary: shared pools alone bring the stack to 12 to 13 backends at rest and 24 under load (92 and 98 today, 101 with the indexer); adding PgBouncer brings it to 8 and 18 with a hard cap, no measurable latency cost, every compatibility case passing, and recovery from PgBouncer and PostgreSQL restarts without manual action and without losing an acknowledged write. Both meet the provisional targets.

Recommendation for 45E, applying the rule written in section 5 (PgBouncer is adopted only if it clearly improves headroom at no compatibility or latency cost): **adopt shared pools and PgBouncer together**, with `DB_PREPARE_THRESHOLD=off` and PgBouncer `max_prepared_statements = 100`. The honest margin is modest at today's single-user load (24 against 18 backends, both far inside 100); the case for PgBouncer is the hard cap and the absorption of future workers, at the price of one more container that must be up for the applications to start. If the owner prefers the smaller system, shared pools alone are sufficient and the pooler stays in its profile.

Two bugs found on the way are fixed (the row-factory leak, `37cef0b`) or recorded (applications run as the superuser; the core has no model-cache volume). Phase 44 stays paused at the 44B production state (revision `027_knowledge_index`, `KNOWLEDGE_INDEXING_ENABLED=false`, 80 index rows, retrieval off, plans for 44E and 44F retained). The homelab runs the old images with the old pools; nothing from this phase is deployed.

## 9. Cutover plan for 45E (for approval, nothing started)

1. Verified `pg_dump` restored into a throwaway database; keyring files copied off-host by the owner; volumes untouched.
2. Build images from a clean worktree of the pinned commit; tag the running images `reachy-rollback/*:027-pre45`.
3. Run `./pgbouncer/make-userlist.sh`; start `pgbouncer` (`--profile pooler`); check `SHOW POOLS`.
4. Stop core, hub, coding-agent; set `DB_HOST=pgbouncer`, `DB_PORT=6432`, `DB_PREPARE_THRESHOLD=off` in `.env`; `up -d` the three; migrations still run direct.
5. Smoke tests as for 44B plus a connection time series (idle under 15, load under 40) and the failure probe against the live stack with the owner's approval of each fault.
6. Rollback: unset the three variables and `up -d` (the applications reconnect directly); old images retained.
