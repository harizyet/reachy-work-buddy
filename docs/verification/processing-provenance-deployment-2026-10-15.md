# Processing provenance and fixed email disclosures: deployment for UAT (2026-10-15)

Owner authorization: "Deploy for UAT", then "I allow it" after the permission layer had refused the first production reads. Branch `feature/processing-provenance-disclosure` (`82305d0`), not merged. Decision: [ADR 0040](../adr/0040-verified-processing-provenance-in-email.md); evidence before deploy: [verification](processing-provenance-disclosure-2026-10-15.md).

| | Before | After |
|---|---|---|
| Schema revision | `036_meeting_email` | `037_processing_provenance` |
| core | `a1102695b5c5` | `74e7161195ea` (tag `p56-82305d0`) |
| hub | `e1844aae58dc` | `c9906ef5b62a` |
| coding-agent | `79d31e4f6f0e` | `9a98434aa79c` |
| migrate | `f79347c7c651` | `b3ae77c2f0d1` |

`MEETING_EMAIL_ENABLED` stays true, `.env` untouched. Core's environment is identical before and after (name and value fingerprints compared, `core-env-{before,after}-037.txt`). Document worker, vLLM, transcription, diarization, semantic router, SearXNG and Postgres untouched; PgBouncer restarted.

## Timeline (UTC, 2026-10-15)
Preconditions checked first: no reminders, no queued or sending email (one earlier meeting email already `sent` to the owner, one sender test), no meeting being processed; the only scheduled alarm is the stale 2026-10-07 one that was already there. 01:51:49 core, hub and coding-agent stopped; dump; restore verified; migration applied; 01:52:36 started. Downtime about 47 s.

## Backup and rollback
| Item | Value |
|---|---|
| Stop-time dump | `~/reachy-backups/reachy-before-037-stop-20261015-015152.dump` (0600, 1,911,898 bytes). **Restore verified** in a disposable container: revision 036, meetings 2, drafts 2, mail_sender 1, secrets 6, all equal to production. |
| Row counts | `~/reachy-backups/rowcounts-before-037.txt` |
| Images | `reachy-rollback/{companion-core,reachy-hub,coding-agent-service,migrate}:pre-037`, each verified equal to the running image before the build |
| SecretStore key file | unchanged (`secret-keys-before-037.json` is an identical copy; keep an off-host copy) |
| Schema rollback | `deploy/homelab/rollback-037.sql` with the services stopped, then retag `pre-037` and start; the last line must print `036_meeting_email`. It drops only `processing_events` and `owner_name`. Cancel or discard unsent meeting-minutes drafts first. |
| Status | **Not invoked.** Keep until the owner accepts. |

## Phase 48 boundary
Counters read with core's token before the stop: previous segment (started 2026-10-14T15:54:16Z) `{}`, saved in `~/reachy-backups/phase48-boundary-037/` with stop and start times and a copy of the shadow-router files. **New segment from 2026-10-15T01:52:38Z.** No frozen Phase 48 file is in the change; no conversation probes were sent.

## Verification
- Schema `037_processing_provenance`; row counts equal; `meetings.processing_events` empty on both existing meetings (they will read as unverified); the sender row kept its settings and credential (`configured`, `verified_ok` true, `owner_name` empty).
- Core, hub and coding-agent on the new image IDs; core and hub `/health` 200; no traceback or error in the first two minutes of any log; `/home`, `/meeting-email/config`, `/meeting-analysis/items`, `/reminders`, meetings and tasks answer; the hub serves the new web build (it contains "Your name").
- Classification of the live configuration, from host names only: local model host `vllm` is **local**; the cloud role host is a public name and is the external role. Transcription and diarization are `transcription` and `diarization` on the Compose network, so new meetings will record **local**.

**Not verified:** the owner session in a browser, the phone, a real Gmail send with the new text, a new meeting going through the real worker (so no real provenance record exists yet), the Android cards.

## To continue UAT
1. Settings > Accounts > Outbound meeting email: enter **Your name**, Save sender. Changing the name does not switch sending off.
2. Share minutes on a meeting and Prepare. For the existing meetings the message must show the **neutral** statement, never the local-only one, plus the Gmail delivery sentence. The fixed opening and closing text appears read-only around the message box.
3. To see the local-only sentence, process a new recording (or write its summary and minutes again after it has been transcribed under this build) and prepare again. To see the external wording, write a summary with the cloud model once.
4. Approve with `SEND` to your own address only, wait the delay, and compare the delivered email with the preview.
