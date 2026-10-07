# Phase 40: Android companion app

Status: **started 2026-10-07.** Decision: [ADR 0029](adr/0029-android-companion-app.md). Build and run steps: [clients/android/README.md](../clients/android/README.md).

User-centred phone client: Talk (voice and chat), To-do, Notes, Meetings. Configuration stays in the web control panel.

## Stages

| Stage | Work | State | Gate |
|---|---|---|---|
| 40.0 Documents | Roadmap row, this page, ADR 0029 | **Done 2026-10-07** | Owner can redirect scope |
| 40.1 Client foundation | Gradle/Compose project, hub API client (cookie login, CSRF), sign-in screen | **Done 2026-10-07** | JVM tests with a mock hub server |
| 40.2 Talk | Chat, mic button (phone speech recognizer, voice modality), optional spoken replies | **Chat verified in an emulator; mic and spoken replies not verified** (emulator has no audio) | Real phone |
| 40.3 To-do and Notes | List, add, complete, delete; notes create/edit/delete | **Implemented**; To-do add verified through chat in an emulator | Real phone |
| 40.4 Meetings | Record AAC/m4a (foreground service: survives tab switches, standby and other apps; recording bar on every screen; failed uploads kept and retried), upload, status list, transcript view | **Record, tab-switch, background/screen-off, notification Stop, failed-upload retry verified in an emulator** against an in-memory hub; transcript view tested only by unit test | Real hub with transcription |
| 40.5 Acceptance on a phone | Install the debug APK, sign in to the homelab hub, talk, add a task, record a short meeting | **Pending (owner)** | Owner |

## Not in this phase

Push notifications, alarms and Activity views, settings screens, Play Store signing.
