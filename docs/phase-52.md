# Phase 52: Voice command to start a meeting recording (Android)

Built on `feature/voice-meeting-recording` (from `main` at `f6d659a`) and merged to `main` 2026-10-14. **No server change.** The owner tested the voice command, the typed command and short-recording handling on a phone and reported them working.

## Behaviour

In Talk's full-screen voice mode, the owner says "Reachy, begin meeting recording." Reachy says "Okay, I'll end our conversation and start recording the meeting.", the voice screen closes, the existing meeting recorder starts, and the app opens Meetings with the recording bar and **Stop and save**.

**Root cause:** the Android app sent every spoken sentence to the hub as an ordinary chat turn. Nothing on the phone recognised an application-side action, and the hub has no tool that can start the phone's microphone, so Reachy could only answer in words. There was no existing client-side command framework to reuse.

## Design

- **Recogniser** (`data/RecordingHandoff.kt`, `isMeetingRecordingCommand`): deterministic, whole-utterance match of "begin/start meeting recording", "begin/start recording (this|the|a) meeting" and "record (this|the|a) meeting", with optional "Reachy", "please", "can you". Questions and longer sentences that only mention recording stay ordinary chat. It runs on final speech results in voice mode, and on a typed chat message (same match; typing skips the spoken confirmation and the voice teardown, since there is no voice conversation, and goes straight to the same permission/foreground checks and recorder start), on the phone: the sentence is not sent to the hub, and no reply or model output can start a recording.
- **Handoff** (`RecordingHandoff`, pure and JVM-tested): `Idle → Confirming → EndingVoice → StartingRecording → Idle`, each handoff numbered so a late or repeated callback is ignored. Steps: check microphone permission, an already-running recording and that the app is resumed; speak the confirmation and wait for the speech engine's own completion (hub voice with the phone's voice as fallback; a failure is reported separately from completion, `SpeechOutput.speak(onFailed)`); re-check; end voice (recogniser destroyed, playback stopped, audio focus abandoned, screen closed) before the recorder is asked for the microphone; `RecordingController.start`; wait on `RecordingController.recording`/`error` (the service sets `recording` only after `MediaRecorder.start()` succeeded); report success only then.
- **Wiring** (`AppViewModel`): the handoff lives in the view model, so a tab switch or activity recreation after the recorder was asked to start still ends in a correct outcome. The Talk screen supplies the voice side while voice mode is open (`VoiceSide`). Success opens Meetings through `openRequest` (the Shell consumes it like the reminder deep link).
- **Stale callbacks:** `SpeechInput` ignores callbacks from a recogniser that was stopped or replaced. While a handoff runs, listening, replies and the voice-source switch are held off. A reply that arrives while a handoff runs or a recording is running is not read aloud (it would be recorded, and in voice mode it must not reopen the conversation).
- **Cancellation:** closing voice mode, the Talk screen leaving composition, `ON_PAUSE` (leaving the app) and sign-out cancel a handoff that has not yet asked the recorder to start, and nothing is recorded. Once the recorder has been asked to start it cannot be recalled; the recording bar's Stop is the way out.

## Failure behaviour

| Case | Result |
|---|---|
| Microphone permission missing (revoked since voice mode opened) | Nothing spoken or recorded; message in Talk; voice resumes. The app does not open a permission dialog from the command. |
| Confirmation fails or cannot speak | No recording; message; voice resumes. |
| Confirmation interrupted by closing voice mode or leaving the app | Cancelled; no recording. |
| Recording already running | No second recording; message; conversation continues. |
| Repeated command / duplicate callback | Dropped. |
| Recorder fails (`error` set by the service) or request throws | Failure shown on Meetings (`recordError`); never announced as started. |
| Recorder silent for 15 s | "Did not confirm" message; the recording bar appears if it starts later. The timeout is a failure guard only, never sequencing. |

## Limits

- Notification permission (Android 13+) is not requested by this path; as with a reminder's Record, recording works without it but the notification may be hidden.
- If the phone's recogniser still holds the microphone when the recorder starts, the start fails and is reported (no automatic retry).
- The recogniser must hear "begin meeting recording"; a misheard wake word before it (it is optional) does not matter, but a misheard command is just ordinary chat.

## Verification

JVM tests: `RecordingHandoffTest` (18: phrases, typed command, ordering, interruption, permission, duplicate, stale, cancel, lifecycle, recorder failure). Full suite 146 passing (incl. ShortRecordingTest). See [the record](verification/voice-meeting-recording-2026-10-14.md).

## Short recordings (added 2026-10-14)

A recording stopped by any route (bar, Meetings, notification, either command) is timed by the service. **Under 10 s:** the clip is deleted, nothing is uploaded, and Meetings shows why. **10 to under 30 s:** the clip is held in `held-meetings/` (not `pending-meetings/`, so no retry uploads it early) and a dialog asks "It looks like the meeting recorded is only N seconds long. Was it a mistake?" with *Upload and analyse* (moves it to the normal queue and uploads it) or *Delete it*. The dialog cannot be dismissed by tapping outside, and returns after the app is reopened; a stop from the notification with the app away posts a notification pointing back to it. **30 s and over:** unchanged. A recording killed with the app still goes to the normal queue. The decision (`data/ShortRecording.kt`) is JVM-tested; the dialog, held-clip files and notification need a phone: record 5 s (expect deletion), 20 s (expect the dialog; try both answers, and reopening the app with it unanswered), and 40 s (expect a normal upload). Calendar-linked recordings that are discarded or deleted are not marked recorded, so the meeting can be recorded again.

## Open for the owner

Physical acceptance on a real phone (below), then approval to build/install an APK. No server deployment is involved: an APK rebuild is sufficient.

1. Talk → voice mode → say "Reachy, begin meeting recording."; the acknowledgement is heard completely; voice mode closes; Meetings opens with the timer and bar.
2. Lock the phone 30 s or more, unlock: still recording. Stop and save: the clip uploads through the normal pipeline.
3. The uploaded recording does not contain the confirmation speech.
4. Repeat with microphone permission revoked, and with a second command while recording.
5. Say a sentence that only mentions recording ("what happens when I record a meeting?"): ordinary reply, no recording.
