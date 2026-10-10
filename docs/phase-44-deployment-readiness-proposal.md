# Phase 44E: deployment-readiness proposal (selective-shadow design, unrecognised-request safeguard, production-indexing gate) — PROPOSAL, 2026-10-10

**Status: decisions recorded in section 7 (owner, 2026-10-10); this page is otherwise a proposal. Nothing here is implemented, deployed, migrated, indexed or activated.** The integration it builds on is committed and pushed (`b34d366`; [record](verification/phase-44e-selective-integration-2026-10-10.md)). Both feature flags stay OFF by default and are not added to production Compose in this step. 44F, dev16 and scorer work are untouched.

## 1. Requirements carried into deployment readiness

| # | Requirement | State today | Proposed work |
|---|---|---|---|
| 1 | An unrecognised personal-knowledge request must not get a fabricated personal answer from the ordinary LLM fallback | **Open.** With the flags on, a request that qualifies as a personal-knowledge question but that B-1 cannot type still reaches the model with no records | section 2 |
| 2 | Zero retrieved evidence means the records checked did not establish the fact, not global absence | Partly: B-1's frozen wording is "The records do not say …" / "The records I searched do not mention …" | section 3 |
| 3 | Restricted evidence completely invisible to unauthorised channels, including citation numbering, errors, response metadata | Met in tests: B-1 only receives revalidated records; markers renumbered by order of appearance; one failure wording for every failure kind; privacy label is the maximum over cited records only; logs and counters are numbers; replies byte-identical with and without a restricted record (text and voice). The shadow design below keeps it | section 4 (carry into shadow) |
| 4 | 44H action boundary and fail-closed retrieval | Met and tested (the boundary precedes the branch; eligible failures give the fixed reply, zero model answer calls) | unchanged |
| 5 | Flags OFF by default, not in Compose | Met (defaults false; Compose passes neither) | unchanged |

## 2. Smallest conservative safeguard for unrecognised personal-knowledge requests (outside frozen B-1)

**Rule (adapter only; B-1 untouched).** When both flags are on, a request that `qualify()` accepts as a personal-knowledge question, is not claimed by an earlier handler or the 44H boundary, but that the B-1 decomposer cannot type (or that needs structured attendance data) gets one **fixed reply and no model call**, handler `knowledge.selective_unrecognised`: *"I can't check your records for that kind of question yet, so I haven't answered it from them."* It claims neither presence nor absence and no action. Everything else is unchanged: status questions stay with the deterministic handlers, general and world questions still reach the model, and with the flags off nothing changes.

**What it would have done, measured offline on the existing qualification sets** (invented corpus vocabulary; descriptive, not a validation; 5 labelled sets, 97 personal-knowledge and 94 other questions):

| Group | Count | Today with flags on | With the safeguard |
|---|---|---|---|
| personal-knowledge, B-1 types it | 13 (13%) | cited deterministic answer | same |
| personal-knowledge, B-1 cannot type it | 71 (73%) | **ungrounded model answer** | fixed reply, no model |
| personal-knowledge, status question | 10 (10%) | deterministic handlers | same |
| personal-knowledge, missed by `qualify` (no anchor) | 3 (3%) | model | **still model** (residual) |
| other (general chat or world), wrongly accepted by `qualify` | 11 of 94 (12%) | model answer | fixed reply (**cost**: a legitimate answer is withheld) |

**Trade-off.** It removes the fabrication path for roughly 85% of personal-knowledge questions the model would otherwise answer without records, at the price of a fixed reply on about 1 in 8 non-personal questions that `qualify` misreads as personal. It cannot reach a personal question with no recognisable anchor (an unknown term, no first-person or record noun); that residual remains and can only be narrowed by the shadow's measurements and by a better anchor vocabulary, not by this safeguard. Tests to add when approved: fixed reply with zero model calls for each unrecognised case; flags-off identity; general chat unchanged; the counter `unrecognised_personal` by category; the false-catch rate re-measured on a fresh general-chat set before enablement.

## 3. Zero evidence is not global absence (wording)

Frozen B-1 text is not edited. Proposed adapter-level addition, only to a reply that cites nothing and whose claims are all "not established": append a fixed sentence *"That is only what the records I could check show."* (text and voice). Tests: appears exactly on zero-citation not-established replies, never on cited answers or conflicts, identical with and without a restricted record present. Owner approval of the wording is needed.

## 4. Selective shadow-mode design (not implemented)

**Purpose.** Learn, on the owner's real traffic and records, how often a question is eligible, what the deterministic path would do, and how often it would fail, without ever releasing an answer or changing a reply.

**Shape.** A second measure-only observer beside the existing retrieval shadow, same pattern (`knowledge/shadow.py`): off unless `KNOWLEDGE_SELECTIVE_SHADOW_ENABLED=true` (new, default false, requires `KNOWLEDGE_RETRIEVAL_ENABLED` and a log path, otherwise stays off with one warning; not added to Compose). After the production reply is final, a snapshot of plain data (session id, text, modality, privacy label, production handler category, attached-meeting flag) is offered to a bounded queue (one job at a time, short queue, drop-oldest, per-job timeout, never on the request path). The job runs the **same** `eligible()` and `_answer()` as the live path against the **same trusted `AccessContext` derived from that turn's modality** (a spoken turn is public only), through the existing `Retriever` and revalidation. The result is reduced to categories and discarded: no text, title, id, citation, query or reply is kept, logged or returned. Nothing it computes can reach a prompt, reply, consent state, draft, memory, task, alarm or the robot, and the live selective path is untouched (shadow may run with the answerer off).

**Metrics (aggregate counts and bucketed histograms per hour; no per-turn rows).**
- funnel: attempted, skipped (slash, sensitive-labelled turn, empty), ineligible by reason (`not_knowledge`, `status_question`, `not_understood`, `needs_structured_data`, `attached_meeting`), eligible;
- eligible outcomes: answered by state (supported, historical, conflicted, unsupported, negative, ordering), citation-count bucket, maximum cited sensitivity (public or work-private only, never finer), would-be-unrecognised (section 2);
- bounded error categories: `timeout`, `retrieval`, `not_ready`, `pipeline`, `verify` (invalid citation: must be 0), `dropped_busy`, `discarded_at_stop`;
- comparison with production by category only: would the deterministic path have replaced a model reply, a handler reply, or nothing (3 values);
- latency buckets; queue depth; revalidation-dropped total (a count, never a reason per record).

**Privacy and trust.** A lower-trust channel never causes a higher-trust retrieval, even internally: access comes only from the turn's modality, exactly as live. Restricted records never reach B-1; counters contain no per-record information, so existence cannot be inferred from them beyond one aggregate number kept in the owner-only operator log. Telemetry file is owner-readable only (mode 600), retained 30 days by the existing retention mechanism, deletable to remove everything.

**Tests to write when approved.** Foreground replies, prompts, model calls and database state identical with the shadow on and off (real PostgreSQL lifespan); no field of any record or reply in the telemetry (schema allow-list test, as for the existing shadow); voice turns never retrieve above public; saturation, timeout and database-fault isolation; clean shutdown and restart continuity; the funnel reconciles.

**Exit criteria for the window (proposal).** At least 50 eligible-qualifying turns over at least 14 days; `verify` errors 0; failure categories below an owner-set rate; eligible and unrecognised rates reported; latency p95 within the owner's limit. Answer **quality** is deliberately not assessable from content-free telemetry; it is assessed in the later supervised owner window (gate step 5 of the [integration record](verification/phase-44e-selective-integration-2026-10-10.md#4-proposed-controlled-deployment-gate-for-owner-review-nothing-here-is-authorised)).

## 5. Operational gate for production indexing (nothing run)

Context: migration 027 is applied; indexing is off; the 2026-10-09 trial indexed **one** note (index 80 to 81 rows), took 13 s for a cold MiniLM load plus one item, held core at about 600 MB, and used 10 to 11 of 100 PostgreSQL connections with no PgBouncer waiting. No real-data backfill has been run; the trial did not measure a bulk load.

| Area | Gate (all must be met and recorded before enabling `KNOWLEDGE_INDEXING_ENABLED` for a backfill) |
|---|---|
| **Backups** | Fresh `pg_dump -Fc` through `docker exec` into `~/reachy-backups` (mode 0700 directory, 0600 file, `umask 077`) immediately before the backfill; sha256 recorded; `pg_restore -l` lists the knowledge tables; per-table row counts taken before. The existing backup runbook ([deployment](deployment.md#upgrades-and-verification-cleanup)) is the procedure. |
| **Isolated restore** | The dump is restored into a **separate disposable container** (never the live database or its volume), row counts compared with the pre-backfill counts, `verify` run against the restored copy, and the restore time recorded as the recovery estimate; container removed afterwards. |
| **Connection limits** | Record PostgreSQL `max_connections` (100 in the trial), PgBouncer pool sizes and core's `DB_POOL_MAX_SIZE` (8 by default) before; the indexer must add no pool of its own beyond the shared bound plus the worker's measured one or two connections; abort on the derived ceilings in section 7. |
| **Worker contention** | Backfill in bounded batches with the existing 2 embedding threads (`KNOWLEDGE_EMBED_THREADS`), at a quiet time, owner present; watch health latency of core, hub and vLLM (ceiling derived in section 7), CPU, memory (ceiling derived in section 7) and the outbox backlog; no concurrent model-manager or meeting-transcription load; a hard cap on rows per session at first (proposal: the owner's current record count only, no new sources). A warm per-item latency is not yet measured; measure it on the first small batch and extrapolate before the full run. |
| **Consistency** | After the run: read-only `verify` shows 0 missing, 0 extra, 0 stale, 0 wrong-model, 0 orphans; outbox empty; no failed or retried row; embeddings all 384 wide; sensitive-tier records indexed with their labels and absent from every lower-ceiling retrieval (the existing retrieval-time revalidation probe). |
| **Rollback** | Unset the flag and recreate core (about 30 s, as in the trial). The index is derived and rebuildable; to remove it entirely, the pre-backfill dump restores the database. Both rehearsed on the disposable restore first. Retrieval and selective answering stay off throughout indexing. |
| **Stop rule** | Any abort condition, a failed outbox row, or any unexplained error stops the work; no resume without an owner decision. |

## 6. Decisions requested

1. Approve the section 2 safeguard (wording and the 85% / 12% trade-off), or choose to leave unrecognised requests on today's path with the residual risk stated.
2. Approve the section 3 wording.
3. Approve implementing the selective shadow as designed (a separate decision; then its tests and a local verification record).
4. Approve the section 5 gate, with owner-set ceilings for connections, memory and latency.
5. Commit and push this proposal.

## 7. Owner decisions of 2026-10-10 and how they amend this proposal

- **D1 (replaces section 2).** No blanket fixed refusal; flag-OFF behaviour preserved. Shadow-only classification and outcome counters (typed, untyped, ambiguous, ineligible) are implemented locally ([record](verification/phase-44e-selective-shadow-2026-10-10.md)). Record-dependent but untyped questions are a recorded safety concern for any future activation; a narrower safeguard is proposed only after representative routing evidence. The LLM is never used to fabricate personal-record answers.
- **D2 (replaces section 3).** Adapter-level qualification implemented: *"I couldn't establish that from the records I was able to check."* for wholly unsupported, zero-evidence answers only; authoritative absence, scoped-search negatives, conflicts and supported partial answers are never overwritten; no restricted existence is revealed. B-1 unchanged.
- **D3.** Selective shadow implemented locally and tested (section 4 above); `KNOWLEDGE_SELECTIVE_SHADOW_ENABLED=false` by default; no semantic comparison with the production reply.
- **D4 (replaces the fixed numbers in section 5).** The prerequisite categories stand. Ceilings are derived from the target deployment's capacity and observed baselines, and are confirmed by the owner from a measured pre-run baseline taken immediately before the window; none is a fixed invented threshold.

| Ceiling | Derivation (inputs are recorded facts) | Value today |
|---|---|---|
| Database connections | Stop when PgBouncer reports any waiting client sustained for half of `query_wait_timeout` (10 s in `pgbouncer.ini`, so 5 s), or when PostgreSQL connections exceed the pre-run baseline plus the indexer's measured increment (the [trial](verification/phase-44b-indexing-workload-trial-2026-10-09.md) saw 10 to 11 connections and +1) and the documented sizing basis of 13 server connections. Hard limits from the configuration: PgBouncer `default_pool_size` 20 plus `reserve_pool_size` 5; PostgreSQL `max_connections` 100 (read-only `SHOW` on the live server, 2026-10-10); `DB_POOL_MAX_SIZE` 8 per service. The earlier unpooled backfill trial (2026-10-08) was reverted after hitting the connection limit, which is why this ceiling is gated on the pooled configuration only | derived from the pre-run baseline; expected about 14 |
| Memory | Stop when core's resident memory exceeds its pre-run value plus the measured MiniLM load (+516 MB in the trial) plus the per-batch growth measured on the first small batch, or when host available memory falls below the pre-run minimum minus that predicted increment. Core has no memory limit in Compose; `pgbouncer` has 256 MB | **host available memory was 3.4 GB of 31.3 GB on 2026-10-10 against a trial minimum of 7.7 GB: the baseline must be re-taken and explained first** |
| Foreground latency | Stop when the rolling median of the health or reply latency of core, hub and the model server exceeds the p95 measured over at least 100 samples in the hour before the window (the median moving to what was previously the tail). Trial baselines for reference: core median 93 ms (max 175), hub 96 ms (max 133); the 2026-10-08 contention test saw chat +10 % and speech p95 +28 % with the indexer running | derived from the pre-run window |

Required before production indexing approval (unchanged in kind, sharpened): a **verified off-host backup** (written outside this host, checksum verified at the destination, and the restore performed from that copy; **blocked today**: the backup programme is paused and the NAS offers no usable transfer path, see [HANDOVER](../HANDOVER.md)), an **isolated restore** into a disposable container with row counts and `verify` compared, **bounded worker contention** (embedding threads 2, batch limits, abort rules above), and a **demonstrated rollback** (flag off and recreate, and restore from the dump, both rehearsed on the isolated copy).
