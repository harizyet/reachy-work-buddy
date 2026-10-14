# Phase 54 deployment: migration 035 and coordinated cutover, for owner UAT (2026-10-14)

Owner authorization (2026-10-14): controlled deployment for owner real-voice UAT; **no merge to main**. Stop after verification.

| | Before | After |
|---|---|---|
| Schema revision | `034_meeting_multimodal` | `035_meeting_speaker_identity` |
| core | `e92463cc8334` | `49abbb72f181` (tag `p54-2eb78ba`) |
| hub | `a88e77f55dfc` | `14dce6fc38ff` |
| coding-agent | `7d8773f1e006` | `724e259ac97e` |
| migrate | `966642fe0c5a` | `1e16a6568c74` |

Built from commit `2eb78ba` (branch `feature/meeting-speaker-identification`, pushed). Document worker, vLLM, transcription, diarization, semantic router, PgBouncer config and `.env` untouched (flags unchanged; core env fingerprint identical before and after).

## Timeline (UTC)
09:47:43 core, hub, coding-agent stopped gracefully (PgBouncer restarted); stop-time dump; dump restored into a disposable container and compared; migration applied; 09:49:25 services started. Application downtime about 1 min 42 s.

## Backup and rollback
| Item | Value |
|---|---|
| Stop-time dump | `~/reachy-backups/reachy-before-035-stop-20261014-094755.dump`, 1,861,950 bytes, 0600, sha256 prefix `16072fb28ca1529e`, 59 table-data entries; **restore verified** (revision 034 and all row counts identical) |
| Row counts | `~/reachy-backups/rowcounts-before-035.txt` (meetings 2, documents 0, tasks 2, notes 3, reminders 0, alarms 9, knowledge_items 751) |
| Images | `reachy-rollback/{companion-core,reachy-hub,coding-agent-service,migrate}:pre-035` (each verified equal to the running image ID before the build) |
| Env fingerprint | `~/reachy-backups/core-env-before-035.txt` |
| Schema rollback | `deploy/homelab/rollback-035.sql` in one transaction with the services stopped (drops one column; names in `speaker_names` stay; revision returns to 034), then retag the `pre-035` images and `up -d --no-build --no-deps` the three services |
| Status | **Not invoked.** Keep everything until the owner accepts. |

## Phase 48 boundary
Counters were read with core's service token before the stop (documented route; no access gate was hit): previous segment (process start 2026-10-14T07:57:52Z) counters `{}`, saved with the stop/start times and the selective-shadow file copies in `~/reachy-backups/phase48-boundary-035/`. **New segment starts 2026-10-14T09:49:27Z.** No frozen Phase 48 file is in the commit (checked by diff against main). No conversation probes were sent, so no verification turns need subtracting.

## Verification
- Schema 035; column `meetings.speaker_identity` jsonb nullable; all existing rows NULL (read as no identities).
- Data: row counts identical; the two meetings' content hash (transcript, diarization, alignment, names, summary, minutes, status, updated_at) identical to the dump; knowledge index 751 rows, 0 duplicate keys, outbox empty.
- Services on new image IDs; hub and core `/health` 200; no traceback/error in 10 minutes of core, hub and coding-agent logs; other services healthy.
- Flags unchanged: knowledge indexing/retrieval/shadow, memory candidates and capture, notepad processing, document library, meeting analysis and multimodal all true as before.
- Existing features answered from real data through core: meetings (2), tasks (2), notes (3), reminders (0), calendar next/due, home, document-library, analysis and multimodal configs.
- New feature on the real meetings: `GET /meetings/{id}/speakers/identify` returned samples for every speaker of both meetings; ranged audio reads (the path a sample plays through) returned 206 on both recordings.
- Hub: `/web/` 200 and serves the build containing "Identify speakers"; `/meetings` and `/meetings/x/speakers/identify` answer 401 without a session.

**Not verified:** an owner-session browser login (no credential used), the Android app, a new recording upload, transcription/diarization of a new meeting, Telegram, the robot, voice, a real document upload. No regression observed.
