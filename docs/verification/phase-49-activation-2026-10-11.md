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

## 2. Owner-initiated processing of "My Task for next week"

Status: **awaiting the owner**. Steps and expected results are in the report that accompanied this record; results will be appended here.
