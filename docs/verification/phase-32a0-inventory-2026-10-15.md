# Phase 32A.0: security and compatibility inventory (2026-10-15)

Gate G0 evidence for [Phase 32](../phase-32.md). **Read-only code inspection at `main` `4acc4f9` plus the uncommitted working tree; no service, device, APK or schema was touched, and nothing was run against the phone or the homelab.** Statements about the physical phone's behaviour are marked *unverified*: they need the 32A.4 device measurements. The owner answered section 9 on 2026-10-15 (resolutions recorded there); this record itself approves nothing further.

## 1. Compatibility baseline

- Hub subset run: `uv run --group dev pytest services/reachy-hub/tests shared -m "not slow" -k "trust or speaker or owner_recognition or enrollment or session or auth or csrf"` gave **147 passed, 456 deselected**. Android unit tests were not run in this step.
- Android is 0.19.0; schema head `037_processing_provenance`; robot voice default `NoSpeakerVerifier`.

## 2. Android session (A01 to A03, A08, A11)

| Fact | Where |
|---|---|
| The session cookie is stored as a plain string in ordinary `SharedPreferences` ("reachy", `MODE_PRIVATE`) next to the hub URL and username. No Keystore, no encryption. | `data/Prefs.kt:7-15` |
| `PersistentCookieJar` writes `Cookie.toString()` lines and re-parses them with the *current request's* URL. OkHttp omits the domain for host-only cookies, so the stored cookie carries no origin; it is bound to whichever `baseUrl` is current at load. Safe today only because `signIn` clears the jar before changing the origin. | `data/ReachyApi.kt:38-54`, `AppViewModel.kt:339-344` |
| `ReachyApi` uses OkHttp defaults: redirects are followed (including `https`↔`http`), and `X-Reachy-CSRF: 1` is added to every request. Cookie matching is by OkHttp host/path rules. | `data/ReachyApi.kt:67-73` |
| Cleartext HTTP is allowed app-wide (`base-config cleartextTrafficPermitted="true"`); the owner accepted this on 2026-10-07 on the premise of Tailscale ([ADR 0029](../adr/0029-android-companion-app.md) item 5). `normalizeBaseUrl` defaults a bare host to `http://`. | `res/xml/network_security_config.xml`, `ReachyApi.kt:57` |
| `android:allowBackup="false"`, so Auto Backup and device-to-device transfer are off (A03 reinstall/restore: nothing is restored by the OS). No `dataExtractionRules`/`fullBackupContent` files exist; with `allowBackup=false` they are not needed. *Unverified on the device.* | `AndroidManifest.xml` |
| Sign-out clears the jar, caches (`CalendarCache`, `HomeCache`), reminders, chat state; it also calls `POST /auth/logout`. | `AppViewModel.kt:358-362` |
| On any 401 the app sets `Session.SignedOut` and shows "Please sign in again". Background paths (`uploadPending`, `DeepReview`) build their own `ReachyApi` from the same cookie string; an expired cookie leaves clips in `pending-meetings` and reports the error. | `AppViewModel.kt:365-367`, `RecordingService.kt:270-290`, `DeepReview.kt:45` |
| Data at rest in app storage outside prefs: `filesDir/held-meetings`, `pending-meetings` (unsent clips and plan files), `calendar-schedule.json`, `home-snapshot.json`, `meeting-reminders.json`; `cacheDir/recording-*.m4a`, `meeting-audio` (player cache), `email-preview/preview.pdf`. None is encrypted. Calendar/Home snapshots hold private titles. | `CalendarCache.kt:16`, `HomeCache.kt:16`, `RecordingService.kt:68,104`, `Voice.kt:216`, `AppViewModel.kt:71,858` |
| No `Log.*` call writes a cookie, body or biometric. Remaining logs are alarm/reminder warnings. No `FLAG_SECURE`, no `BiometricPrompt` anywhere. | grep over `app/src/main` |
| Notifications: only meeting reminders use `VISIBILITY_PRIVATE` with a public version; the recording notifications, deep-review and alarm notifications set no visibility. Recording notification text is generic ("Reachy"). | `MeetingReminders.kt:214-219`, `RecordingService.kt:212-244`, `DeepReview.kt:100,114`, `PhoneAlarm.kt:208` |

## 3. Hub session and revocation (A02, A03)

- Login sets `request.session["user"] = username` (Starlette `SessionMiddleware`, cookie `reachy_session`, `max_age=43200`, `same_site="strict"`, `https_only` only if `SESSION_COOKIE_SECURE=true`, default **false**). `app.py:951-955`, `operator.py:214-224`.
- **The session is a signed, stateless cookie.** Starlette refreshes it on each response, so the 12 hours slide with use. Logout calls `session.clear()` on *that* request only. **There is no server-side session table, no per-device record, no password-change invalidation and no "log out other devices".** A copied cookie stays valid until it goes unused for 12 hours or `SESSION_SECRET_KEY` is rotated (which signs out every client, including the web UI).
- Consequence for 32A.1: per-device remote revocation **does not exist**. The smallest approved change would be a server-side session id/version checked by `require_remote_auth`/`require_owner_session` (hub schema or store change). Not proposed for implementation until the owner decides (section 9).
- Authorization: `/messages`, `/voice/turn`, `/webrtc/offer`, `/sessions|audit|notifications|briefing|calendar` go through the `private_work_routes` middleware when `ACCOUNTS_SERVICE_TOKEN` is set (production): owner cookie *or* `REMOTE_UI_TOKEN` bearer, and `user_id` must equal `OWNER_USER_ID`. State-changing cookie requests need `X-Reachy-CSRF: 1`, which is a same-origin marker, not a secret. `require_owner_session` (owner-recognition routes) accepts the cookie only, no bearer. `app.py:495-512,905-935`.

## 4. Voice and text modality (A06, A07, A10, A17)

- `input_modality` is a field of the request body (`InboundMessage`, default `text`), **asserted by the client**. The hub passes it to core unchanged. Android sets `voice` for recognised speech and `text` for typing (`ReachyApi.kt:136`); typed turns also join a chat record, spoken turns do not. A chat-record turn is rejected unless `text`/`web` (`app.py:1634`).
- Effects of `voice`: core caps document/personal access (`access_from_ceiling(..., voice=True)`, `app.py:1482`); the hub sets `access_ceiling="sensitive"` only for authenticated `web` + `text` (`app.py:1506`); structured commands parse only for `text` (`app.py:1519`).
- ADR 0011 confirmation: `require_text` is enforced in core at `memory.forget` confirmation (`app.py:1869` via `confirm_action`), email approve (`1953`) and send (`1980`), the HTTP routes for those (`2491`, `2620`, `2632`) and the four meeting-distribution actions (`meeting_distribution/service.py:262,283,323,338`). Email cancel-send is deliberately allowed from voice. No bypass found by reading these paths.
- **Limit that matters for A07/A17:** because the modality is client-asserted, the server cannot tell that a turn *was* spoken. The voice cap protects against an honest client's speech, not against an authenticated client that labels spoken text as `text`. The authenticated owner session is the real boundary; `SpeakerEvidence` cannot change that and must not be described as if it did. A forged-modality test (A07) should therefore assert "no authority beyond the owner session", not "server detects speech".
- The `/voice/turn` route (hub-side STT on an uploaded WAV, `Channel.REACHY`, `VOICE`) is documented in code as a caller-upload diagnostic; it returns only a transcript and reply, never evidence.

## 5. Speaker verification foundation (GV)

- `SpeakerVerifier.verify(wav_bytes, *, owner_id, robot_id, voice_session_id, turn)` (`speaker/base.py`) is robot-shaped. `SpeakerEvidence` (`shared/models/trust.py`) requires `robot_id`, `voice_session_id`, `turn` and **monotonic** capture/expiry times, which are meaningful only inside one hub process. The only caller is `robot_voice.run_turn`, which stores evidence in `VoiceSession.trust` and runs `verify` concurrently with STT on the same WAV. `NoSpeakerVerifier` is the only implementation; **no model is wired**.
- Android sends the hub text (`/messages`), never audio. `SpeechRecognizer` yields no audio bytes to the app, so **a verifier needs a separate audio capture**. Candidates for 32A.V: (a) record PCM in-app with `AudioRecord` for the same turn, which risks microphone contention with the OS recognizer (*unverified; needs a device test*); (b) send that same audio to the hub's own STT instead of using `SpeechRecognizer`, which also settles locality (A09) and gives the verifier its bytes. Either needs a new or extended authenticated hub route; that is an API change needing owner approval.
- Phone-session evidence does not fit the current model without a decision: `robot_id` has no phone equivalent, and `effective_trust` (`reachy_hub/trust.py`) is defined for the robot voice session. Options for the owner: a `client_id` field on a phone-specific evidence type, or a documented reserved id. No change proposed yet.
- Owner-recognition data today: `enrollment_store.py` is the **benchmark** store only (raw webm/ogg/wav up to 10 MB, behind `OWNER_RECOGNITION_*` routes with a fresh-reauth check for mutating calls). Its docstring and [Phase 25](../phase-25.md) state it is deliberately not an operational template store; `recognition_store.py` ("encrypted template storage") is described in Phase 25 but **does not exist**. The Android app has no enrollment UI; enrollment is web-only. `hub/keyring.py` exists for encryption keys and is the likely basis for template encryption (to confirm in design).
- [ADR 0038](../adr/0038-meeting-speaker-identification.md) point 2 says "no embedding is computed" for Identify Speakers. 32A.M contradicts that clause for consented profiles, so it needs a new ADR (or an explicit amendment) before any embedding is computed. Samples there are unsaved time ranges of the existing recording, which suits "linked audio evidence".

## 6. Phone speech and privacy (A09, GV, G4)

- `Voice.kt` uses `SpeechRecognizer.createSpeechRecognizer(context)` with `LANGUAGE_MODEL_FREE_FORM` and partial results. It sets neither `EXTRA_PREFER_OFFLINE`, `EXTRA_LANGUAGE` nor `createOnDeviceSpeechRecognizer`; the manifest `<queries>` entry only lets it find a service. The recognition service is whatever the phone's default is (often a Google service that may use the network). **Locality is therefore unknown and the UI must not claim it.** *Unverified: needs the device, OS version and observed traffic.*
- Phone TTS is `android.speech.tts.TextToSpeech(context)` with the default engine; the engine and any network use are *unverified*. By default replies play in Reachy's streamed hub voice; the "phone voice" preference switches to the phone engine (`Prefs.phoneVoice`).
- Meeting recording uses `MediaRecorder` AAC/m4a at 16 kHz, saved in app storage and uploaded to the hub for Reachy's own STT and diarization. Separate path from dictation.

## 7. Threat model (short)

| Threat | Current state | 32A response |
|---|---|---|
| Rooted/other-app access to app data or a copied backup | Cookie and cached private titles in clear; backup off | G1 Keystore storage; cache review |
| Stolen cookie | Valid up to 12 h idle; no revoke | Owner decision on server-side session version |
| Plaintext transport on non-tailnet LAN | Allowed app-wide | Owner decision: warn/block non-private cleartext (G1) |
| Redirect or origin confusion leaking the cookie | Mitigated only by clearing on sign-in; redirects followed | Pin origin, refuse cross-origin redirects |
| Spoken request forges a text modality | Client-asserted; boundary is the owner session | Test as "no extra authority"; never present evidence as a gate |
| Replay/synthetic owner voice | No verifier | GV measurements; fail to uncertain |
| Biometric template or raw audio leakage | Raw benchmark store only; no template store | Encrypted store, no logs/prompts/RAG, deletion proof |
| Silent bystander enrollment from meetings | Not possible today (no embeddings) | Explicit consent action only; typed name creates no template |
| Voice mismatch signing out the owner | Not applicable yet | Mismatch must warn or suppress private playback, never end the session |

## 8. Blocking defects

None found in the modality paths read above. Defects and gaps recorded for later gates, not fixed here: no per-device revocation; plaintext session and private caches at rest; recording/deep-review notifications lack a private variant; no `FLAG_SECURE` or recents protection; cleartext allowed globally.

## 9. Owner decisions at G0 (answered 2026-10-15)

| # | Question | Resolution |
|---|---|---|
| 1 | Revocation | Approved: server-side per-device revocable sessions, 12-hour idle expiry kept. Production change, separate gate; 32A.1 ([ADR 0041](../adr/0041-shared-voice-identity.md) decision 9) |
| 2 | Cleartext policy | **Amended**: first "require HTTPS", then HTTPS deferred. HTTP over authenticated Tailscale stays; no TLS, certificates, proxy or HTTPS migration in 32A; biometric endpoints not publicly exposed; limits documented; HTTPS a separate future task |
| 3 | Audio transport | One capture pipeline feeding the hub's STT and the verifier (`POST /voice-identity/turn`); meeting audio reused |
| 4 | Evidence shape | Transport-neutral `VoiceEvidence` with a projection to the robot's `SpeakerEvidence` |
| 5 | Template store and key | Encrypted `voice_profiles` table (migration 038), keys in the existing keyring file outside the database |
| 6 | ADR work | ADR 0041 written; ADR 0038 amended |
| 7 | Verifier host | Central, existing home server, CPU-first, SpeechBrain ECAPA-TDNN in a stateless sidecar; measure before GPU |

### Threat model, transport amendment

With HTTP retained (decision 2) the rows "Plaintext transport on non-tailnet LAN" and "Stolen cookie" above stay open in 32A rather than being closed by TLS. What 32A adds on top: voice audio and voice results also cross the phone-to-hub hop in clear off the tailnet; the hub-to-speaker and hub-to-core hops are plain HTTP on the Compose network; Caddy's single port proxies every `/hub/*` route, so the voice routes are reachable wherever the hub is. The compensating controls are owner-cookie-only access (no bearer), CSRF, reauthentication for profile changes, routes that 404 when the feature is off, a speaker service with no published port, and ciphertext-only profiles. The full table is in [ADR 0041](../adr/0041-shared-voice-identity.md#threat-model-transport-focused).

Phase 32B is untouched, and no robot, daemon or device action was taken.
