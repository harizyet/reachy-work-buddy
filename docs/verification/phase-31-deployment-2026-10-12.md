# Phase 31 deployment: migration 032 and coordinated cutover, analysis OFF (2026-10-12)

Owner authorization: "Approved: proceed with the controlled Phase 31 deployment using the verified preparation procedure" (2026-10-12), covering the cutover below only. **It does not cover enabling meeting analysis, automatic analysis, retrieval of unreviewed findings or the owner-supervised trial; `MEETING_ANALYSIS_ENABLED` is false.** Preparation and rehearsal: [preparation record](phase-31-deployment-preparation-2026-10-12.md). **Result: deployed; no rollback needed; all checks below passed.** Not yet accepted by the owner.

| | Before | After |
|---|---|---|
| Schema revision | `031_documents` | `032_meeting_analysis` |
| core | `92a81c773dd8` | `484b1495d55c` (tag `p31-e6b24d4`) |
| hub | `d438f87dc181` | `af30ec4c0a1e` |
| coding-agent | `44b6fa237c0e` | `9c20355f64cc` |
| migrate | `4498cc0870b8` | `f0e063e40124` |

Code: images built from a clean worktree of commit `e6b24d4`; the working tree used for Compose is branch `phase-31-meeting-analysis` (HEAD `d94293b`), which adds only the Compose pass-through `MEETING_ANALYSIS_ENABLED: ${MEETING_ANALYSIS_ENABLED:-false}` and documentation to `e6b24d4`. The branch is not merged. Untouched: PostgreSQL, PgBouncer, vLLM (7B, healthy), the model manager (not running), Caddy, SearXNG, router, transcription, diarization, document worker, the robot, every other flag.

## Timeline (UTC, 2026-10-12)

Preconditions 14:01: tree clean, no alarm or reminder due within 30 minutes, the one meeting `complete`, no deep-review job (manager not running), no conversation in the last 10 minutes. Tested images retagged to the production names (IDs checked equal to the rehearsal builds); `reachy-rollback/*:pre-032` verified equal to the previous running images. **14:01:26 Phase 48 counters read; 14:01:27 core stopped gracefully** (`docker stop -t 30`, exit 0, not OOM-killed), then hub and coding-agent (exit 0). Stop-time dump taken and verified by restore into a throwaway `--network none` container (revision 031, 51 tables with identical counts, container removed). The first migrate run refused ("Stop hub/core and other database clients": two idle PgBouncer connections, as in the 030 deployment); waited until they closed (14:06:31; PgBouncer not restarted). **14:06:35 migrate applied 032**; counts of all 51 pre-existing tables unchanged. **14:06:43 `up -d --no-build --no-deps` core, hub, coding-agent; core `/health` 200 at 14:06:49.** Downtime about 5 min 22 s, nearly all of it the connection wait.

## Backup and rollback

| Item | Value |
|---|---|
| Stop-time dump (the rollback point) | `~/reachy-backups/reachy-before-032-stop-20261012-220137.dump`, 324,017 bytes, 0600, sha256 prefix `6099f8b33c17942f`, 51 table-data entries, restore verified; counts `rowcounts-at-stop-before-032.txt` (identical to the prepared dump's) |
| Prepared dump | `reachy-prepared-before-032-20261012-213302.dump`, sha256 prefix `2adb17fe1ed8f7ab` |
| Images | `reachy-rollback/{companion-core,reachy-hub,coding-agent-service,migrate}:pre-032` |
| Schema rollback | `deploy/homelab/rollback-032.sql` (rehearsed on a restored copy); services stopped first, then the `pre-032` images started |
| Status | **Not invoked.** Keep all of it until the owner accepts the deployment. |

## Phase 48 boundary

The previous segment (core process started 2026-10-12 07:42:52 UTC) ended at the graceful stop 14:01:27 with capture counters `{"attempted":21,"excluded_attachment":11,"no_match":7,"excluded_handled":3}`, saved with the stop details in `~/reachy-backups/phase48-boundary-031/segment-before-031.txt`; selective-shadow file copied to `selective-shadow.cohortF-end.jsonl` (5,251 bytes, 0600; the new process had not appended anything yet, identical hash). **New segment ("cohort G") starts 2026-10-12 14:06:46 UTC** (core `process_started_at`). The new counters started at `{}` and show `{"attempted":5,"excluded_channel":5}` after my probes: **5 `probe-031` turns (channel `probe-031`) to subtract from the 48B/48F windows**; no memory candidate was created (`memory_candidates` 0, `memories` 2, unchanged). Frozen code unchanged (51 of 53 files in `knowledge/`, `memory/`, `notepad_processing/` byte-identical to production before; the 2 that differ are the non-frozen `runtime.py` and `sources.py`). All Phase 48 flags are unchanged.

## Verification

- Services: core, hub, coding-agent running on the new image IDs; PostgreSQL and vLLM healthy; no traceback or error in the first minutes of any of the three logs; core env shows `MEETING_ANALYSIS_ENABLED=false` and all other flags as before.
- Feature is off: core `/meeting-analysis/config` 404 (nothing built); the hub's `/meeting-analysis/*` routes exist and answer 401 without an owner session.
- Existing functions: core `/meetings`, `/notes`, `/tasks`, `/reminders`, Notepad processing config and capture counters answer from the real data; conversation probes through the real core: tasks ("2 confirmed tasks"), a named note read verbatim, a meeting question answered from the transcript, a plain chat reply from the 7B, and a meeting question with no match answered with the fixed "couldn't find" (the meeting contains no such words).
- Speaker-label correction ("speaker_0" shown as "Speaker 1"): the meeting row is **byte-identical** to the stop-time dump (all columns, hash of the table's data block equal), the stored labels in `aligned_segments` are still `speaker_0` to `speaker_5`, so identifiers, transcript text, timestamps and the alignment are unchanged; only the display and the index text changed.
- Knowledge index: total 85 rows before and after (meeting 80 = 78 segments plus summary and minutes, note 3, task 2); `ref_key` is the primary key so a row cannot duplicate and none does (0 duplicate keys); all 78 meeting-segment rows were re-written by the indexing worker with the new text (78 start "Speaker N", 0 still "speaker_N"); outbox empty, nothing failed; retrieval and the transcript read both returned the meeting with "Speaker 1" to "Speaker 3".

**Not verified:** a browser session as the owner (the hub's owner-session routes need the login), the Android app, the robot, Telegram, the voice path, and any use of the Analysis tab (the feature is off). No regression was observed.

## Next, each needing separate authorization

Enabling `MEETING_ANALYSIS_ENABLED` for the owner-supervised trial of [phase-31 section 6](../phase-31.md) (prompt, validator and 7B frozen); until then the deployment is inert. Release the `pre-032` images and the extra dump only after the owner accepts.
