# Phase 31 trial, Step A: core image `fa418f2` with the narrowed retrieval, analysis OFF (2026-10-12)

Owner authorization: "Step A: Approved: Deploy the tested `fa418f2` core image with `MEETING_ANALYSIS_ENABLED=false`" (2026-10-12). Preparation: [trial preparation](phase-31-trial-preparation-2026-10-12.md). **Result: deployed and verified; no rollback.** Core only; hub and coding-agent were not touched.

| | Before | After |
|---|---|---|
| core image | `484b1495d55c` | `df320da58e2f` (tag `p31-fa418f2`, built from a clean worktree of `fa418f2`) |
| hub / coding-agent / schema | `af30ec4c0a1e` / `9c20355f64cc` / `032_meeting_analysis` | unchanged |
| `MEETING_ANALYSIS_ENABLED` | false | false |

What changed in behavior: only an owner-confirmed action is offered to the knowledge index (decisions, open questions and pending actions never are). With the feature off nothing is indexed from analysis in either build.

## Timeline (UTC)

Preconditions 14:26 to 14:27: tree clean (HEAD `7784a45`), schema 032, no alarm or reminder due in 30 minutes, the one meeting `complete`, model manager not running, 7B loaded, no conversation in 10 minutes, 0 analysis runs and items. Rollback tag `reachy-rollback/companion-core:pre-trial-index` created and verified equal to the running image `484b1495d55c`; the tested image retagged as the production core name. Environment fingerprint (names and 12-character value digests, 53 variables) saved to `~/reachy-backups/core-env-before-trial-index.txt` (0600). Counters read, then **core stopped gracefully at 14:27:06 (exit 0, not OOM-killed)**; selective-shadow file copied; `up -d --no-build --no-deps companion-core`; **core healthy 14:27:13**. Downtime about 7 seconds.

## Phase 48 boundary

The previous segment (core process start 2026-10-12 14:06:46 UTC, after the Phase 31 deployment) ended at 14:27:07 with `{"attempted":5,"excluded_channel":5}`: the five `probe-031` turns of the deployment record, already listed for subtraction. Saved in `~/reachy-backups/phase48-boundary-031/segment-before-trial-index.txt`; shadow-file copy `selective-shadow.cohortG-end.jsonl` (5,803 bytes, 0600). **New segment from 14:27:10 UTC.** My three smoke-test turns in it (channel `probe-031`: tasks, a note, a meeting question) are the only three attempts it had before Step B ended it; all `excluded_channel`, no candidate created. Frozen code is unchanged (`fa418f2` touches neither the frozen files nor `memory/` nor `notepad_processing/`).

## Verification

- Core `/health` 200, image `df320da58e2f`, no traceback or error in the logs; hub and coding-agent still on their images, hub `/health` 200.
- **Environment unchanged:** the fingerprint of all 53 variables is identical before and after (`diff` empty); `MEETING_ANALYSIS_ENABLED=false`.
- **Analysis inaccessible:** core `/meeting-analysis/config` 404; 0 runs, 0 items.
- Existing functions: `/meetings`, `/notes`, `/tasks`, `/reminders`, Notepad config and capture counters answer; conversation probes (open tasks, the note "GIT" read verbatim, the meeting question answered from the transcript with "Speaker 1" to "Speaker 3"); the meeting's stored labels are still `speaker_0` to `speaker_5`.
- **Knowledge index:** 85 rows, 85 distinct keys before and after (meeting 80, note 3, task 2); 78 meeting-segment rows read "Speaker N", none "speaker_N"; 0 analysis entries; outbox empty; all 51 pre-existing table counts identical.

**Not verified:** the owner's own browser session, Android, Telegram, the voice path, the robot.

## Rollback (not used)

`docker tag reachy-rollback/companion-core:pre-trial-index reachy-homelab-companion-core:latest`, stop core, `up -d --no-build --no-deps companion-core`. Keep the `pre-` images until the owner accepts.
