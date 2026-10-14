# Phase 55 deployment: migration 036 and coordinated cutover, feature OFF (2026-10-14)

Owner authorization (2026-10-14): "build and deploy for UAT". The schema, images and web/Android code were deployed first with the flag off (the first write of the flag was blocked by the permission layer and not worked around); **the flag was then enabled on the owner's explicit instruction ([below](#activation-2026-10-14-owner-enable-the-flag))**. No sender is configured, no credential exists, no email has been sent. Deployed from branch `feature/sender-test-email` (head `6bb7f46`; includes Phase 55 and the sender test email), **not merged to main**.

| | Before | After |
|---|---|---|
| Schema revision | `035_meeting_speaker_identity` | `036_meeting_email` |
| core | `49abbb72f181` | `8381632b0fc1` (tag `p55-6bb7f46`) |
| hub | `14dce6fc38ff` | `e1844aae58dc` |
| coding-agent | `724e259ac97e` | `79d31e4f6f0e` |
| migrate | `966642fe0c5a` | `f79347c7c651` |

Document worker, vLLM, transcription, diarization, semantic router, PgBouncer config and `.env` untouched. Core's environment differs from before by exactly one variable, the new pass-through `MEETING_EMAIL_ENABLED=false`.

## Timeline (UTC, 2026-10-14)
15:29:18 core, hub and coding-agent stopped gracefully (PgBouncer restarted), stop-time dump, restore verified, migration applied, 15:30:24 services started. Application downtime about 1 min 6 s.

## Backup and rollback
| Item | Value |
|---|---|
| Stop-time dump | `~/reachy-backups/reachy-before-036-stop-20261014-152925.dump`, 1,896,376 bytes, 0600, sha256 prefix `60ba70ba31ffad28`, 59 table-data entries; **restore verified** (revision 035, all counts equal) |
| Row counts | `~/reachy-backups/rowcounts-before-036.txt` |
| Images | `reachy-rollback/{companion-core,reachy-hub,coding-agent-service,migrate}:pre-036` (each verified equal to the running image before the build) |
| SecretStore key file | copied to `~/reachy-backups/secret-keys-before-036.json` (0600, identical), because the sender credential will be encrypted with it. **Same host only: keep an off-host copy.** |
| Env fingerprint | `~/reachy-backups/core-env-before-036.txt` |
| Schema rollback | `deploy/homelab/rollback-036.sql` with the services stopped (deletes meeting drafts, history, sender settings, groups and the stored credential; plain drafts and meetings stay; a sent message stays sent), then retag the `pre-036` images and start them; the last line must print `035_meeting_speaker_identity` |
| Status | **Not invoked.** Keep until the owner accepts. |

## Phase 48 boundary
Counters read with core's token before the stop (documented route, no gate hit): previous segment (started 2026-10-14T09:49:27Z) `{}`, saved with stop/start times and the shadow-file copies in `~/reachy-backups/phase48-boundary-036/`. **New segment from 2026-10-14T15:30:26Z.** No frozen Phase 48 file is in the change; no conversation probes were sent.

## Verification (feature off)
- Schema `036_meeting_email`; the four new tables exist and are empty; `email_drafts` still 0 rows; row counts identical; the two meetings' content hash (including speaker names and identities) identical to the dump; knowledge index 751 rows, 0 duplicate keys, outbox empty.
- Services on the new image IDs; hub and core `/health` 200; no traceback or error in the first minutes of any log; other services healthy.
- Core answers meetings, tasks, notes, reminders, calendar, home and the document, analysis, multimodal and capture-counter routes from the real data; `/meeting-email/*` is 404 (feature off); the hub's meeting-email routes answer 401 without an owner session; the hub serves the new web build (contains "Share minutes").

**Not verified:** the owner session in a browser, the phone app, anything with the feature on (it is off), any real Gmail behaviour, a real recording upload, Telegram, robot, voice.

## Activation (2026-10-14, owner: "enable the flag")

`MEETING_EMAIL_ENABLED=true` added to `deploy/homelab/.env` (backup `.env.bak-before-meeting-email`, kept beside it; the diff showed exactly one added line) and **only core recreated** (graceful stop, `up -d --no-build --no-deps --force-recreate companion-core`, same image `8381632b0fc1`; hub, coding-agent, worker and database untouched). Preconditions: no alarm, reminder, analysis run or queued email within 15 minutes. Core stopped 15:33:56 UTC, running again 15:34:15 (about 19 s); **new Phase 48 segment from 15:34:17 UTC**; the previous segment's counters (`{}`) are in `~/reachy-backups/phase48-boundary-036-flag/`.

Verified from inside core with the service token: the only environment difference is `MEETING_EMAIL_ENABLED` (now true); `/meeting-email/config` and `/sender` answer, reporting `enabled: true`, the sender **not configured and sending off, no credential**; `/meeting-email/drafts` and `/groups` answer (empty); `email_drafts` has 0 rows; meetings, tasks, notes, reminders, home, document, analysis, multimodal and capture routes answer; no error in the logs; the hub's meeting-email routes answer 401 without an owner session. **Not verified:** the owner's browser session (Settings card, Share minutes), the phone, and anything involving a real mailbox. **Rollback:** set the flag to false (or restore `.env.bak-before-meeting-email`) and recreate core; drafts and settings stay but become unreachable.

## To start UAT
1. ~~Enable the flag~~ done (above).
2. The owner enters the dedicated Gmail details in Settings > Accounts > Outbound meeting email (the password goes through the form once; nothing in this deployment ever sees it), Verifies, turns sending on, and uses **Send a test email** to their own address.
3. Install the Android debug APK `~/reachy-releases/reachy-companion-0.19.0-share-minutes-debug.apk` (sha256 `e4251b85595d50a03cad50de22ca8c9abc3b6a8d94ee6db120f35cd41b391528`; version still 0.19.0, replaces other 0.19.0 debug builds), then follow the UAT checklist in [Phase 55](../phase-55.md#uat-checklist).
