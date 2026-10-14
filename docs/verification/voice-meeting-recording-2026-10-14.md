# Voice-to-meeting-recording: local verification (2026-10-14)

Scope: Android only, [Phase 52](../phase-52.md). **Labels: JVM unit tests and a compile only. No emulator run, no device, no APK installed, no recording started, no server touched.**

| Check | Result |
|---|---|
| `./gradlew :app:testDebugUnitTest` | 146 tests, 0 failures (126 existing + 18 in `RecordingHandoffTest` + 2 in `ShortRecordingTest`) |
| `./gradlew :app:compileDebugKotlin` | passes |

Covered by tests: recogniser accepts the explicit phrases and rejects questions and longer sentences; confirmation precedes voice end, which precedes recorder start; success only after the recorder reports active; recorder failure and a throwing request are failures; failed or interrupted confirmation, no speech engine, missing or revoked permission, existing recording (before and during the confirmation), repeated command and repeated completion, cancel during confirmation with a late completion, a completion from an older handoff, app not in foreground (at start and after the confirmation), cancel while voice is closing, and no cancel once the recorder was asked to start.

Not covered by any automated check, and needed on a phone: `SpeechInput` generation guard and `SpeechOutput` failure signalling (Android classes), the Compose wiring in `TalkScreen`, `ON_PAUSE` cancellation, whether the recogniser has released the microphone by the time the recorder starts, the foreground-service start from the voice screen, that the confirmation is absent from the recorded clip, lock-screen continuity and the upload. Stop and save and the upload path are unchanged (`RecordingService`/`uploadPending` untouched).

Phone: the owner reported the voice command, typed command and short-recording handling working (2026-10-14); no itemised log was kept.
