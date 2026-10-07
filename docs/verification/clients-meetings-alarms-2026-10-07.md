# Android, meetings and alarms: evidence 2026-10-07 to 2026-10-08

Dated evidence for the work between Phase 39 and the chat-history change. It is not a health check. What each feature is and how to use it is in the
[operator guide](../operator-guide.md), [Phase 40](../phase-40.md), [41](../phase-41.md), [43](../phase-43.md), [Phase 27](../phase-27.md) and
[Phase 38](../phase-38.md); decisions are in [ADR 0027](../adr/0027-alarms-and-presence-gated-delivery.md) and [ADR 0029](../adr/0029-android-companion-app.md).

## Deployed to the homelab (each time after a `pg_dump` in `~/reachy-backups`)

| Change | Revision | Backup name prefix |
|---|---|---|
| Meeting alignment | `022_meeting_alignment` | `reachy-before-alignment` |
| Audio playback endpoint, longer summaries and minutes, alarm tag and wake acknowledgement | none | `reachy-before-audio-outputs` |
| Silent-recording check | `023_meeting_audio_gaps` | `reachy-before-audio-gaps` |
| Alarm repeat and on/off, notes and reminders screens | `024_alarm_repeat` | `reachy-before-alarm-repeat` |
| Meeting titles and descriptions | `025_meeting_description` | `reachy-before-meeting-titles` |
| Core clears an alarm's delivery note on each ring (phone backup) | none | `reachy-before-phone-alarm` |
| Deleting saved chats | none | `reachy-before-chat-delete` |

After each deploy the containers were up, the revision was read back from the database, and the new code was confirmed inside the running image. The existing
meetings, alarms and chats survived every upgrade.

## Real data

- **Silent recording.** The owner's 758 s recording (made under app 0.1.1, before the foreground-service build 0.1.2 existed) holds exact digital silence from 135.0 to 173.5 s, 209 to 542 s and 595 to 734.5 s: 511 s, two thirds of it. The production worker found the same three gaps and flagged the three transcript lines that span them (the line the owner clicked, 2:13 to 2:58, is mostly inside the first). The conclusion that the old build caused it rests on timing (the foreground-service build was delivered six minutes after the recording started) and the exact zeros; it is not confirmed on the current build.
- **Real model.** The local Qwen2.5-7B named the first real meeting "Enterprise AI & Client Engagement" with an accurate one-sentence description. The summary and minutes were not rerun on the real model after the length limits were lifted, so their new quality is unjudged.
- **Real voice engine.** Piper inside the production hub image synthesised "Hello, this is a test." (1.5 s, valid WAV).

## Emulator checks (throwaway hub, in-memory stores)

Add, switch and edit an alarm; Notes create, list and back; To Do inline add and the New Reminder sheet; meeting rename; recording playback from a tapped line with a real WAV (the second line played from 6 s and was highlighted); the unfolded Fold layout (the display switched to 2208x1840 at 380 dpi) for Notes, Reminders, Meetings and Alarms, and back, mid-edit, without a crash or lost text; one reply gave one voice request and none after three tab round trips; a phone alarm scheduled, then fired with the app process killed and the hub stopped, showing the notification and playing on the alarm stream; the chat history drawer and a confirmed delete. The emulator has no audio output, so no sound was heard and Stop was confirmed only by the notification and service ending.

## Automated results at the last run

Core 718 passed, 36 skipped. Hub 427 passed, 13 skipped, 1 failed (`test_spoken_command_text_does_not_actuate_the_robot`, failing before this work). Browser fixtures 17 passed, 1 failed (the "Hey Reachy" label test in `voice.test.cjs`, also failing before). Android 55 JVM tests passed. Postgres persistence and migration tests passed on disposable pgvector containers for alignment, silence, alarm repeat, meeting descriptions and chat delete. Ruff clean from the repository root.

## Not verified

- Anything on a physical phone or Pixel Fold, including phone alarms in Doze and with the app swiped away, and the unfolded layout on the real hinge.
- Spoken replies on the owner's phone after app 0.12.1: the owner reported them silent; this could not be reproduced (the emulator detected the reply, fetched the voice and started playback; production synthesis works). Version 0.12.2 hardened playback and the cause is unconfirmed.
- The phone alarm against a real hub and robot reporting "robot unavailable" and "nobody detected", and the web UI against the production hub (no owner session in development).
- A deep-tier summary or minutes on the real GPU.
