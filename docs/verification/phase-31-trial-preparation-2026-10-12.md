# Phase 31 owner-supervised trial: preparation (2026-10-12)

**Status: prepared and rehearsed; NOT activated.** The deployment of 2026-10-12 is unchanged: core `484b1495d55c`, hub `af30ec4c0a1e`, coding-agent `9c20355f64cc`, schema `032_meeting_analysis`, `MEETING_ANALYSIS_ENABLED=false`. Activation needs the owner's separate approval of the configuration change. Trial scope (owner, 2026-10-12): manual analysis started by the owner; Qwen2.5-7B, prompt `meeting-analysis-2` and the validator unchanged; the owner reviews decisions, open questions and action candidates; an action becomes a task only on explicit confirmation; no automatic analysis; no cloud, no model switching; no unreviewed finding promoted into memory or retrieval.

## 1. What was verified while the feature is off

- **Deployed web bundle:** the running hub image serves `/web/` (200) and contains the Analysis code; unauthenticated `/meetings` and `/meeting-analysis/config` answer 401.
- **Authenticated owner, Meetings interface, feature off:** checked in a real browser (Chromium via Playwright) against the real hub in front of the real core with `MEETING_ANALYSIS_ENABLED=false` and the same production web build (`clients/web/e2e/analysis.spec.ts`, "analysis disabled", desktop and mobile). The signed-in owner sees the Meetings list, opens a meeting, sees Summary, Minutes and Transcript, **no Analysis tab**, the transcript with "Speaker 1" for the stored label `speaker_0`; the hub reports `{"enabled": false}`, and `GET`/`POST /meetings/{id}/analysis` are 404 in core. **I cannot log in to the production hub as the owner (no credential), so the same check on production is the owner's, below.**
- **No automatic analysis:** the only code path that starts an analysis is `POST /meetings/{id}/analysis` (checked in the source; the meeting worker, the recording-complete path and the runner never enqueue). On a restored copy of the production database the core image booted with the flag true and, after 12 s, had 0 runs and 0 items; the meeting reads `not_analysed`.
- **Model:** analysis uses the local-only provider (routing forced to local-only, `temperature 0`); no cloud route exists in the code path; it asks the model served as `reachy-local`, which is the 7B unless the model manager has swapped in the Deep Local model. Do not start a Deep Local job during the trial; the check below confirms the 7B is loaded.
- **No memory promotion:** `meeting_analysis` imports no memory store, and nothing writes a memory, note or candidate. Only an owner-confirmed action creates a task (existing task system, receipt, provenance).

## 2. A scope conflict found and closed before activation (needs a core image change)

The deployed core indexes **undismissed decisions and open questions** (and confirmed actions) for Phase 44 retrieval once a run completes. Those are unreviewed (a decision or question has no confirmation step, only dismissal), so flag-only activation of the deployed build would have put unreviewed model-written findings into the knowledge index, contrary to the trial scope and to the earlier statement that unreviewed finding retrieval needs separate authorization. Today retrieval is inert for replies and selective answering excludes model-written entries, so the exposure would have been the index rows and the Brain view, not answers; still it is outside the scope. Fix committed as `fa418f2` (not deployed): **only an action the owner has explicitly confirmed is offered to the index**; decisions, open questions and pending actions never are. Tests updated (adapter, store, PostgreSQL flow); the Phase 48 frozen files are untouched. Because this is a code change, it ships as its own step before the flag-only step.

## 3. Rehearsal (restored copy of the live database, `--network none`, disposable)

New core image built from a clean worktree of `fa418f2` (`reachy-p31-trial-companion-core`, `df320da58e2f`). On a fresh restore of the live database: flag false: `/meeting-analysis/config` 404, `/meetings/{id}/analysis` 404; flag true: config `{"enabled":true}`, the meeting `not_analysed`, items empty, 0 runs and 0 items in the database, no traceback. Tests: 64 meeting-analysis (core in-process, PostgreSQL, hub), 578 in the knowledge/meeting/brain subset (the two known baseline failures), 4 Playwright (analysis on, analysis off, desktop and mobile), ruff clean.

## 4. Procedure after approval

Both steps recreate **only core** (no migration, no PgBouncer wait: about 15 to 30 seconds without core; the hub shows core as unavailable meanwhile). Each core restart ends a Phase 48 segment and starts a new one. They may be done as one restart if the owner approves "image and flag together"; the default below is two, so the flag change stays a flag-only change.

Common: `cd deploy/homelab; export SEARXNG_SECRET_KEY="$(cat .env.searxng-secret)"; DC="docker compose -p reachy-homelab --env-file .env"`. Never print `.env` or `docker compose config`.

Preconditions each time: no alarm or reminder due in 30 minutes, no meeting mid-pipeline, no deep-review job and the model manager not running, no open voice conversation, 7B loaded (`curl -s 127.0.0.1:8003/v1/models` shows `Qwen2.5-7B-Instruct-AWQ`).

**Step A: core image `fa418f2`, flag still false.**
1. `docker tag $(docker inspect reachy-homelab-companion-core-1 --format '{{.Image}}') reachy-rollback/companion-core:pre-trial-index`; `docker image inspect` it and confirm it equals `sha256:484b1495d55c…`.
2. `docker tag reachy-p31-trial-companion-core:latest reachy-homelab-companion-core:p31-fa418f2` and the same for `:latest`.
3. Save the env fingerprint (names and 12-character digests of values only): `docker inspect reachy-homelab-companion-core-1 --format '{{json .Config.Env}}' | python3 -c "import json,sys,hashlib; [print(k, hashlib.sha256(v.encode()).hexdigest()[:12]) for k,_,v in (e.partition('=') for e in json.load(sys.stdin))]" | sort > ~/reachy-backups/core-env-before-trial-index.txt` (0600).
4. Read the capture counters (`GET /memory-candidates/capture-counters` from inside the container with the service token) and save them to `~/reachy-backups/phase48-boundary-031/segment-before-trial-index.txt`; `docker stop -t 30 reachy-homelab-companion-core-1`; copy `/data/shadow-router/selective-shadow.jsonl` to the same directory.
5. `$DC up -d --no-build --no-deps companion-core`.
6. Verify: `/health` 200, running image `df320da58e2f`, env fingerprint identical to step 3 (`diff` prints nothing), flag false, `/meeting-analysis/config` 404, `/meetings`, `/notes`, `/tasks` answer, 78 meeting-segment rows still start "Speaker N", knowledge index count 85 and no duplicate keys, 5 minutes of logs clean. Record the new segment start.

**Step B: the flag, and only the flag.**
1. `cp -p .env .env.bak-before-meeting-analysis` (0600). `grep -c '^MEETING_ANALYSIS_ENABLED=' .env` must print 0.
2. `printf 'MEETING_ANALYSIS_ENABLED=true\n' >> .env` (check the file ended with a newline first). Prove nothing else changed: `diff .env.bak-before-meeting-analysis .env | grep '^[<>]' | sed 's/=.*/=<value>/'` must show exactly one `>` line, `MEETING_ANALYSIS_ENABLED=<value>`.
3. Env fingerprint of the running core (as step A.3) to `core-env-before-flag.txt`; read the counters; `docker stop -t 30` core; copy the shadow file.
4. A quick safety dump (read-only, no stop needed; nothing changes before the owner starts a run): `pg_dump -Fc` to `~/reachy-backups/reachy-before-meeting-analysis-enable-<time>.dump`, verified by `pg_restore --list`.
5. `$DC up -d --no-build --no-deps companion-core`.
6. Verify: image unchanged (`df320da58e2f`); env fingerprint diff against `core-env-before-flag.txt` shows only `MEETING_ANALYSIS_ENABLED` (digest changes); `/health` 200; core `/meeting-analysis/config` `{"enabled":true}`; the meeting reads `not_analysed`; `meeting_analysis_runs` and `_items` have 0 rows (nothing started by itself); table counts unchanged; logs clean; the owner reloads the web client and sees the Analysis tab (hub config true).
7. Write the activation record: the boundary (old segment's counters and end time, new segment start), dump reference, fingerprints, what was and was not verified. Any probe turns use channel `probe-031b` and are listed for subtraction.

**Owner's check of the Meetings interface before approving (feature still off):** sign in to the web client, open Meetings, open the meeting; Summary, Minutes and Transcript should work as before, the speakers should read "Speaker 1" to "Speaker 6", and there should be no Analysis tab.

## 5. Rollback

- **Flag:** `cp -p .env.bak-before-meeting-analysis .env`; stop core (`-t 30`), `$DC up -d --no-build --no-deps companion-core`. The routes disappear at once; nothing is migrated back. Analysis rows stay in the database, inert; a task made from a confirmed action stays (it is the owner's record); the index drops the confirmed-action entries at its next reconcile.
- **Image (step A):** `docker tag reachy-rollback/companion-core:pre-trial-index reachy-homelab-companion-core:latest`; stop core, `up` as above.
- **Schema:** not needed by either step; if ever required, `rollback-032.sql` with the three services stopped, as in the deployment record.
- **Abort criteria:** any failed precondition; core not healthy within 60 seconds of `up`; an env fingerprint difference other than the flag; a run or item present before the owner clicks Analyse; an error in the logs. Stop, roll back, report.
- Keep the stop-time and safety dumps and all `pre-` images until the owner accepts the trial setup.

## 6. What the trial can and cannot show

Frozen throughout: prompt, validator, schema, the 7B. The acceptance report and the limitations to state (`stated` is not independently verified; the known question-recall regression; the 7B's grounding weakness) are in [phase-31 section 6](../phase-31.md).
