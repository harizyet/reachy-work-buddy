# Phase 44E: selective shadow telemetry policy (retention, deletion, intervals, shutdown, disclosure) — 2026-10-10

**Scope: the aggregate file written by `knowledge/selective_shadow.py` (committed `26b16f0`; the hardening below is implemented and tested locally, uncommitted), which is OFF by default and has never run outside tests.** This page states what the code does today, verified by tests and one measurement on 2026-10-10, and lists the residual risks and the proposed hardening, which is **not implemented**. The sibling retrieval shadow ([`shadow_telemetry.py`](../services/companion-core/src/companion_core/knowledge/shadow_telemetry.py)) has the same row and flush pattern; its limits below apply equally. Evidence: [shadow verification record](verification/phase-44e-selective-shadow-2026-10-10.md).

## 1. What is stored

One JSON line per flush: `schema`, `window_start` (the UTC hour) and `groups`, a map of fixed group names to fixed counter names and integer counts (funnel, routing class, ineligible and untyped reasons, anchor kind and strength, production path kind, outcome, citation-count bucket, maximum cited sensitivity as `none`/`public`/`work-private`, modality, latency bucket). Any name outside the fixed vocabulary is stored as `other`. **Never stored:** questions, replies, evidence, titles, record or session ids, any hash of them, user identity, per-turn rows, timestamps finer than the hour. File mode 0600, owner of the core process, on the core host only.

## 2. Aggregation intervals

- **Window:** the UTC hour (`window_start`).
- **Flush:** every 300 s while counts exist, when the hour rolls over, and at shutdown. Since the 2026-10-10 hardening **each flush merges its counts into the single row of the current hour and rewrites the file atomically** (a 0600 temporary file, fsync, replace), so repeated flushes and restarts leave exactly one row per hour and the file carries no finer timing than the hour. A legacy file that has several rows per hour is folded into one at start-up. An hour with no activity writes no row. A failed write keeps the counts and retries at the next flush.
- **Reporting/export:** `python -m companion_core.knowledge.selective_shadow report <file> [--min-cell 5] [--by day]` (or `selective_shadow.report`) is the only export an operator should read. It sums hourly rows over the period or per day and **suppresses every cell below the threshold** (default 5, never below 2), with complementary suppression inside a group (when one cell is hidden the smallest visible cell is hidden too, so a hidden value cannot be recovered by subtracting from a self-reconciling group such as the funnel). Hidden counts are never printed, only how many cells were hidden. Raw hourly rows remain in the 0600 file for the owner.

## 3. Retention and deletion

- **Retention:** 30 days by default (`KNOWLEDGE_SELECTIVE_SHADOW_RETENTION_DAYS`, clamped to 1 to 365). Rows whose `window_start` is older than the cutoff, and any unparsable line, are removed at start-up (forced) and at most once a day on a flush, by rewriting the file through a temporary 0600 file and an atomic replace.
- **Deletion:** deleting the file erases everything the shadow ever recorded. Nothing is copied to a database, log or backup by the shadow; unsetting the flag and restarting stops all writing. The core log line at shutdown holds only the in-process totals (the same category counts), never text.
- **Not covered:** host-level backups or snapshots of the directory holding the file (the owner chooses the log path; keep it outside paths included in off-host backups unless that is intended).

## 4. Shutdown handling

`stop()` is called from the application lifespan's `finally` inside a suppress block: it refuses new offers, lets the running job finish within its timeout plus one second (then cancels it), counts any still-queued jobs as `discarded_at_stop`, stops the private answerer's background refresh, and flushes. A failure in any step cannot stop the service from shutting down. After a crash (no `stop()`), at most the last unflushed interval (up to 300 s of counts) is lost; no partial or corrupt row is written because each row is one `write` of a complete line. A restart appends to the same file (tested).

## 5. Protection against low-frequency information disclosure

| Protection in place | Limit |
|---|---|
| Counters are categories from a fixed vocabulary; no text, hash, id or identity | A category can still describe a rare event; the report suppresses cells under 5 |
| One merged row per hour; no finer timestamp is written (hardened 2026-10-10) | The hour itself is visible in the raw file |
| Sensitivity recorded only as the maximum cited bucket (`none`, `public`, `work-private`); no `sensitive` bucket exists; restricted records change no counter (tested, text and voice) | A cell of 1 still says a work-private citation happened in that period |
| Spoken turns are assessed with public access only, so a shared-speaker turn can never raise a higher-trust counter | A `voice` cell reveals that a spoken knowledge turn occurred |
| 0600 file, local host only, 30-day retention, delete-to-erase | Anyone with host or backup access can read it |
| Single-owner deployment: the only data subject is the owner | The model changes if a second person ever uses the system |

**Implemented hardening (2026-10-10):** one row per hour merged across flushes and restarts; atomic rewrites; small-cell suppression with complementary suppression in the report/export; retention and shutdown regression tests (`tests/test_selective_shadow_telemetry.py`). **Still open:** rolling rows older than 7 days up to daily rows (optional); keeping the log path outside off-host backup scope; applying the same merge to the older retrieval shadow file (`shadow_telemetry.py`, OFF, unchanged).

## 6. Failure containment (verified)

Evidence, all in `tests/test_selective_shadow.py` and `tests/test_selective_shadow_lifespan.py`:

- **No partial foreground response:** the reply and its privacy label are decided before the shadow is offered anything, and the offer is a snapshot of plain data, not the response object. A `submit` that raises mid-call leaves the response body, status code and turn count identical to a run without the shadow (tested; `submit` is also wrapped in a suppress block in the route).
- **No delay:** an offer costs about 3 microseconds (tested: under 5 ms each over 500 offers; measured 0.40 ms in total for 120). Work happens in one background task on the service's event loop. A shadow whose retrieval takes 1 s, hangs for 30 s or raises does not delay four foreground turns (tested); 40 foreground turns with a saturated shadow took 0.3 s (real PostgreSQL).
- **Bounded event-loop impact (measured):** with a 1 ms heartbeat while 120 offered jobs ran (typed, ambiguous, untyped and chat questions over up to 15 retrieved records), the longest gap was about 30 ms; a regression guard fails above 250 ms. Each job is CPU-bound for that long at most, because planning is synchronous Python; if a measurement on real data shows more, the planning step can be moved to a worker thread (not needed now).
- **Bounded resources:** queue of 10 by default (oldest dropped), one job at a time, 3 s timeout, shared connection pool (no pool of its own; connections stayed within the bound and returned to zero at shutdown).
- **Faults:** retrieval error, empty index, hang, an exception inside the job and a real index table renamed mid-flight were counted in bounded categories without changing a reply or leaking exception text.
