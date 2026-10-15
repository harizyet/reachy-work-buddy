# Phase 32A.V verification: Android voice capture, enrolment and owner-match display (2026-10-15)

Branch `feature/phase-32a-voice-identity` (uncommitted working tree on `4acc4f9`). **Nothing merged, deployed or installed; the `speaker` service and `VOICE_IDENTITY_ENABLED` were never started on the homelab; no production session, schema or biometric data touched; no release APK.** Labels: *unit* = JVM/pytest with mocks; *integration* = real client code against a real in-process hub with fixture models; *real model* = the actual SpeechBrain ECAPA code on the dev box; *physical phone* = none yet.

## Results

| Check | Label | Result |
|---|---|---|
| Android JVM suite (`./gradlew :app:testDebugUnitTest`) | unit | **197 tests, 0 failures** (25 new: 13 logic, 12 model/API with a mock hub; 1 integration, below, included only when `REACHY_E2E_HUB` is set) |
| `VoiceIdentityHubIntegrationTest`: enrol (a silent clip refused and deleted, five owner clips), wrong then right password, voice turn for owner and other voice and a silent clip, session still valid after a non-match, profile delete, evaluation opt-in, labelled upload, counts, delete | integration | Passed against the fixture hub **uncalibrated** (port 18732) and **calibrated** (18733). Uncalibrated: every result "Owner match: unverified" / "inconclusive"; calibrated: "Owner voice verified" for 220 Hz, "not verified" for 440 Hz |
| Hub + shared suite (`pytest services/reachy-hub shared -m "not slow"`) | unit | 612 passed, 8 skipped (Postgres), **2 failed: `test_web_client::test_sample_responses_still_match_the_hub` and `test_calendar_feed_hub` upload test; both also fail on a pristine `4acc4f9` checkout** |
| New hub tests | unit | `test_voice_identity.py` 27, plus label tests in `test_owner_recognition.py`; PostgreSQL store test (earlier run) |
| Core Postgres migration and rollback suite with head 038 | PG (disposable container, since removed) | 103 passed, 1 skipped (earlier run; no core code changed since) |
| Speaker service contract test | unit | 6 passed |
| `ruff check` on changed Python | | clean |
| Evaluation tool against the real model over HTTP | real model | Ran end to end on public example clips: 11 clips, ECAPA, 0.23 s per 1.8 s clip on the dev box (2 threads). **Pipeline rehearsal only**: two public speakers cut into 1.8 s pieces (5 enrol, 4 held-out, 2 "other"), so its error rates mean nothing and are not reported as results |
| APK | build | `app-debug.apk` 0.20.0 (versionCode 5), 17.7 MB, sha256 `01c1a821…ef6`, `~/reachy-releases/reachy-companion-0.20.0-voice-identity-debug.apk`. Permissions unchanged from 0.19.0 (`RECORD_AUDIO` was already declared) |

## Requirement check

| Requirement | Where it is met |
|---|---|
| One capture path shared by STT and speaker check | `PcmCapture` → one WAV → `/voice-identity/turn?converse=false`; hub STT and verifier read the same bytes (hub test asserts the STT saw exactly the verified bytes) |
| Multi-sample enrolment, consent, quality, cancellation, deletion | Enrolment screen; consent box and password required before save (model test: nothing is sent without consent); per-clip quality reason and delete; cancel drops the hub's draft; profile delete behind the password |
| Unverified / inconclusive until calibration | `ownerMatch()`: unit test proves no state renders as verified while uncalibrated; integration test proves it end to end against an uncalibrated hub |
| Voice chat survives failure | The transcript goes through the unchanged `/messages` path; hub tests show a turn works with no profile or an outage; the integration test shows a non-match leaves the session valid; the app can fall back to the phone's recogniser |
| No extra permissions from a match | Nothing reads a result except the label; the wording test forbids unlock/allow/permission/access; the hub never passes evidence to core; a hub test shows a verified owner still gets core's "can't accept that confirmation by voice" |
| Privacy of audio, embeddings, evidence | Audio is in memory only (buffer zeroed), never logged or written; the app stores no result; the hub returns state and expiry, never a score or vector (tested); embeddings live in hub memory (drafts), the stateless sidecar and ciphertext at rest |
| Debug APK, not installed | Built and checksummed only |
| HTTPS deferred | No TLS, certificate, proxy or cookie-secure change; cleartext allowance untouched |

## Architecture changes this slice

1. `POST /voice-identity/turn` gained `converse=false`, which stops after transcript and state (default unchanged).
2. The benchmark store's voice clips gained an optional validated `label` (additive field on `EnrollmentSample`, header `X-Reachy-Benchmark-Label`, export manifest). Existing sidecar metadata loads unchanged.
3. Android: `PcmCapture`, `Endpointer`, `Wav`, `VoiceIdentityModel`, `VoiceIdentityScreen`, `GvScreen`, owner-match line in voice mode, two new preferences (`installId`, `phoneRecognizer`), the voice-identity API methods. See [ADR 0041](../adr/0041-shared-voice-identity.md#android-client-phase-32av-added-2026-10-15).
4. `tools/voice_identity_benchmark.py` now ingests the app's export, treats replay and synthetic clips as attacks, and reports threshold candidates.
5. Fixture `clients/android/e2e/android_voice_identity_hub_server.py` and the integration test.

## Not verified / open

- Nothing ran on a physical phone: microphone behaviour of `AudioRecord` with the `VOICE_RECOGNITION` source, endpointing in real rooms (the energy gate may clip quiet speakers or trigger on loud noise), fold/unfold, Bluetooth routes and hub-down behaviour on the device are all unverified. The [UAT checklist](phase-32a-uat-checklist.md) lists them.
- The enrolment consistency limit (0.35), the quality limits (1.5 s speech, -45 dBFS, 2% clipping) and the 10 s result lifetime are uncalibrated engineering placeholders.
- No threshold is selected or active. No owner data has been collected, so no real FAR/FRR exists.
- The evaluation clips are raw audio on the hub until deleted; persistence needs `OWNER_RECOGNITION_CAPTURE_DIR` and `SECRET_KEY_FILE`.
- Over plain HTTP outside the tailnet, voice audio is readable on the network (owner-accepted, HTTPS deferred).
- Hub-side STT latency for a voice turn on the homelab is unmeasured; the extra upload plus the unchanged `/messages` call make a voice turn two round trips.
- The 32A.1 session-revocation work, 32A.M meeting matching and a web enrolment UI are not part of this slice.
