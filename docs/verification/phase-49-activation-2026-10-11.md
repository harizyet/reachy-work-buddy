# Phase 49 controlled activation and owner acceptance test (2026-10-11)

Owner authorizations (two separate answers, 2026-10-11): (1) set `NOTEPAD_PROCESSING_ENABLED=true` and restart core; (2) process the one existing production note "My Task for next week", **initiated by the owner** in the authenticated Notepad, with no automatic accept, reject or task creation. Part 1 is done; part 2 is awaiting the owner's action (status at the end of this page).

## 1. Activation (done)

| | |
|---|---|
| Change | one line appended to `deploy/homelab/.env` (gitignored, mode 0600): `NOTEPAD_PROCESSING_ENABLED=true`; only core recreated (`up -d --no-build --no-deps companion-core`); image unchanged (`cbf13868a429`, commit `3e17ad3`); no other flag touched (indexing, retrieval, shadow, candidates and capture as before; selective answering still absent) |
| Core stop | 07:27:04 UTC graceful (`docker stop -t 30`, exit 0, not OOM-killed) |
| Core healthy | 07:27:12 UTC (about 8 s of core downtime; hub and everything else untouched) |
| Rollback | set the line to `false` (or remove it) and recreate core; nothing else; the dump and `pre-049` tags are kept |

**Phase 48 boundary 2.** Cohort B (06:38:44 to 07:27:04 UTC) is closed and cohort C opens at 07:27:07 UTC. Cohort B contained only my deployment probes: capture counters `{"attempted":20,"excluded_channel":20}` (no candidate logic reached, durable report: 0 rows), shadow telemetry cumulative `admitted 26` = the 6 of cohort A plus exactly the 20 probes (copy: `~/reachy-backups/phase48-boundary-049/selective-shadow.cohortB-end.jsonl`, sha256 prefix `d8676998c7b1f5cd`). So cohort B holds **no owner usage**. Cohort C starts with 3 more deployment probes (channel `probe-049`, 07:27) to be subtracted. Both Phase 48 trial logs carry the boundary row.

**Verification after the restart**

| Check | Result |
|---|---|
| Flags in the core container | `NOTEPAD_PROCESSING_ENABLED=true`, concurrency 1; the five Phase 48 flags unchanged |
| Core routes | `/notepad-processing/config` 200 `{"enabled": true}`; `/notepad-proposals` 200 `[]`; without a service token 401 |
| Hub owner-only | anonymous and bearer-only requests refused (401) on the Phase 49 routes, as before |
| Existing reads | tasks 0, reminders 0, notes 3, meetings 1, alarms 9: all 200 |
| 44H boundary | "put the robot in standby" (text) and "delete all my memories" (voice) -> "I can't perform that action here, so I haven't made any changes." |
| New inquiry path | "what are my tasks?" -> "You have no confirmed tasks. 3 notes have not been processed, so I can't say whether they hold other commitments." (the 49E answer replaces the old one only while the flag is on) |
| **No historical note processed** | notepad jobs 0, proposals 0, links 0, provenance 0; tasks 0, reminders 0; the note "My Task for next week" hash and `updated_at` (2026-10-09 02:45:24 UTC) unchanged |
| Logs | 0 tracebacks in the new core process |

## 2. Owner-initiated processing of "My Task for next week" (07:41 UTC)

The owner ticked "Send to Reachy for processing" in the authenticated Notepad. Read-only verification afterwards:

| Check | Result |
|---|---|
| Jobs | exactly 1 (`succeeded`, attempts 1, model `reachy-local`, no error; queued 07:41:14, finished 07:41:16, i.e. 2 s) |
| Original note | unchanged: 248 characters, same md5, `updated_at` 2026-10-09 02:45:24 UTC; the job's snapshot equals the note and its SHA-256 matches |
| Proposals | exactly 1: task "refactor clickhouse migration", evidence from the note, status `pending`, no stated time, no ambiguity markers |
| Source span | characters 0 to 126 of 248; the evidence is an exact substring of the note at that span |
| Authoritative records | tasks 0, reminders 0, task/reminder receipts 0: nothing created, nothing accepted or dismissed by me |
| Inquiry (core `/conversation`, probe channel) | "What do I need to do next week?" -> "You have no confirmed tasks. You have no confirmed reminders next week. 1 more action item extracted from your note “My Task for next week” is awaiting your review and not yet confirmed: refactor clickhouse migration. 2 notes have not been processed, so I can't say whether they hold other commitments." ("What tasks do I have?" and "Do I have any pending action items from my notes?" give the same split.) Pending and confirmed are separate; asking promoted nothing |
| Logs | core 0 errors; hub shows no failed request |

**Comparison with the note.** The note has two action sentences. The 7B proposed one task covering the first ("refactor clickhouse migration", its evidence being the whole first sentence including "present to CTO"). It did **not** propose the second, "Prepare a chart of how it will work and the ingestation of data" (a missed item, the known recall limit of the 7B; nothing was invented), and it correctly left "story is important" and "I'm on ANBQA and the DB Migration" as context. The proposed text is a short paraphrase; the owner may use Edit and accept to word it fully (for example to include the study of alternatives and the CTO presentation).

**Defect found in this run (UI only, fixed in code, not yet deployed).** The Notepad panel showed "Something went wrong" three times (under Process again, under the suggestions, under the Meetings area) although nothing had failed. Cause: `failure(error)` in `ProcessingPanel.tsx` treated "no error" (`null`) as an unknown failure, and the three mutation-error lines rendered it. No request had failed (the job, proposal and inquiry above are correct, and the hub log has no error), so the data and the review controls were unaffected. The fix returns `null` for `null`/`undefined`; a regression test (`shows no error text when nothing has failed`) fails without the fix and passes with it; the earlier component tests missed it because they asserted what is shown, not what is absent. The production hub image still contains the old client until the owner approves a hub rebuild and recreate (web client only; no schema or core change).

Status at the end of this page: the proposal is **pending and undecided**; the owner decides Accept, Edit and accept or Dismiss.

## 3. Hub-only fix deployment (owner-approved, 2026-10-11 08:27 UTC)

Owner approved the bug fix and its deployment. Commit `3adc66e` (only `ProcessingPanel.tsx` and its test differ from the deployed `3e17ad3`), hub image built from a clean worktree: `3a1156fd2fd0` (`p49-3adc66e`; client bundle `index-B6cqDOik.js` replaces `index-Dukl-VGn.js`). Previous hub image `eac6a24e3c6f` tagged `reachy-rollback/reachy-hub:pre-049-fix` (the original `pre-049` tag, `0e5f42fb8504`, is kept). Only the hub was stopped (08:27:17) and recreated; healthy 08:27:24 (7 s). Core (started 07:27:07), PostgreSQL, PgBouncer and vLLM were not touched, so no new Phase 48 boundary arose. Verified: new image running, 0 restarts, 0 tracebacks in hub and core logs, hub owner-only routes still 401 for anonymous and bearer-only requests, `/web/` and `/health` 200, schema still 029, the note unchanged (same hash and `updated_at`). Rollback of this step: `docker tag reachy-rollback/reachy-hub:pre-049-fix reachy-homelab-reachy-hub:latest` and recreate the hub with `up -d --no-build --no-deps reachy-hub`.

**Owner decision observed:** between the processing run and this deployment the owner accepted the pending proposal in the Notepad (their action, not mine). It created one task through the review path (1 task, 0 reminders, 1 provenance row, 1 `task.created` receipt, proposal status `accepted`), exactly as designed.

## 4. Processed tag (owner request; built and tested; not deployed)

A first version used an icon; at the owner's request it was replaced by a text tag (`ProcessedTag.tsx`, no icon remains). A small pill beside the title in the notes list and in the open note's header: **Processed · review** (job finished and suggestions are waiting; accent border), **Processed** (job finished, nothing waiting), **Queued**, **Processing**, **Failed** (red). Nothing for a note never sent or when the feature is off. It reads the same per-note status as the panel (shared query cache), so it updates when processing finishes, and means only that a processing job finished for that note, not that anything was accepted. No server change: one small `GET /notes/{id}/processing` per listed note. Tests: every state in the list and the header, never-sent, feature off (component), the exact tag in the real-browser spec; vitest 235 passed, tsc clean, Playwright Notepad and Notes specs 11 passed (both projects and mounts). Deploying it is a hub-only rebuild pending the owner's approval.
