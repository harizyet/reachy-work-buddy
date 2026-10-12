# Phase 31 trial, Step B: `MEETING_ANALYSIS_ENABLED=true` (2026-10-12)

Owner authorization: "Step B: Approved conditionally: Once Step A passes, activate `MEETING_ANALYSIS_ENABLED=true` through the documented flag-only change and second core restart" (2026-10-12). Step A passed ([record](phase-31-trial-step-a-deployment-2026-10-12.md)). **Result: enabled; verified; no rollback.** **No analysis was started and none exists.**

Authorized: manual, owner-initiated analysis with the existing local 7B (served as `reachy-local`; the 7B was loaded at activation), prompt `meeting-analysis-2` and the validator unchanged; only an owner-confirmed action becomes a task and reaches retrieval; no automatic analysis, cloud processing or Deep Local switching; no unrelated change. Not authorized: analysing any production recording without a separate owner action.

## The configuration change

`deploy/homelab/.env` (gitignored, 0600): one line added, `MEETING_ANALYSIS_ENABLED=true`; backup `.env.bak-before-meeting-analysis` (0600, made first, the flag line was absent). The name-only diff against the backup shows exactly one changed line. Compose already passes the variable through (default false). Image unchanged (`df320da58e2f`).

## Timeline (UTC)

Preconditions 14:27 (nothing due, manager not running, 7B loaded, no conversation). Env fingerprint before: `~/reachy-backups/core-env-before-flag.txt`. Counters read; **safety dump** `~/reachy-backups/reachy-before-meeting-analysis-enable-20261012-222740.dump` (332,049 bytes, sha256 prefix `c72c4f3da67d95b0`, 53 tables with data including the two empty analysis tables; listed with `pg_restore --list`, not restore-tested because nothing but the flag changes and the stop-time dump of the 032 deployment remains the restore-verified rollback point). **Core stopped gracefully 14:27:41 (exit 0, not OOM-killed)**, shadow file copied, `up -d --no-build --no-deps companion-core`, **healthy 14:27:47**. Downtime about 6 seconds.

## Phase 48 boundary

The segment that started at 14:27:10 ended at 14:27:41 with `{"attempted":3,"excluded_channel":3}` (the three Step A `probe-031` turns), saved in `~/reachy-backups/phase48-boundary-031/segment-before-flag.txt`; shadow-file copy `selective-shadow.cohortH-end.jsonl`. **New segment from 14:27:44 UTC** (core `process_started_at` 14:27:44.458), counters `{}`. Total probe turns to subtract across the Phase 31 work: 5 (deployment) plus 3 (Step A), all on channel `probe-031`; Step B added none. Frozen code unchanged.

## Verification

- **Only the flag changed:** the fingerprint diff before and after lists exactly one variable, `MEETING_ANALYSIS_ENABLED`; `docker exec ... env` shows `true`; every other flag is as before.
- **Enabled:** core `/meeting-analysis/config` `{"enabled":true}`; the hub's route answers 401 without an owner session (the owner's browser should now show the Analysis tab; I cannot sign in as the owner).
- **Nothing started by itself:** the meeting reads `not_analysed`, `run` null, no items; `/meeting-analysis/items` empty; 0 runs and 0 items still 20 seconds after startup.
- **Nothing else moved:** all table counts identical to before the restart (the two analysis tables at 0); knowledge index 85 rows, 85 distinct keys, 0 analysis entries, outbox empty; `/notes`, `/tasks`, `/reminders`, Notepad config 200; logs clean; hub and coding-agent untouched; the 7B is the loaded model and the model manager is not running.

**Not verified:** the owner's browser session (Analysis tab, the Analyse action), and the analysis itself (deliberately not run).

## Rollback (not used)

Restore the configuration: `cp -p .env.bak-before-meeting-analysis .env`, stop core (`-t 30`), `up -d --no-build --no-deps companion-core`; the routes disappear at once, any analysis rows stay inert, a task made from a confirmed action stays. If the image itself were at fault, retag `reachy-rollback/companion-core:pre-trial-index` (Step A). Abort criteria and the schema rollback are in the [preparation record](phase-31-trial-preparation-2026-10-12.md#5-rollback).

## For the trial

The owner starts an analysis from the Analysis tab of a meeting. The acceptance report and limits (`stated` is not independently verified; the question-recall regression; the 7B's grounding weakness) are in [phase-31 section 6](../phase-31.md). During the trial do not start a Deep Local job, change the prompt, validator or model, or enable anything else.
