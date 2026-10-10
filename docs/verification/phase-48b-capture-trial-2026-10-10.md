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
