# Phase 32: Shared voice identity, phone-first rollout and deferred robot deployment

Status: **G0 approved by the owner 2026-10-15 (with the HTTP amendment below). 32A.V is implemented in isolation on branch `feature/phase-32a-voice-identity`: not merged, not deployed, no production session, schema or biometric data touched, no APK built. The Android slice of 32A.V is built (debug APK, not installed). 32A.M and 32A.1 to 32A.5 are not started. 32B is deferred.** Inventory: [32A.0 record](verification/phase-32a0-inventory-2026-10-15.md). Decision record: [ADR 0041](adr/0041-shared-voice-identity.md).

Baseline: `main` at `4acc4f9` (2026-10-15 review). This page supersedes the **delivery sequence** of the Phase 32 row in [plan.md](plan.md#6-implementation-roadmap), not the underlying [Phase 25](phase-25.md) security contracts. Nothing here authorizes a deployment, an API/schema change or enabling a verifier; each gate below needs the owner.

## G0 decisions (owner, 2026-10-15)

| # | Decision | Where it lands |
|---|---|---|
| 1 | Server-side, per-device revocable sessions, keeping the 12-hour idle expiry initially | 32A.1; design in [ADR 0041](adr/0041-shared-voice-identity.md) decision 9. Changes production sessions, so a separate approval gate. Not built |
| 2 | **Amended: HTTPS is deferred.** Reachy stays on authenticated HTTP over trusted private connectivity, mainly Tailscale. No TLS certificates, reverse proxies, HTTPS migration or certificate management in 32A. Speaker verification, enrollment and profile endpoints are not exposed publicly. Existing authentication and authorization stay. Stored templates and enrollment artifacts are encrypted. HTTP's limits are documented ([ADR 0041 threat model](adr/0041-shared-voice-identity.md#threat-model-transport-focused)). **HTTPS is a separate future security-hardening task** (see below) | 32A.V and 32A.1; the original "require HTTPS, no cleartext exceptions" is withdrawn |
| 3 | One phone audio capture pipeline feeding Reachy's existing on-premises STT and the speaker verifier; reuse meeting audio where possible | `POST /voice-identity/turn`; meeting matching reads the stored recording (32A.M) |
| 4 | Transport-neutral speaker evidence with device, client and session provenance; robot interfaces stay compatible | `VoiceEvidence` + `to_speaker_evidence()` |
| 5 | Encrypted, versioned profiles in the existing database; keys outside it; enrollment, re-enrollment, deletion | Migration `038_voice_profiles`, keyring file |
| 6 | ADR for shared voice identity; amend ADR 0038 before biometric embeddings | [ADR 0041](adr/0041-shared-voice-identity.md); [ADR 0038 amendment](adr/0038-meeting-speaker-identification.md) |
| 7 | Verifier on the existing home server, CPU-first, established embedding implementation, measure before any GPU | `speaker` sidecar, SpeechBrain ECAPA-TDNN |

Further requirements: enrollment starts on Android; enrolled identities are reusable across supported clients; meeting identification builds on existing diarization and manual assignment with unknown handling and owner confirmation; voice is identity evidence, never authorization; no unnecessary second microphone path; no automatic enrollment of attendees; voice chat and meeting recording behave as before; the robot, camera and fusion stay deferred. Do not merge, deploy, change production sessions, migrate production biometric data or build/install a release APK without a separate approval gate.

### Future hardening task: HTTPS (not scheduled)

Owner-deferred 2026-10-15. When it is taken up it needs its own plan: TLS in front of the hub (or tailnet-issued certificates), `SESSION_COOKIE_SECURE=true`, removing the Android cleartext allowance, and re-pinning the origin. Until then 32A deliberately does none of that, and the document set describes the exposure honestly: the session cookie, voice audio and results cross the phone-to-hub hop in clear unless that hop is the tailnet, and the Compose-internal hops are plain HTTP.

## 32A.V implementation status (isolated)

| Piece | State | Where |
|---|---|---|
| Speaker-embedding sidecar (stateless, CPU, pinned model, token, profile `speaker`) | Built; contract tests pass; run against the real model through the sidecar code on the dev box (192-d, same-speaker 0.53 vs different -0.01 on the two Phase 25a.1 clips, 3 s embed p50 0.36 s with 2 threads). No homelab measurement yet | `deploy/homelab/speaker/`, `deploy/homelab/tests/test_speaker_service.py` |
| Shared models and route constants | Built | `shared/models/voice_identity.py`, `shared/protocols/voice_identity_api.py` |
| Encrypted profile store (memory + PostgreSQL), migration 038, `rollback-038.sql` | Built; tested on a disposable PostgreSQL including the full core migration/rollback suite | `reachy_hub/voice_profiles.py`, `migrations/versions/038_voice_profiles.py` |
| Enrollment drafts, consent, reauth-gated commit/delete, verification, evidence ledger, combined turn route | Built; 25 hub tests | `reachy_hub/voice_identity.py`, `tests/test_voice_identity.py` |
| GV benchmark tool (confusion matrix, FAR/FRR with Wilson intervals, per-condition, sweep, latency) | Built; arithmetic tested; **not run on real owner/non-owner audio** | `tools/voice_identity_benchmark.py` |
| Android enrolment UI, single PCM capture client, owner-match display, GV evaluation screen | **Built** (debug APK 0.20.0, not installed): 25 new JVM tests, plus an integration test of the real client code against a real in-process hub in both uncalibrated and calibrated modes; full suite 197 passing. **No physical-phone run yet** | `clients/android/`, [verification record](verification/phase-32a-android-2026-10-15.md), [UAT checklist](verification/phase-32a-uat-checklist.md) |
| Web enrollment | Not planned for this slice (enrollment starts on Android) | |
| GV evaluation tool and protocol | Tool reads the app's labelled export (or fetches it), classifies replay/synthetic as attacks, reports threshold *candidates* with observed rates and intervals, selects nothing. Rehearsed on public clips only | `tools/voice_identity_benchmark.py`, [GV protocol](verification/phase-32a-gv-protocol.md) |
| Calibration, spoof/replay probes, held-out physical-phone trials, delete/re-enroll proof on the device, latency on the homelab | **Not done**: gate GV is open. No threshold is selected or active | needs the owner and the phone |

The verifier stays disabled and uncalibrated: `VOICE_IDENTITY_ENABLED=false`, thresholds unset, and with no approved thresholds no result is ever `verified`.

## 1. Decision and objective

Build one reusable, on-premises voice-identity capability across trusted Reachy clients, starting with enrollment and live testing on Android. It must verify whether a live voice utterance is the owner and help name diarized speakers in meeting recordings. Activating recognition on the physical robot (microphones, camera, direction sensing, fusion, motion) is deferred.

| Part | Scope | Status |
|---|---|---|
| **32A** Shared voice identity, phone-first | One encrypted voice-profile registry and inference API; owner enrollment; calibrated verification of trusted-client voice turns; consented meeting-speaker matching and review; Android session/privacy hardening | Active planning |
| **32B** Robot owner recognition | Adapt the verified model to robot microphone conditions; face, sound direction, audiovisual fusion, embodied trust enforcement | **Deferred**; separate owner approval |

Trust separation (binding):

- An authenticated client uses the existing T3 authenticated-channel category ([ADR 0024](adr/0024-owner-recognition-trust.md)). 32A separately produces `SpeakerEvidence` for a *current live utterance* under the Phase 25 contract: score, quality, freshness, session binding and spoof/replay uncertainty.
- A voice match is identity evidence. It never authorizes an action, raises T3 or substitutes for login.
- A meeting speaker-name suggestion is a different, non-authorizing output derived from recorded diarized speech. It needs owner review before it becomes an attributed identity.
- Android platform biometrics may unlock the UI. They are not Reachy speaker verification.

## 2. Foundations and boundaries

- The Android client is native Kotlin/Jetpack Compose ([ADR 0029](adr/0029-android-companion-app.md)), a thin client of the hub owner API (session cookie plus `X-Reachy-CSRF`). Voice/chat, meeting recording, notes, documents, reminders, alarms and calendar/Home already exist; do not rebuild them.
- Phase 25 separates identity evidence, effective trust and action authorization. Keep T0 to T3 semantics and the [ADR 0011](adr/0011-destructive-action-consent.md) text-only consequential/destructive confirmation. No LLM or recognition model makes an authorization decision. Reuse the `SpeakerVerifier` contract and server-side evidence/trust logic; do not create a second authority path on Android.
- Matching is implemented once, centrally, not separately in Android, web, meeting worker and robot.

### Shared architecture

- **Voice-profile registry:** the owner profile first; optionally explicitly consented named contacts later. Each profile is scoped by owner/account and carries provenance, model version, encryption key and retention policy. Meeting recordings are never a silent bystander enrollment database.
- **Verification** `verify(owner, live_utterance)`: a 1:1 question. Returns short-lived `SpeakerEvidence` to the caller's session, with explicit uncertain/failure states.
- **Meeting identification** `suggest_profiles(diarized_speaker_samples)`: 1:N similarity against consented known profiles only, with a reject/unknown option. Returns candidate labels and evidence for review, never a trust level. `SPEAKER_00` ids stay scoped to one recording.
- **Clients:** Android first. Other authenticated voice clients use the same API after their own audio-path and privacy testing. Robot microphone admission stays disabled until 32B even if the service runs.
- **Identity and audit:** manually confirmed names stay separate from automatic guesses, with provenance, reversible corrections, model/template version and links to the original evidence. No global identity learning from a correction.

Android `SpeechRecognizer.createSpeechRecognizer()` does not select or prove an on-device recognizer; measure its privacy properties before advertising phone dictation as on-premises. Meeting audio captured by the foreground service and uploaded for on-premises processing is a separate path and must not be conflated with one-shot dictation.

### In scope for 32A

1. Consenting owner enrollment from the Android microphone into a shared server-side registry, with replacement, deletion and recovery. Templates are encrypted; biometric material stays out of logs and cloud services; any backup is separately consented, encrypted, deletable and documented.
2. Benchmark and deploy an on-premises verifier on real phone audio (non-owner, noise, replay, synthetic speech, overlap); calibrate the threshold and explicit unknown/uncertain outcomes.
3. Bind each live result to its utterance, authenticated session and a short expiry. Show "Owner voice verified", "Uncertain" and "Not verified" without raw scores as certainty claims.
4. Audit and harden Android session persistence, expiry, reauthentication and revocation. Optional platform biometric/PIN unlock is a separate control.
5. Apply the same Core resource/action policy to typed and spoken requests, including voice-to-meeting transitions and any future Gmail send. A recognized voice alone cannot approve consequential actions.
6. Match diarized meeting clusters to consented profiles and offer evidence-linked, reviewable suggestions in the existing web/Android Identify Speakers UI, with Unknown/Skip kept. Never silently overwrite manual assignments or historical summaries.
7. Audit speech-audio locality, preserve recoverable meeting recording, and test on the owner's physical phone, including Tailscale loss, microphone interruptions and hub downtime.

### Out of scope for 32A

- Robot speaker calibration, visual liveness, face detection, sound direction, robot motion and robot microphone arrays. (Phone enrollment, FAR/FRR and replay testing are in scope.)
- Bystander recognition, shared-room identity databases, ambient wake listening, unattended robot audio memory capture.
- A second biometric-session manager, a new Core authorization system, a remote identity provider, or replacing the Android UI architecture. A lightweight isolated shared inference adapter is permitted if the Hub verifier protocol cannot safely host the chosen model.
- Same-device phone-call/Teams/Zoom capture (existing meeting-recording constraints apply).
- Production activation of `VOICE_SENSITIVITY_GATE_ENABLED` for robot voice.

## 3. Implementation plan: 32A

### 32A.0: Security and compatibility inventory (no deployment)

- Trace Android login/logout, cookie storage and scope, CSRF, hub authorization, session expiry, password change, multi-device sessions, HTTP/Tailscale/TLS paths.
- Establish what the server can actually revoke. Do not promise remote device revocation unless the mechanism exists and is tested.
- Inspect Auto Backup exclusions and persistent app caches (recording retries, playback, previews, notifications).
- Map `input_modality=voice` versus `text` across every action/confirmation handler. Any bypass is a blocking security defect.
- Document the STT/TTS providers used on the physical phone, what is local and what crosses the network.
- Trace the `SpeakerVerifier` protocol, `VoiceTrustContext`, enrollment benchmark APIs and encrypted-storage requirements. Identify a phone-audio transport that supplies audio bytes, not text; Android STT transcripts do not preserve identity evidence.

**Gate G0:** written inventory with code locations, threat model, compatibility baseline and owner approval for any API/schema change. No change to running services.

### 32A.V: Shared enrollment and live verification (required)

- Owner-consented enrollment in the Android client on the existing owner-recognition data and encrypted-template architecture where possible: several varied short phrases, sample-quality assessment, review, delete/re-enroll, fresh owner reauthentication for replacement.
- A proven on-premises embedding/verifier model within the homelab GPU/CPU budget, with one versioned profile/embedding pipeline for live verification and post-meeting matching. Inference on private infrastructure. No persistent raw speech unless explicitly consented for a bounded benchmark; embeddings encrypted and excluded from chat memory, RAG, LLM prompts and telemetry.
- Live PCM/audio for the current voice turn over authenticated private transport, verified concurrently with the existing transcription pipeline where feasible. Reusable by other authenticated clients after their acceptance. No extra continuous listening or background microphone activation.
- `SpeakerEvidence` with owner/session/utterance binding, expiry and quality/spoof fields. Speaker identity is distinct from session authentication; a raw score is never an authorization token.
- Report a confusion matrix, false-accept/false-reject counts and rates, latency distributions, speaker counts, conditions, confidence intervals where meaningful, and the limits of the small private set. Non-owner voices only with consent; never enroll unknown bystanders.
- Probe replay through another speaker, audio injection, synthetic/converted owner-like speech, background owner speech, shared microphone, noisy and quiet scenes. Fail to unknown/uncertain on poor quality, model outage, stale audio or suspicious presentation; claim no spoof immunity without evidence.
- The UI shows the last current-session state with a clear expiry and no persistent "recognized" badge. A non-match must not sign out an authenticated owner; a separately reviewed response/privacy policy applies.

**Gate GV:** owner-approved benchmark and threshold; owner match and non-owner rejection on held-out physical-phone trials; documented latency and spoof limits; delete/re-enroll proof; no cloud biometric transfer; independent trust/authorization tests. The verifier stays disabled by default until the owner approves activation.

### 32A.M: Meeting speaker identification assistance (required)

- Consume the canonical diarized segments and stable recording-local clusters ([Phase 31](phase-31.md), [Phase 54](phase-54.md)); no new diarization pipeline. Pick clean multi-second windows; exclude overlap and silence.
- Compare each cluster to consented profiles through the shared model version. Calibrate open-set rejection independently of the live threshold. Report top candidates, an unknown state and source timestamps; never present a cosine score as a calibrated probability.
- Add suggestions to the existing Identify Speakers UI on web and Android: accept, rename, reject, Unknown or Skip. Confirmed names win; suggestions never auto-rename transcript, analysis, summary or action attribution.
- Store owner confirmation and provenance apart from generated suggestions; recompute derived outputs through the existing stale-output mechanism; keep original diarization labels and immutable evidence.
- Offer an explicit consent-and-enroll action for a participant who wants a reusable profile. A typed speaker name is not consent and creates no template; unknown bystanders stay meeting-local.
- Bound cost and retention. No meeting audio, embeddings or identities to cloud providers or LLM prompts. Enforce the meeting's authorization, privacy scope and deletion behaviour.
- Test single and multiple known/unknown speakers, repeat meetings, different microphones, noise, overlap, model change, conflicting names and corrections. Quantify false matches and unknown rejection; owner review is the backstop, not proof of accuracy.

**Gate GM:** on physical-phone multi-speaker meetings, known owner segments produce reviewable candidates with linked audio evidence; unknown attendees stay unknown; confirmations propagate through the existing invalidation workflow; wrong suggestions can be rejected without polluting profiles. Robot path untouched.

### 32A.1: Session and secret protection

- Move persisted session credentials from ordinary SharedPreferences to a supported Android Keystore-backed design with authenticated encryption and an app-controlled key lifecycle.
- No credentials, cookie values, private request/response bodies or biometric material in logs; no secrets in backups.
- One hub origin binding with consistent cookie domain/path; reject silent host changes and unsafe redirects. Transport stays HTTP over the tailnet per the amended G0 decision 2: no TLS, certificate or proxy work here; document the cleartext exposure instead (HTTPS is the separate future task above).
- Define expiry/401, logout, local credential deletion and password-change behaviour. Per-device server-side sessions with the 12-hour idle expiry are approved (G0 decision 1; design in ADR 0041 decision 9) but change production sessions, so they ship only behind a separate approval gate.
- Notes, tasks and transcripts stay server-side; bound retention and deletion of temporary meeting/audio files and caches.

**Gate G1:** tests for cookie migration, expiry, logout, restart, origin change, offline, backup exclusion and no secret-bearing logs; existing authenticated flows still work.

### 32A.2: Optional Android local unlock

- Platform `BiometricPrompt` with device-credential fallback; no Reachy face/voice template is created or uploaded.
- Local unlock is a UI disclosure control only. On unlock, revalidate the hub session and permissions. It never sets a T3 assertion or authorizes anything offline.
- Conservative inactivity default, owner opt-in/out and timeout. Never obstruct a running foreground meeting recording, emergency Stop or pending upload recovery. Hide previews while locked; no confidential text on the lock screen or in the recents snapshot.
- Handle unsupported hardware, multiple device users, credential and biometric enrollment changes, process death and cancellation without security downgrade.

**Gate G2:** physical biometric and device-credential paths pass; no biometrics sent to the hub; no private content before local unlock and server-session validation; recording survives locking.

### 32A.3: Voice/text authorization parity

- Android speech requests stay `voice` modality and typed requests `text`; the authenticated origin never converts spoken consent into typed confirmation.
- Consequential actions use an authenticated explicit text/tap confirmation backed by server policy (details, expiry, idempotency, cancellation), keeping any stricter ADR 0011 constraint. A generic tap or biometric unlock is not enough unless policy explicitly allows it.
- Show that read permissions, privacy labels and private-channel response behaviour match across Android text, Android voice and authenticated web.
- Never send a sensitive spoken reply to an external/untrusted audio route without explicit policy; test Bluetooth and speakerphone.
- A voice badge or `SpeakerEvidence` never raises authority above the authenticated phone channel, and a poor match never erases valid login. Define separately what a mismatch changes (warn, suppress spoken private playback, require fresh device confirmation) versus what signed-in typed operations may do.

**Gate G3:** matrix tests show no escalation via voice, prompt injection, forged modality or stale session; consequential/destructive operations still need Core confirmation; failures are closed.

### 32A.4: Speech privacy disclosure and control

- Determine whether one-shot `SpeechRecognizer` is offline or remote on the owner's device: OS version, recognition service, mode, observable network behaviour, without storing private speech.
- Offer an explicit on-device-only mode, or the existing on-prem speech service with authenticated, consented audio transfer. If locality cannot be guaranteed, say so in the UI.
- Separate phone OS/vendor STT from Reachy's local meeting STT/diarization/analysis. A missing language pack is visible and never triggers a covert cloud fallback.
- Record the phone TTS privacy path; no unannounced sensitive-text transfer through a cloud-capable fallback.

**Gate G4:** verified privacy path and truthful UI copy; with on-device-only selected, no recognizer audio leaves the phone except consented transfers to the private Reachy endpoint.

### 32A.5: Regression and staged Android deployment

- Run app unit tests, build a versioned debug APK, test against a local/disposable hub where possible.
- Verify meeting start/stop handoff from voice chat, foreground microphone permission, long recording, interrupted upload and recovery; keep the speaker-label workflow separate from owner biometrics.
- Test hub reboot, network loss, Tailscale reconnect, session expiry during upload, lock/unlock, process death, fold/unfold if a Fold, on the physical device.
- Test live owner/non-owner, ambiguous, replay and synthetic speech, microphone handoff into recording, and verification failure without losing the capture.
- Test meeting suggestions and corrections end to end on web and Android, with explicit consent for any enrolled non-owner and no unattended auto-labelling.
- No robot/Nano deployment, camera permission, motion change or voice trust gate enablement.
- Deliver a change list, test evidence, known limitations, a rollback APK and reproducible install notes.

**Gate G5 (release):** the owner reviews the evidence, performs physical-phone UAT and explicitly approves installation and enablement. No automatic merge, production deployment or activation.

## 4. Acceptance matrix

Each result records device and OS, app and backend commit, scenario, expected/actual result, evidence location and any owner waiver. Emulator runs are not physical-device acceptance.

| ID | Scenario | Required result |
|---|---|---|
| A01 | Fresh login, restart, cookie migration | Existing account works; no plaintext persisted secret in current app data |
| A02 | Expired/revoked session; hub 401 | Private data withheld; clear reauthentication; no unauthorized retry |
| A03 | Logout and app reinstall/restore | No reusable credential or sensitive backup restored |
| A04 | Optional local unlock success/cancel/failure | Protected UI hidden until allowed; server authority unchanged |
| A05 | Phone lock during meeting | Foreground recording continues; Stop accessible; output recoverable |
| A06 | Voice asks to send email/delete record | No voice-only final authorization; existing confirmation policy enforced |
| A07 | Forged text/voice modality or stale confirmation | Rejected, fail-closed by the server |
| A08 | Hub or Tailscale disappears mid-operation | No leak or duplicate action; recoverable state displayed |
| A09 | Phone dictation and phone TTS | Documented real processing path; locality claims match evidence |
| A10 | Typed/voice read of private calendar/notes | Same owner and privacy ceiling applied |
| A11 | Phone/fold, app background, process death | No private preview exposure; key flows survive or recover safely |
| A12 | Robot stack unchanged | No new robot recognition, wake, motion or memory eligibility |
| A13 | Enroll owner voice, later delete/re-enroll | Owner-controlled encrypted template lifecycle; old evidence invalidated |
| A14 | Owner, consented non-owner and ambiguous voices | Calibrated accepted/rejected/uncertain outcomes with per-condition evidence |
| A15 | Replay/synthetic/overlap/noisy phone speech | Limits measured; suspicious or low-quality input never silently verified |
| A16 | Same utterance versus stale/reused verifier result | Session/turn binding enforced; no evidence replay into later turns |
| A17 | Verified voice requests a sensitive action | Identity does not bypass authenticated confirmation or Core policy |
| A18 | New meeting, enrolled owner and unknown attendees | Owner is a reviewable candidate; unknowns not auto-enrolled or auto-named |
| A19 | Suggestion accepted, rejected or corrected | Provenance kept; transcript and dependent outputs updated/reviewed by existing mechanisms |
| A20 | Same person across phone and another enrolled client | Shared model/profile works with documented device-specific accuracy; no robot activation |
| A21 | Delete voice profile or meeting | Stored biometric profile/matches removed or invalidated per retention policy; no residual automatic identity claim |
| A22 | Biometric endpoints and the speaker service exposure | Voice-identity routes accept the owner cookie only (no bearer), are 404 when disabled, and the speaker service publishes no host port; the Caddy warning against Internet exposure stands |
| A23 | HTTP transport limits | Documented in ADR 0041 and the deployment guide; no TLS, certificate, proxy or cookie-secure change made by 32A; HTTPS recorded as a future task |
| A24 | One capture, two consumers | A single uploaded WAV is what STT transcribes and the verifier embeds; no second microphone path; the conversation still works when verification is unavailable |

## 5. Deferred: Phase 32B, physical robot recognition

Resume only on separate owner approval, when the physical voice/motion deployment and [Phase 30](phase-30.md) stabilization suit real trials. Reuse the 32A profile and validated model where transfer tests allow, plus [Phase 25](phase-25.md) and [ADR 0024](adr/0024-owner-recognition-trust.md):

1. A separate consenting dataset across robot microphone distances, orientations and noise; the phone-calibrated threshold is not assumed to transfer.
2. Robot-specific FAR/FRR, calibration, spoof/replay and latency acceptance with compatible encrypted owner templates.
3. Second-stage request-sensitivity classification with explicit uncertain/unknown outcomes.
4. Direction of arrival, face/liveness evidence and current-utterance audiovisual association.
5. T0 to T1 to T2 fusion, expiry/downgrade, output revocation, safe fault behaviour.
6. Adversarial shared-room acceptance and a separate robot deployment/rollback gate.

Until 32B is accepted: `NoSpeakerVerifier` stays the robot voice default even when the phone verifier is active; the robot sensitivity gate stays off; `ROBOT_VOICE_ELIGIBLE = False` ([Phase 48](phase-48.md)) is preserved; access to sensitive ambient requests is not broadened.

## 6. Non-goals and constraints

- No cloud LLM or external speech provider is implicitly authorized. Any exception is an explicit, accurately disclosed owner choice.
- On-prem server processing says nothing about the locality of Android's OS speech recognizer.
- Being on Tailscale is not authentication; transport security is not identity.
- No generalized biometric directory. Reachy remains single-owner.
- Hub/Core separation and existing consent, audit and rollback practice are preserved.

## 7. Definition of done

32A is done when G0, GV, GM and G1 to G5 are evidenced and approved; Reachy recognizes the enrolled owner from live Android utterances and proposes known speaker identities in meetings from the same on-prem profile service, both with explicit uncertainty handling; owner/non-owner and adversarial results are documented; the experience works on the physical phone; suggestions are owner-reviewed and consent-bounded; voice and text obey the same Core constraints; speech locality is described accurately; and no robot deployment has occurred. 32B remains deferred.

## 8. References

[plan.md](plan.md#6-implementation-roadmap) Phase 32 row; [phase-25](phase-25.md); [ADR 0024](adr/0024-owner-recognition-trust.md); [ADR 0011](adr/0011-destructive-action-consent.md); [ADR 0029](adr/0029-android-companion-app.md); [phase-40](phase-40.md); [phase-48](phase-48.md); [project-state](project-state.md); code: `clients/android/app/src/main/java/app/reachy/companion/data/Prefs.kt` (cookie persistence), `data/ReachyApi.kt` (owner API), `Voice.kt` (recognition provider).
