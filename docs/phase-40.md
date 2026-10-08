# Phase 40: Android companion app

Status: **built through app version 0.14.0 (2026-10-08); not yet accepted on a physical phone or Fold.** Decision: [ADR 0029](adr/0029-android-companion-app.md). Build and run steps: [clients/android/README.md](../clients/android/README.md).

User-centred phone client: Talk (voice and chat), Reminders (To Do and timed reminders), Notes, Meetings and Alarms. Configuration stays in the web control panel.

## Stages

| Stage | Work | State | Gate |
|---|---|---|---|
| 40.0 Documents | Roadmap row, this page, ADR 0029 | **Done 2026-10-07** | Owner can redirect scope |
| 40.1 Client foundation | Gradle/Compose project, hub API client (cookie login, CSRF), sign-in screen | **Done 2026-10-07** | JVM tests with a mock hub server |
| 40.2 Talk | Chat, mic button (phone speech recognizer, voice modality), optional spoken replies | **Chat verified in an emulator; mic and spoken replies not verified** (emulator has no audio) | Real phone |
| 40.3 To-do and Notes | List, add, complete, delete; notes create/edit/delete | **Implemented**; To-do add verified through chat in an emulator | Real phone |
| 40.4 Meetings | Record AAC/m4a (foreground service: survives tab switches, standby and other apps; recording bar on every screen; failed uploads kept and retried), upload, status list, transcript view | **Record, tab-switch, background/screen-off, notification Stop, failed-upload retry verified in an emulator** against an in-memory hub; transcript view tested only by unit test | Real hub with transcription |
| 40.5 Acceptance on a phone | Install the debug APK, sign in to the homelab hub, talk, add a task, record a short meeting | **Pending (owner)** | Owner |
| 40.6 Meeting review | Speakers on every line from the server alignment; tap a line to play the recording from it (download-then-play, with a seek bar); Edit on a line; silent-recording warning and per-line flags; editable title and description with "write again"; summaries, minutes and deep reruns (see [Phase 41](phase-41.md), [43](phase-43.md)) | **Done 2026-10-07/08** (app 0.5.0 to 0.12.0); playback verified on an emulator with a real WAV | Real phone |
| 40.7 Talk polish | Selectable chat text; replies read aloud in Reachy's own voice (streamed with `POST /speech/stream` from 0.15.0, phone voice as fallback), a full-screen voice mode with an animated ball and a voice-source choice, Reachy or this phone (0.15.0), each reply once, not again on a tab change; previous chats in a drawer (a side panel when unfolded) with open and delete | **Done 2026-10-07/08** (0.7.0, 0.12.1/0.12.2, 0.14.0) | Owner has not confirmed spoken replies on the phone after 0.12.1 (see HANDOVER) |
| 40.8 Alarms | Apple-Clock-style Alarms tab: big times, switches, Edit, Add/Edit sheet with time wheels, Repeat, Label, Sound, Volume (backend `repeat`/`enabled`, [Phase 38](phase-38.md)) | **Done 2026-10-07** (0.8.0); add and switch verified on an emulator | Real phone |
| 40.9 Notes and Reminders | Apple-Notes-style Notes (month-grouped list, search, full-screen editor, first line is the title, autosave); Apple-Reminders-style Reminders tab (lists home, To Do, Scheduled, inline add/rename, Completed, New Reminder sheet; swipe to delete) | **Done 2026-10-07** (0.9.1, 0.10.0); verified on an emulator | Real phone |
| 40.10 Pixel Fold | The activity handles configuration changes itself; windows 600 dp or wider get a navigation rail and two panes for Notes, Meetings, Reminders and Talk's chat history | **Done 2026-10-07** (0.11.0); verified by switching an emulator to the Fold's inner size and back mid-edit | A physical Fold |
| 40.11 Phone alarm backup | The phone keeps an exact clock alarm for each live alarm and rings it when Reachy was offline, found nobody, or could not play it; works with the app closed ([ADR 0027 addendum](adr/0027-alarms-and-presence-gated-delivery.md)) | **Done 2026-10-07** (0.13.0); verified on an emulator with the app process killed and the hub down | A physical phone, and a real hub plus robot "offline"/"nobody detected" outcome |

## Not in this phase

Push notifications from the hub (the phone backup alarm polls instead), an Activity view, settings screens, Play Store signing and release builds: the APKs are debug builds delivered by hand. Dark theme tuning, hinge/posture awareness on the Fold, and phone-side playback of a chosen radio station are not built.
