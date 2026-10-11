# Phase 48B: production capture activation and supervised trial log (started 2026-10-10)

**Status: capture is ON in production for owner-authenticated typed turns (Web, Android, owner private Telegram). Robot voice is ineligible. The first evidence window is open; rules are frozen for it.** Design and eligibility: [48B record](phase-48b-capture-eligibility-2026-10-10.md). Plan and gate: [Phase 48 section 4](../phase-48.md#4-48b--supervised-candidate-capture).

## 1. Activation (owner-approved 2026-10-10)

| Item | Value |
|---|---|
| Code | commit `d899e14` (robot voice ineligible via `ROBOT_VOICE_ELIGIBLE = False`); core image built from a clean `git worktree`, tag `reachy-homelab-companion-core:48b-d899e14` and `:latest`; image id `15ce11cf8ad9` |
| Recreated | `companion-core` only (`up -d --no-build --no-deps`), 14:06 UTC; hub (Phase 44 image; the only later hub change is a docstring), database, models, robot services untouched |
| Flags | `MEMORY_CANDIDATES_ENABLED=true`, `MEMORY_CANDIDATES_CAPTURE_ENABLED=true` (`deploy/homelab/.env`) |
| Before | 0 candidates, 1 meeting complete and none running |
| After | core healthy in under 20 s; `GET /memory-candidates` reports `capture_enabled: true`; no keyring or store warnings; queue empty |
| Backups | database dump `~/reachy-backups/reachy-before-phase48b-capture-20261010-2206.dump` (0600; filename uses local time); env file `~/reachy-backups/.env.before-p48b` |
| Rollback | capture only: set `MEMORY_CANDIDATES_CAPTURE_ENABLED=false` and `up -d --no-build --no-deps companion-core`. Code: retag `reachy-rollback/companion-core:pre-48b` (the 44H/Phase 44 image) as `:latest` first. No schema change |

The robot is not part of this trial or its acceptance. Not exercised: Android on a device and the Telegram poll loop against production (the owner's own use is the test).

## 1a. Freeze (owner, 2026-10-10)

From observation start, the capture implementation and rules are **frozen**: candidate patterns, limits, eligibility, sensitivity handling and scoring are not tuned unless a privacy, security or data-integrity defect is found (it would be logged here and would end the clean sample). Flags stay `MEMORY_CANDIDATES_ENABLED=true`, `MEMORY_CANDIDATES_CAPTURE_ENABLED=true`; robot voice stays ineligible until Phase 32. No content is logged or exposed beyond the existing owner review surface. Do not manufacture a scripted dataset: a few controlled checks per channel (Web, Android, Telegram) prove each channel works; the evidence comes from normal use.

| Frozen item | Value |
|---|---|
| Image | `reachy-homelab-companion-core` `15ce11cf8ad9` (commit `d899e14`), started 14:06 UTC |
| `memory/candidate_service.py` | sha256 `8965cc18b285c8c8b495769e389ad872bd6dddb7fb7f5c8c59f59eccc2e57e68` |
| `memory/candidate_rules.py` | `9ef3dec7de1b0eb73c13311d6ec9e9499e659cabbac07c51569955bfd3ec7d43` |
| `memory/candidates.py` | `c18e810efa7b371ecc5863d962a229421f0e17804d083ab280e5ed821b51eb5c` |
| `memory/candidate_routes.py` | `6b5cc7a58340d89c0967357b697f61e3adbf8bf565fafedfa0b641bf31b6c43a` |

Verify at the end: `sha256sum` of those four files at `HEAD` matches, the running container image id is unchanged, and `docker inspect` shows no restart other than the intended end-of-window one.

## 1b. End-of-window procedure

1. Run `python3 tools/memory_candidate_trial_report.py --since 2026-10-10T14:06:00Z` and save the output here.
2. Capture the in-memory duplicate/cap/exclusion counters **from the read-only route added on 2026-10-10 (commit `9c8214a`)**, before any restart of core: `docker exec reachy-homelab-companion-core-1 python3 -c "import os,urllib.request;print(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/memory-candidates/capture-counters',headers={'X-Reachy-Service-Token':os.environ['ACCOUNTS_SERVICE_TOKEN']})).read().decode())"` (numbers only and the process start time; service-token protected; no reset or write operation; core only, no hub proxy). The counters live in process memory and start from zero at every core start, so read and record them **before every restart** and sum the segments. (The original plan of reading a shutdown log line never worked: that line is never logged.)
3. Combine with the owner's tally (section 4) into the acceptance report below: precision, counts, gate verdict, and ACCEPT / ACCEPT WITH CHANGES / REJECT. No tuning is implemented until that report is complete.

**Defect found 2026-10-10 14:34 UTC: step 2 does not work.** The `capture summary` line is logged at INFO and no logging is configured, so a graceful stop prints no summary (verified). Until the owner decides (proposal: raise that one log call in `app.py` to WARNING, or add a read-only counters route; neither touches the four frozen capture files), the duplicate/cap/exclusion tallies cannot be read at the end of the window. The durable counters (proposed, accepted, edited, rejected, suppressed) are unaffected.

Restart log (any restart of core during the window must be recorded):

| Time (UTC) | Reason | In-memory summary |
|---|---|---|
| 2026-10-10 14:34:37 to 14:34:59 | planned: Phase 48D indexing activation (`KNOWLEDGE_INDEXING_ENABLED=true`; same image, capture flags and rules unchanged) | not recoverable (the logging defect above). Durable counters at that time: 0 proposed, 0 candidates, 0 suppressions |
| 2026-10-10 14:45:23 to 14:45:25 | planned: deploy of the read-only counters route (image `027ed2d6437e`, commit `9c8214a`, capture files unchanged) | not recoverable: the old process had no route and no log line (all counters of this segment were zero or exclusions; durable counters still 0 proposed) |
| 2026-10-10 14:46:19 | planned: Phase 48E (`KNOWLEDGE_RETRIEVAL_ENABLED=true`; same image, capture flags unchanged) | read before the restart: `{"attempted":1,"no_match":1}` (that one attempt is the owner-side verification probe "What is two plus two?", sent directly to core, not owner usage) |

| 2026-10-10 14:56:34 | planned: Phase 48F selective shadow (`KNOWLEDGE_SELECTIVE_SHADOW_ENABLED=true`; same image, capture unchanged) | read before the restart: `{"attempted":2,"no_match":2}` (the two 48E probes) |
| 2026-10-10 15:02:30 | planned: graceful stop to flush and verify the selective-shadow telemetry (same image, flags) | read before the restart: `{"attempted":2,"no_match":2}` (the two 48F probes at 14:57; not owner usage) |
| 2026-10-11 06:34:54 to 06:38:44 | **BOUNDARY: Phase 49 deployment (owner-approved, boundary option).** Core image `027ed2d6437e` (commit `9c8214a`) replaced by `cbf13868a429` (commit `3e17ad3`); capture flags and the four frozen capture files unchanged (hashes verified in the new image); graceful stop (`docker stop -t 30`, exit 0) | read before the stop: `{"attempted":4,"no_match":2,"excluded_handled":2}` for the process started 2026-10-10 15:02:32. Durable counters: 0 proposed, 0 candidate rows. **Cohort A ends here.** Cohort B starts at 0 with the new image; its first 20 attempts (`excluded_channel`, channel `probe-049`) are deployment probes and are subtracted. Do not merge A and B as one uninterrupted trial. [Deployment record](phase-49-deployment-2026-10-11.md) |
| 2026-10-11 07:27:04 to 07:27:07 | **BOUNDARY 2: Phase 49 activation** (`NOTEPAD_PROCESSING_ENABLED=true`, same image `cbf13868a429`, capture flags and rules unchanged); graceful stop, exit 0 | read before the stop: `{"attempted":20,"excluded_channel":20}` = my 20 deployment probes only; **cohort B closed with no owner usage**. Cohort C starts at 0 (its first 3 attempts are probes, channel `probe-049`). [Activation record](phase-49-activation-2026-10-11.md) |
| 2026-10-11 10:08:47 to 10:08:51 | **BOUNDARY 3: Brain provenance deployment** (core-only, image `cbf13868a429` -> `1c3290c4d993`, commit `d34ad51`; capture flags and the four frozen capture files unchanged); graceful stop, exit 0 | read before the stop: `{"attempted":6,"excluded_channel":6}` = my six probes only; **cohort C closed with no owner usage**. Cohort D starts at 0 (first 5 attempts are probes, channel `probe-049`). [Record](phase-49-brain-provenance-deployment-2026-10-11.md) |
| 2026-10-11 12:27:48 to 12:28:36 | **BOUNDARY 4: hybrid intent router deployment** (core-only, image `1c3290c4d993` -> `ef80ad3c7c77`, commit `d7eee35`, `INTENT_ROUTER_ENABLED=true`; capture flags and the four frozen capture files unchanged); graceful stop, exit 0 | read before the stop: `{"attempted":6,"excluded_channel":5,"no_match":1}`; **cohort D closed** (one real owner turn, no candidate). Cohort E starts at 0 (first 16 attempts are probes, channel `probe-router`). [Record](intent-router-deployment-2026-10-11.md) |
| 2026-10-11 12:59:15 to 12:59:20 | **BOUNDARY 5: privacy remediation deployment** (core-only, image `ef80ad3c7c77` -> `260eab85da2b`, commit `41a81a0`; capture flags and the four frozen capture files unchanged); graceful stop, exit 0 | read before the stop: `{"attempted":16,"excluded_channel":16}` (probes only); **cohort E closed with no owner usage**. Cohort F starts at 0 (first 20 attempts are probes, channel `probe-privacy`). [Record](privacy-remediation-and-searxng-rotation-2026-10-11.md) |

Counter segments from `process_started_at` 14:46:23 UTC: my two verification probes (`attempted 2, no_match 2` at 14:50) are not owner usage and are to be subtracted from the final tally. The trial boundary list above is the whole record; the window continues, not restarted.

**Cohorts (from 2026-10-11):** the window is now two cohorts. Cohort A: 2026-10-10 14:06 to 2026-10-11 06:34:54 UTC, image `15ce11cf8ad9`/`027ed2d6437e`. Cohort B: from 06:38:44 UTC, image `cbf13868a429` (Phase 49 and the named-note grounding fix included). Report and tally them separately; the capture rules are unchanged across the boundary.

Frozen items re-verified after that restart: image `15ce11cf8ad9` unchanged, `candidate_service.py` hash unchanged.

**Telemetry fix (owner-directed, instrumentation only, 2026-10-10).** `GET /memory-candidates/capture-counters` (core only; `shared/protocols/memory_candidates_api.py`, `app.py`): integer counters and `process_started_at`, nothing else; behind core's service token (401 without it); no reset or mutation; absent when review is off; capture never reads it. Tests: numbers only with canary session ids and sentences absent from the body, unauthorised and mutating requests refused, capture identical with and without reads, flag behaviour. The four frozen capture files are byte-identical (hashes above re-checked after the deploy) and no capture rule, limit, eligibility or text handling changed. The old shutdown-summary log line is left as it was.

## 2. Rules for the window

- Use ordinary interactions through Web, Android and owner Telegram. Capture needs short first-person statements of preference or fact matching the deterministic rules; the rules and ceilings (5 per hour, 20 per day, pending expire after 14 days) are **not tuned during the window** unless a privacy or security bug is found; any such change is logged below and ends the clean sample.
- Window: 3 to 7 days or 30 to 50 candidate-worthy interactions, whichever the owner calls.
- Gate: at least 80% of surfaced candidates useful or reasonable; 0 sensitive-capture violations; 0 durable memories without an explicit accept; 0 candidates from non-owner channels.

## 3. Measurements

Read-only report (never prints candidate text): `python3 tools/memory_candidate_trial_report.py --since 2026-10-10T14:06:00Z`.

| Measure | Source |
|---|---|
| candidates proposed; accepted unchanged; edited then accepted; rejected; suppressed; expired | database counters (hourly rows) |
| memories created from candidates | memories with source `candidate:<id>` |
| duplicate proposals, cap hits, exclusions | core's in-memory summary, logged only when core stops gracefully (`grep "capture summary"`); read at the end of the window. This is a known gap: a crash loses it |
| incorrect sensitivity or scope | owner tally below (candidates are proposed as work-private, no scope; the review shows and lets the owner change both) |
| obvious candidate-worthy facts missed | owner tally below (recall is secondary to precision) |

Candidate text is deleted when a candidate is decided, so counts, not content, are the durable record. The owner's judgement of "useful or reasonable" per candidate is what the precision figure rests on.

## 4. Owner tally (fill in as the window runs)

| Date | Channel | Proposed | Useful / reasonable | Edited | Rejected | Suppressed | Duplicate | Wrong sensitivity or scope | Missed fact (describe the kind, not private content) |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | |

## 5. Result

Not yet available. When the window closes this section gets the counts, precision, the gate verdict and the recommendation (capture stays ON, ON with limits, or OFF with review kept).
