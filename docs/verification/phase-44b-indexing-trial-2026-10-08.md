# Phase 44B supervised production indexing trial, 2026-10-08

Owner authorisation: accept the contention test as passed (the Whisper p95 +28% with indexing recorded as a limitation) and run a supervised trial of production indexing over the existing backfill only, with retrieval disabled throughout and the flag restored to `false` at the end. Times are Singapore time (UTC+8).

**Outcome: the backfill completed in seconds and the index was validated, but the trial was aborted and reverted early because it exposed a PostgreSQL connection-limit problem. The flag is `false` again. A fix is committed (`a969b87`) but not deployed.**

## Preflight (13:41)

Revision `027_knowledge_index`; hub, core and vLLM healthy; no alarm or reminder due within 45 minutes; the one meeting `complete`; no voice session (robot offline); `knowledge_items` 0, outbox 1 row (the meeting); production core had the flag `false`.

## What happened

| Time | Event |
|---|---|
| 13:42:53 | `KNOWLEDGE_INDEXING_ENABLED=true` for core only (`up -d --no-build companion-core`; `.env` untouched, so reverting is the same command without the variable). `KNOWLEDGE_EMBED_THREADS` is not set, so the default 2 applies (it is not passed through compose). The worker has no OS-level `nice`: its low priority is 2 torch threads and a yield to the event loop between embedding batches. |
| 13:42:57 | The whole backfill was indexed: 80 rows (78 transcript segments, 1 summary, 1 minutes) for the one meeting; the outbox drained to 0; no failed or retried rows; `last_error` empty. MiniLM load plus embedding took under 5 s after the core restart. |
| about 13:44 | A `psql` I ran against Postgres was refused with **"sorry, too many clients already"**. `pg_stat_activity` was at the server's `max_connections` of 100. Per mandatory-condition 7 I stopped and reverted. |
| 13:44:24 | Core restarted with the flag unset: `KNOWLEDGE_INDEXING_ENABLED=false` confirmed in the container; hub and core healthy. |

Honest gaps in the monitoring: my monitor aborted once on the planned core restart (a script fault, no production effect), and its second run was killed by a careless `pkill` that also ended my shell, so **no resource time series was captured for the trial window**. The only measurements are the end states below and the earlier [contention test](phase-44b-contention-result-2026-10-08.md). No chat-latency probe ran during the window. Service logs for core, hub and coding-agent contain no "too many clients", traceback or connection errors for that period, and health stayed `ok` whenever it was checked, but a brief connection failure in another service during the window cannot be excluded from logs alone.

## The finding: no connection headroom

Each store opens a pool of at least 4 connections; core holds about 56 and the hub 32, coding-agent 4 (92 in all) beside Postgres's own sessions. At rest, with indexing off, the server sits at **93 to 98 of 100**. The indexer added two more pools of 4 and pushed it to the limit. That leaves almost no room for anything else, indexing or not (a migration job, a `psql`, a restart that overlaps old and new connections). This is a latent reliability risk that predates Phase 44.

Done: the indexer's two pools are now `min_size=1, max_size=2` (`a969b87`, tests pass on a disposable Postgres), which would add 2 rather than 8. Not done, and for the owner: raise `max_connections` for the homelab Postgres (a restart of that container) and/or cap the other stores' pools. Neither was changed; a production Postgres restart or an image rebuild of core was not part of the trial authorisation.

## Validation of the index (read-only, afterwards)

A one-off container from the production core image, with a 2-CPU, 3 GB limit, read the production database and wrote nothing; checksums of the index, the outbox count and the meetings table were identical before and after.

- **Counts:** 80 rows for 1 meeting: kind `meeting_segment` 78, `meeting_summary` 1, `meeting_minutes` 1. Outbox 0 rows, 0 failures. Every row `work-private`, no project scope, `local_only`.
- **Index against the source (the adapter's current view):** 80 expected, 80 present, 0 missing, 0 extra; `match_text`, sensitivity, scope, kind and local-only all equal for every row; every row has a 384-dimension embedding from `sentence-transformers/all-MiniLM-L6-v2`; reference keys are `meeting:<id>#<locator>` (`0`..`77`, `summary`, `minutes`); 80 distinct source versions; every row has `observed_at`; the two generated items carry confidence below 1 and the 78 transcript segments 1.0.
- **Correction overlays:** the meeting has 2 segments with an accepted transcript correction; for all 78 the indexed text equals the corrected text the adapter returns (the raw transcript is not indexed). No speaker display names are set on this meeting, so name overlays were not exercised on live data.
- **Retrieval-time revalidation against the live index, with nothing exposed to the assistant** (the retrieval code was run in that one-off container only; no flag was set and no route exists):
  - Owner, private channel, local destination: lexical returned 5 items and hybrid 10, all `work-private` and local-only, with provenance, no drops.
  - Shared (public) channel: 0 items with the index pre-filter; with the pre-filter switched off to test revalidation alone, 5 candidates were dropped `over_ceiling` and 0 returned.
  - Cloud as a possible destination, pre-filter off: 5 dropped `destination`, 0 returned.
  - Source changed underneath (adapter stubs, no write): source missing, 5 dropped `missing`; source hidden, 5 dropped `deleted`; reclassified `sensitive`, 5 dropped `over_ceiling`; a stale part no longer in the source, dropped `missing`; changed source text, the returned text is the source's text, not the index's.
  - A project scope other than the meeting's still returned the unscoped meeting, which is the documented interim single-owner rule (D8: unscoped is owner-accessible, not public).

## End state

Revision `027_knowledge_index`; `KNOWLEDGE_INDEXING_ENABLED=false` in the core container; no `.env` or compose change; `knowledge_items` 80 rows (derived data, left in place; retrieval is off and nothing reads them); `knowledge_outbox` 0 rows; hub, core and vLLM healthy; no temporary container left (the validation container ran with `--rm`; its env file was shredded). Temporary configuration changes: one process-level variable on one `docker compose up`, already reverted by the second.

## Remaining before a repeat

1. Owner decision on Postgres connection headroom (raise `max_connections`, or reduce pools).
2. Rebuild core with `a969b87` (a production deployment, so a separate approval), then a repeat trial if the owner wants resource data from production itself; the backfill is already built, so a repeat would only prove the steady state. The re-run needs a monitor that tolerates the planned restart.
