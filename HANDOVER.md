# Handover

Current session snapshot: 2026-09-27. Read [AGENTS.md](AGENTS.md) first.
The [documentation index](docs/README.md) defines ownership;
[project state](docs/project-state.md) collects deployment limits and open
acceptance. This file holds only session continuation details.

## Current work

**Phase 25a.4 (input-sensitivity gate) landed, 2026-09-28 — off by
default, not deployed with anything different.** `RequestSensitivity`/
`RequestAuthorizer` existed since 25.0 but were never called; this adds
`classify_sensitivity()` in `request_sensitivity.py` (deterministic
regex rules only — recognizes a handful of obvious PUBLIC/PERSONAL/
CONSEQUENTIAL phrasings, everything else is `UNKNOWN`, which fails
upward exactly like a sensitive request would, since there's no
LLM-assist layer yet) and wires it into `robot_voice.py`'s `_answer`:
before a transcript reaches Core, classify it, compute `effective_trust`
from the session's `VoiceTrustContext` (25a.3's evidence), and
`authorize_request`; anything short of `ALLOW` withholds the turn
(`VoiceTurnOutcome.WITHHELD`, reused rather than adding a new outcome)
instead of calling Core. Gated behind `VOICE_SENSITIVITY_GATE_ENABLED`
(new env var, default `false`, added to `.env.example`/compose but
**deliberately left off** there too) — with no real speaker model (still
`NoSpeakerVerifier`) and no visual verifier at all, trust can never
exceed T1, so turning this on today would block most everyday questions,
not just sensitive ones. This needs an explicit owner decision later,
not a silent default flip. 11 new tests (`test_request_sensitivity.py`'s
classifier cases, `test_sensitivity_gate.py`'s wiring cases); full
`pytest services shared` (925 passed) and Ruff pass. No redeploy done —
no functional change while the flag stays off, and the compose/env
additions are just plumbing for whenever the owner does want to try it.

**Phase 25a.3 (speaker-verification wiring) landed, 2026-09-28 — no
real model yet.** New `reachy_hub/speaker/base.py`: the `SpeakerVerifier`
protocol (`async verify(wav_bytes, *, owner_id, robot_id,
voice_session_id, turn) -> SpeakerEvidence | None`, must never raise) and
`NoSpeakerVerifier`, the default until a real adapter exists.
`robot_voice.py`: `VoiceSession` now carries a `VoiceTrustContext`
(`trust.speaker`, `trust.visual`, both `None` today); `VoiceTurnPipeline`
gained a `verify_speaker` field (defaults to `NoSpeakerVerifier`, so every
existing call site and test kept working unchanged); `run_turn` runs
`pipeline.verify_speaker` concurrently with `pipeline.transcribe` via
`asyncio.gather` on the same WAV — including the Phase 24g pretranscribed
wake-admission path, where STT already ran during admission but the audio
still gets verified here for the first time. A verifier exception is
caught locally and degrades to `trust.speaker = None`; it never fails the
turn, matching the documented "speaker-verifier outage caps trust at T0"
behavior. **Nothing computes or uses `TrustLevel` from this evidence
yet** — that's 25a.4 (gating the input-sensitivity boundary), deliberately
not done this pass. 6 new tests
(`services/reachy-hub/tests/test_speaker_verification.py`); full
`pytest services shared` (902 passed) and Ruff pass; no docker
build/redeploy needed (no new runtime dependency, no config change).

**Enrollment portal hardened to the Phase 26d policy, 2026-09-28.**
Implemented the policy decided just below: added
`reachy_hub/keyring.py` (AESGCM, duplicates `companion_core.secrets.
Keyring`'s shape per ADR 0001 — no sibling-service import); rewrote
`FilesystemEnrollmentStore` to encrypt every capture at rest (AAD binds
ciphertext to kind/sample_id/content_type) and added an
`is_benchmark_enabled`/`set_benchmark_enabled` gate that `add_sample`
now enforces (403 if off); routes moved under
`/owner-recognition/benchmark/...` to leave room for a future,
separate `/owner-recognition/enrollment/...` operational namespace;
added `PUT .../benchmark/enabled` and
`GET .../benchmark/{voice,face}/export` (zip download, fresh-reauth
gated); `EnrollmentStatus` now reports `benchmark_enabled` and each
kind's total byte count. `services/reachy-hub/pyproject.toml` gained a
direct `cryptography` dependency (was only companion-core's before;
each service builds its own image from its own pyproject, so this was
required, not redundant) — `uv lock` updated. The homelab compose file
now mounts the existing `credential_keys` secret into `reachy-hub` too
(`SECRET_KEY_FILE=/run/secrets/credential_keys`, same key file
core/migrate already use). Portal UI relabelled "Benchmark dataset"
throughout, with an explicit enable checkbox gating the record/capture
buttons, dataset size display, and export buttons
(`clients/operator-ui/owner-recognition.js`, new `apiDownload` helper
in `app.js`). 41 backend tests across `test_enrollment_store.py`
(including an encrypt/decrypt round-trip and a wrong-key-rejection
case) and `test_owner_recognition.py` (including the enable-gate and
export flow); full `pytest services shared` (896 passed) and Ruff pass.
Compose config validated (`docker compose config`) against the real
`.env`.

**Deployed to the homelab, 2026-09-28 06:34 UTC (`19c6545`).** Backup
first (`~/reachy-backups/reachy-before-enrollment-hardening-deploy-20260928T063311.dump`).
`scripts/start-homelab.sh --check` then `--build`; hub/core health ready
in 2s. Confirmed the `credential_keys` secret is mounted at
`/run/secrets/credential_keys` inside `reachy-hub` and
`SECRET_KEY_FILE` points at it. Full curl smoke test against the live
stack: logged in, checked status (`benchmark_enabled: false`), confirmed
an upload attempt 403s before enabling benchmark mode, enabled it,
uploaded a real sample, read the raw on-disk file directly and confirmed
it's genuine AESGCM ciphertext (no plaintext bytes visible), checked
`voice_total_bytes` reported correctly, downloaded the export zip and
confirmed it decrypts back to the exact original bytes plus a correct
manifest, restarted the `reachy-hub` container and confirmed both the
sample and the `benchmark_enabled` flag survived, then deleted the test
sample, turned benchmark mode back off, and logged out — the deployment
is back in its default (off, empty) state. The production capture
volume was empty before this deploy, so there was no old-format
(plaintext) data for the new encrypted format to fail on; not a concern
now but would matter for any *future* format change.

**Still not verified: the actual browser UI.** Same limitation as
before — no Chromium available in any session so far. The curl checks
above prove the backend/encryption/gating contract; they say nothing
about `owner-recognition.js` itself (the new benchmark-enable checkbox,
dataset-size display, export-download button). Open Settings · Accounts
and try it for real next.

**Benchmark-vs-operational biometric-data policy decided, 2026-09-28
(owner).** Resolved the tension the new Phase 26 flagged (below): raw
biometric captures may be retained only for an explicitly enabled
benchmark/calibration purpose (separate encrypted store, owner-visible
size/export/delete, disabling it never touches normal auth); normal
operational enrollment stores only derived templates, deleting raw
captures once a template exists. Recorded as
[Phase 26d's resolved policy](docs/phase-26.md#26d-addendum-benchmark-vs-operational-data-policy-owner-decision-2026-09-28)
(the table, the four 26d requirements, and the separate-stores rule) and
cross-referenced from
[phase-25.md's enrollment-portal section](docs/phase-25.md#enrollment-portal).
**Not implemented yet** — today's `reachy_hub/enrollment_store.py`
(deployed to the homelab this session) is unencrypted and has no
benchmark/operational split; it implements only the benchmark half of
the now-decided policy. Bringing it into line (encryption at rest, a
separate operational template store, the portal's
Operational-enrollment/Benchmark-dataset split) is real Phase 26/Phase
25a.2/25b.3 implementation work, not done in this documentation pass.

**New Phase 26 (Security hardening and assurance) inserted into the
roadmap, 2026-09-28 — documentation only, nothing implemented.** The
owner supplied a phase spec
(`/home/hariz/.claude/uploads/.../phase-26-security-hardening-and-assurance.md`)
to run after Phase 25 and before meeting transcription. Renumbered:
former Phase 26 (meeting transcription/minutes) → **`docs/phase-27.md`**;
former Phase 27 (embodied meeting secretary) → **`docs/phase-28.md`**,
including their internal stage labels (27a/27a.2/27b/27c →
28a/28a.2/28b/28c). New **`docs/phase-26.md`** adapts the owner's spec to
this repo's actual ADRs/files (threat model & attack-surface inventory,
auth/authz audit, network/host/container hardening, secrets/data-at-rest,
SBOM/AIBOM supply-chain, LLM/RAG adversarial testing, DoS/physical-safety
testing, privacy/retention/backup review, security regression suite,
residual-risk report). It explicitly flags one concrete tension for 26d
to resolve: the owner-recognition enrollment portal added this session
(`reachy_hub/enrollment_store.py`) deliberately keeps raw voice/face
captures rather than deriving-then-deleting, which is the opposite of
this new phase's stated audio/camera privacy model — that's a real open
question, not an oversight, and 26d should decide it deliberately.
Updated `docs/README.md`, `docs/plan.md` (roadmap table + the one V0.3
mention) and `docs/phase-24a.md` (two stale "Phase 26" mentions that
meant meeting transcription) for the new numbering. All cross-file
links/anchors verified to resolve. Depends on Phase 25 being implemented
enough to exercise real biometric trust paths before Phase 26's own
acceptance completes (26a–26e generic hardening may start earlier).

**Phase 25.0 (contracts and trust engine) implemented, 2026-09-28, not
deployed.** Landed per [phase-25.md](docs/phase-25.md#implementation-sequence)'s
own sequencing: contracts and the deterministic trust engine before any
biometric model integration, so expiry/downgrade is unit-tested against
fakes first. New: `shared/models/trust.py` (`TrustLevel`, `SpeakerEvidence`,
`VisualEvidence`, `TrustLimits`), `reachy_hub/trust.py` (`effective_trust`),
`reachy_hub/request_sensitivity.py` (`RequestSensitivity`,
`InteractionDecision`, `authorize_request`), and
[ADR 0024](docs/adr/0024-owner-recognition-trust.md) recording the evidence/
trust/authorization split and service-ownership boundary. 50 new unit tests
(`test_trust.py`, `test_request_sensitivity.py`) cover T0–T3 boundaries,
TTL edges, quality/spoof/liveness/frozen-frame/DoA/session/owner mismatches,
and that `Trusted` interaction mode doesn't change authorization. Full
`pytest services/reachy-hub services/companion-core` (716 passed, 29
skipped) and Ruff pass locally. Nothing biometric exists yet: no enrollment
portal, no speaker/face model, no camera/mic integration, no production
gating, nothing deployed or touched on the homelab/Nano.

**Phase 25a.1 (voice model benchmark) started, 2026-09-28 — pipeline smoke
test only, not owner accuracy.** Owner chose this track over the
enrollment-portal skeleton. Set up an isolated benchmark environment
(`benchmarks/phase-25a-speaker/`, own `.venv`, kept out of the uv
workspace per the [dependency-rollout guidance](docs/phase-25.md#recommended-dependency-rollout));
installed `torch`/`torchaudio` (PyTorch CPU index) and `speechbrain`;
loaded `speechbrain/spkrec-ecapa-voxceleb` (HF snapshot `0f99f2d0eb...`,
Apache-2.0). Confirmed the scoring pipeline separates same-speaker
(0.53, accept) from different-speaker (0.017, reject) pairs using that
model card's own two example clips — not the owner's voice, not a
non-owner impostor trial. p50 latency on trimmed 3 s clips was ~0.49 s on
this dev box (20 CPU); real homelab timing is still unmeasured. Full
record, versions and limitations in
[the verification doc](docs/verification/phase-25a1-voice-benchmark-2026-09-28.md).
Noted for later: this torchaudio build's `.load()` needs the optional
`torchcodec` package; the smoke test used `soundfile` directly instead —
resolve one way or the other before writing the production
`reachy_hub/speaker/ecapa.py` adapter.

**Owner-recognition enrollment-portal skeleton added, 2026-09-28** — the
owner asked to set up real audio capture and a web UI for voice/face
enrollment together, so this session built the capture mechanism that
serves both. New Settings · Accounts card "Owner recognition"
(`clients/operator-ui/owner-recognition.js` + `index.html`/`app.js`
wiring) records browser-mic voice clips (`MediaRecorder`) and
browser-camera face photos (`getUserMedia` + canvas snapshot). Backend:
`shared/models/enrollment.py`, `reachy_hub/enrollment_store.py`
(`InMemoryEnrollmentStore` default; `FilesystemEnrollmentStore` opt-in via
`OWNER_RECOGNITION_CAPTURE_DIR`, wired to a persistent volume below) and
`reachy_hub/owner_recognition.py` (new routes under `/owner-recognition/`,
wired into `app.py`). Every route requires an owner cookie session (no
REMOTE_UI_TOKEN bearer path); recording/deleting a sample also requires
same-origin CSRF and a fresh password reauth (`POST
/owner-recognition/reauth`, 5-minute window). **This is explicitly a raw
capture tool, not the real enrollment flow** — see
[phase-25.md's enrollment-portal section](docs/phase-25.md#enrollment-portal)
for the distinction: no speaker/face model is wired in, no template, no
calibration, no accuracy testing, and a captured sample is not identity
evidence (ADR 0024's evidence/trust/authorization split is untouched).
16 new backend tests pass (`test_owner_recognition.py`,
`test_enrollment_store.py`); full `pytest services shared` (883 passed)
and Ruff pass. **Not verified in a real browser** — no Chromium available
in this session (`node --check` syntax-only). A real closure bug in the
voice-recording stop handler (stale `voiceRecorder` read after
`stopVoiceStream()` nulled it) was caught and fixed by re-reading the
code, not by running it — treat this as a stronger reason, not less, to
actually exercise it in a browser before relying on it. Nothing deployed
yet.

**Persistent capture volume wired and deployed, 2026-09-28 (owner
request).** `deploy/homelab/docker-compose.yml` sets
`OWNER_RECOGNITION_CAPTURE_DIR=/data/owner-recognition-captures` on
`reachy-hub` and mounts a new named volume,
`owner-recognition-captures`, at that path, so `FilesystemEnrollmentStore`
is used instead of the in-memory default and samples survive a container
recreate. Documented in `deploy/homelab/.env.example` and
`docs/phase-25.md`'s enrollment-portal section (not encrypted at rest —
restrict host access like any other data/credential volume).

**Deployed to the homelab, 2026-09-28 05:29 UTC.** Backup taken first
(`~/reachy-backups/reachy-before-owner-recognition-deploy-20260928T052840.dump`,
0600) — no schema change in this deploy, so this was routine caution, not
a required migration-safety step. `scripts/start-homelab.sh --check` then
`--build`: image rebuilt, `owner-recognition-captures` volume created,
`reachy-hub`/`companion-core` recreated, hub health ready at 05:29:39Z.
Verified end to end with curl against the live stack: logged in as
`owner`, confirmed password (reauth), uploaded a real voice sample byte
blob, confirmed it landed under `/data/owner-recognition-captures/voice/`
inside the container, `docker restart reachy-homelab-reachy-hub-1`, and
confirmed the sample was still listed in `/owner-recognition/status`
afterward — the volume mount genuinely persists across a container
restart. Deleted that test sample and logged out afterward; both hub and
core health checks pass post-deploy.

**Still not verified: the actual browser UI.** The curl check above
proves the backend/volume contract; it says nothing about
`owner-recognition.js` itself (getUserMedia permission prompts,
MediaRecorder, canvas capture, DOM wiring) — still needs a real browser
session, which this one didn't have. **This is the next thing to do.**

**Next for Phase 25:**
1. **Verify the new portal in a real browser** — open Settings ·
   Accounts, record a voice sample and a face photo, confirm they show up
   and delete cleanly.
2. **Use the portal to collect real, consenting owner and non-owner
   audio** (and, later, face photos) — this is the actual 25a.1 benchmark
   Phase 25a.1's smoke test still needs; nothing further on speaker
   verification can be evaluated meaningfully without it.
3. AASIST anti-spoof benchmarking (not pip-installable, needs its own
   repo/weights) is a separate later pass.

**Settings UI cleanup (2026-09-27):** conversational animations and connected
accounts now occupy separate cards in Settings · Accounts. Local Chromium
checks passed at mobile/desktop widths, as did the three existing Accounts/
animation browser tests and Ruff. Deployed to the homelab at 11:03 WIB;
hub/core health and a live mobile Chromium render passed.

**[Phase 24e](docs/phase-24e.md) closed by owner re-scope (2026-09-27).**
Everything it built is deployed. Most of its rows passed on the robot with
the owner:
- the [24e physical run](docs/verification/phase-24e-physical-2026-09-25.md)
  (2026-09-25/26);
- [clock, reply labelling and small.en](docs/verification/clock-routing-stt-physical-2026-09-27.md)
  (2026-09-27);
- the [correctness set](docs/verification/phase-24e-correctness-2026-09-25.md)
  (94.3%).

Owner decisions after closing, 2026-09-27:
- **Waived** as Phase 25 gates, never run on the robot: the supervised
  30-minute session, and cancelling a held turn (in-process test only).
- **Renewed usability acceptance.**
- **Deferred:** item 4, Nano diagnostics. The Nano has no persistent
  journal, no power logging and no diagnosis procedure. It needs the
  owner's sudo and approval.

**[Phase 24g](docs/phase-24g.md) is deployed and in physical testing; it is
not accepted (2026-09-27).** The design is in the
[ADR 0023 wake addendum](docs/adr/0023-robot-voice-conversation.md#addendum-wake-started-sessions-2026-09-27-phase-24g).

Owner decisions, 2026-09-27:
- monitoring is owner-armed and stays armed across restarts;
- anyone may converse while it is armed;
- candidates are transcribed in hub memory;
- the robot rests in its sleep pose while armed and idle, and lifts its head
  slightly to a silent alert pose on "Hey Reachy". This replaced the
  daemon's full wake-up move after the first physical run;
- `WAKE_ANIMATION_ENABLED` is on by default, including unattended production
  use while armed (exception recorded in AGENTS.md);
- the follow-up timeout is 10 s.

The detector is the community Edge Impulse "Hey Reachy" `.eim`
([bench and live session](docs/verification/phase-24g-detector-bench-2026-09-27.md)).
The robot's local acoustic-event filter is deferred, so the VAD and the hub
relevance rules gate candidates.

**Done this session.** Everything below is committed through `b62a023`:
- **Build:** the decisions, detector bench and live microphone session,
  implementation and tests. Checked off the robot: fast suites, browser
  tests, Postgres migration suite, the detector client against the real
  aarch64 model, and the pinned `ADD` lines on the Nano's Docker.
- **Deploy:** the homelab database was backed up and migrated to
  `009_wake_arm`. The hub and core were rebuilt at `b62a023`, and the Nano
  image rebuilt and recreated.
- **Physical runs:** see the
  [physical record](docs/verification/phase-24g-physical-2026-09-27.md).
  - Detection works: 8/8 in the first run, scores 0.77–0.99.
  - The full wake-up move broke candidates (its sound was recorded, and
    people waited for it). That led to the alert pose and new timings.
  - On `b62a023`, a conversation started by voice ran from 10:02:26 to
    10:03:52Z, then ended on the 10 s follow-up.
  - The hub also logged 4 `no_wake_phrase` rejections between 09:56 and
    10:00Z. Whether those were the owner's attempts or background speech is
    unattributed.

**Privacy carry-forward window shortened (`56f65dc`, 2026-09-27), deployed.**
The 24g physical run also showed "what's my next appointment" muting a
later, unrelated "tell me a story" for about 19 filler turns. Core's
`CONTEXT_MESSAGES` is now 15 (was 39); ADR 0006 ties it to the model's own
context on purpose, so both numbers moved together, not just the privacy
side. Companion-core was rebuilt and recreated on the homelab
(`docker restart` alone would not have picked up the code change); the hub
container itself was not touched, so the robot's WS connection and wake
arm were undisturbed. Not yet checked with a live "next appointment" ->
follow-up sequence on the robot.

**Owner requests 1–2 (2026-09-27)** — see the
[third physical run](docs/verification/phase-24g-physical-2026-09-27.md#third-run-on-0880b1b-silent-rest-poses):
1. **False wakes return to sleep silently: passed on the robot** with
   `0880b1b` (owner confirmed). The snore cause was idle behaviours
   clearing the rest pose; no daemon routine is used now.
2. **Home on admission: fixed in `c579cc8`, not yet on the robot.** On
   `0880b1b` it never ran, because the hub sends `voice_start` before it
   answers the candidate upload, and the suspend cancelled the monitor
   mid-upload. A suspend during a pending candidate now counts as the
   admission.

The owner also switched the 24f motion on for a session and reported it
behaved as expected. That is an observation, not 24f acceptance. The
motion switches reset to off on the next embodiment restart.

**Home on admission: confirmed on the robot, `c579cc8` running since
10:57:45Z.** The daemon's access log shows a goto right after each
`wake candidate admitted` (11:05:12.9Z and 11:06:28.7Z), before the later
sleep return. No further action needed on this item.

**Session 1 (calibration) done, 2026-09-27 13:43-14:46Z — clean, no
issues found.** 26 wake detections, 24 rejected `no_wake_phrase`, 1
discarded (no speech followed), 1 admitted. The owner confirms only 1
deliberate "Hey Reachy" attempt was made and it succeeded first try; the
other 25 were the scripted false-trigger scenarios, all correctly
rejected. Isolation checks (no TTS/tools/search/durable transcript,
robot returns to sleep) pass for all 25. Raw logs in
`/tmp/.../scratchpad/24g-acceptance/` (session-scoped, not durable).

Added a log line (`bab441e`) so admission latency (upload -> voice_start)
can actually be measured — the existing logs only gave detected-to-
admitted, which conflates the caller's own speech duration. Deployed and
confirmed running (`reachy-embodiment:local`, re-registered as `nano-1`,
re-armed automatically).

**Session 2 (first held-out attempt), 2026-09-27 15:08-15:16Z — found a
real bug, not scored as final.** 8 detections: 4 rejected
`no_wake_phrase`, 1 discarded ("no request followed"), 3 admitted (each a
clean multi-turn conversation). Isolation checks pass; no stray tool/
search activity. The discard was a genuine attempt: the owner said "Hey
Reachy," waited to see the alert-pose cue, then started speaking — by
then most of the 4 s `speech_start_seconds` budget was gone (the alert
goto itself dispatches within ~1s of detection, so the shortfall is
human reaction time to the cue, not code latency). 3/4 genuine acceptance
(75%) misses the 90% target.

**Fixed (`4b6893b`): `speech_start_seconds` raised 4.0 -> 6.0s** in
`shared/models/robot_voice.py` (only the hub needs
rebuilding for this one — the robot always runs whatever `WakeLimits` the
hub sends at arm time, no Nano image change needed). ADR 0023 and the
fixture-timing tests updated. Homelab hub/core rebuilt and restarted;
robot reconnected and re-armed automatically, wake counters reset to
0/0/{}.

**Session 3 (fresh held-out run): deferred by the owner, 2026-09-28 —
not started.** When resumed: full scenario list cold, plus several
genuine attempts (3-5 each of immediate-question and natural-pause) so
the acceptance-rate sample is meaningful (Session 1's single genuine
attempt wasn't). Score against the agreed targets below; if it passes,
write `docs/verification/phase-24g-<date>.md` per the plan.

**Numeric targets agreed (owner, 2026-09-27)** — see
[phase-24g.md](docs/phase-24g.md#agreed-numeric-targets-owner-2026-09-27):
false conversations ≤1/2h (held-out), genuine-turn acceptance ≥90%, added
admission latency p50≤1.5s/p95≤3s, one calibration session then one
held-out session, both with 24f motion off.

**New `Trusted` interaction mode added (2026-09-27), not yet deployed.**
Owner asked for a mode where Reachy answers everything spoken, with no
privacy-centric restrictions. Scoped with the owner to exactly one thing:
`apply_privacy_override` (ADR 0006) no longer vetoes work-private/sensitive
content to a text channel when `session.interaction_mode == TRUSTED` —
everything else is untouched, confirmed with the owner explicitly:
- ADR 0011's destructive-action consent (voice can never confirm a
  destructive action; bulk always blocked) is unaffected — it has no
  `interaction_mode` input at all.
- `robot_speech_withheld_reason`'s DND/meeting vetoes (ambient room
  occupancy, not content classification) are unaffected — out of scope.
- Settable only from the operator UI's mode selector (`PATCH
  /sessions/{user_id}/mode`), never from a spoken/text command — owner was
  explicit trusted mode must not be reachable via `/reachy ...` parsing.

See the [ADR 0006 addendum](docs/adr/0006-response-routing.md#trusted-mode-exempts-the-privacy-veto-2026-09-27).
Changed: `shared/models/session.py` (new enum member),
`reachy_hub/response_policy.py` (`apply_privacy_override` gained a `mode`
param), the four call sites in `reachy_hub/app.py`, operator-ui's mode
`<select>`, and `docs/plan.md`'s mode table. Full `pytest services shared`
(813 passed) and Ruff pass locally. Not yet deployed to the homelab or
exercised on the robot — needs a rebuild/redeploy of reachy-hub and a live
operator-UI check before the owner tries it.

**Next: run the 24g acceptance scenarios (the phase's remaining gate).**
1. Run every scenario in the
   [acceptance requirements](docs/phase-24g.md#acceptance-requirements)
   list (coughs, sneezes, TV/podcast speech, nearby conversation, false
   wake + continued talk, wake + silence, genuine immediate and
   naturally-paused requests, etc.), each checked against the rejected-
   candidate isolation list (no session, no TTS, no tools/search, no
   durable transcript, discarded audio, robot returns to its prior state).
3. Record wake candidates/hour, false conversations admitted/hour,
   exposure hours, scenario counts, false rejects and p50/p95 admission
   latency in a new dated
   `docs/verification/phase-24g-<date>.md`, separating fixture/real-
   process/physical evidence.
4. While at it, do a live check of the shortened privacy window
   (`56f65dc`): ask a calendar question, then ~7-8 unrelated follow-ups,
   and confirm the speaker un-mutes instead of staying silent for ~19
   turns.

Scratch on the Nano: `~/24g-bench` (models, clips, wheels) and `~/24g-src`
(source mounts for the detector check); both are disposable.
Phase 25 owner recognition follows; its
24e prerequisites remain settled. Keep conversational motion off until
24f's deferred rows pass.

TV speech answered as a turn remains a known limit: 24g now covers false
wake admission, while Phase 25 retains speaker attribution and open-session
input gating. The audio-fault recovery sub-row is in process only, also by
owner decision.

**Owner decisions on 2026-09-27:**
- Open-ended spoken questions take about 8 s to first audio, because the
  local model writes about 60 words at about 21 tokens/s. This is
  accepted as is: the 4 s budget is measured on short questions.
- [Phase 24f](docs/phase-24f.md) is **closed by re-scope**. Its passed
  rows are silent poses, wobble, stops, 409 arbitration, palm stop and
  switch-off. The rest is deferred to a future phase, so Phase 25 runs
  with motion off until those pass.

**Fixed and deployed 2026-09-27:**
- **Camera across daemon media restarts** (`0ec9c52`, `6f6eb24`): a
  standby wake used to leave the camera and palm stop without frames
  until embodiment restarted. It is now verified with a no-motion media
  release/acquire
  ([record](docs/verification/phase-24f-physical-2026-09-27.md#camera-socket-fix-on-nano-1)).
  A real standby wake has not been retried: after the next `/reachy wake`,
  confirm that palm stop still works.
- **Abandoned palm-frame uploads:** the hub answers them with a 400
  instead of a traceback.

**Noticed, not investigated:** a recreated hub container downloads small.en
again (112 s before voice works).

## Last-reported machine state

These are previous session observations, not health checks performed during
this documentation pass. Recheck state before relying on them.

- **Nano:** booted 2026-09-27 06:47 WIB (motor supply was off on the first
  boot; the once-per-boot recovery restarted the daemon once and stopped,
  as designed). The daemon runs as PID 7340 and was `running` at 09:33Z.
  - **Checkout and image:** the checkout is `c579cc8`, and
    `reachy-embodiment:local` = `c579cc8` (`a9baf002`, log
    `~/24g-logs/build-c579cc8.log`). The **running container is on
    `15ba2797` (`0880b1b`)**, recreated by the owner at 10:43:42Z with
    voice on and `WAKE_ANIMATION_ENABLED=true`. "Hey Reachy" was **armed**
    (the arm is stored in the hub database; disarm from the robot
    microphone panel). The owner switched the 24f motion on at about
    10:48Z.
  - **Rollback:** `:0880b1b` (`15ba2797`), then `:b62a023` (`ebfffcef`),
    then `:6f6eb24` (`0ab5ebdf`); roll the checkout back with it.
  - **Motion:** 24f gestures and wobble were switched **on** by the owner
    at about 10:48Z; they reset to off on any embodiment restart.
  - **Access:** sudo on the Nano needs a password, so the owner runs
    `systemctl` steps and container recreates. This dev box has key SSH
    as `Reachy-Mini-Jetson`.
  - **Tools:** the system `python3` is too old for `voice-timing.py`: use
    `~/reachy-venv/bin/python`, and pass `--session N` when a log holds
    several voice sessions. There is no MediaPipe on the Nano (palm stop is
    hub-side). `opencv-python-headless` for the 24f tools is in
    `~/24f-tools` only (use `PYTHONPATH`).
  - **Logs:** `~/24f-logs` and `~/24d-logs`; the 24g image build logs are
    in `~/24g-logs`.
  - **Units:** `reachy-embodiment.service` and
    `reachy-daemon-recovery.service` are enabled, and the container has no
    Docker restart policy.
  - **Network:** embodiment is host-networked on 8100, and the daemon is on
    loopback 8000.

  Apply the [deployment boundaries](docs/deployment.md#robot-host-and-jetson-nano)
  before daemon starts or motion; `--check` stays read-only.
- **Homelab:** hub and core were rebuilt at `ef40307` (2026-09-28
  05:29:39Z) for the owner-recognition portal + persistent capture volume;
  migrate ran (no new migration in this deploy, still `009_wake_arm`). The
  new `owner-recognition-captures` volume exists and was confirmed to
  persist a sample across a `docker restart` of the hub container.
  `STT_MODEL=small.en`, `PALM_STOP_ENABLED=true` and
  `VOICE_CONTINUATION_WINDOW_MS=3000` are in the private `.env`. The
  schema is `009_wake_arm`. The latest pre-deploy backup is
  `~/reachy-backups/reachy-before-owner-recognition-deploy-20260928T052840.dump`
  (backups are 0600). Start only through `scripts/start-homelab.sh`, which
  is allowed in the gitignored `.claude/settings.local.json`, so a session
  can run it. To restart only core, run
  `docker restart reachy-homelab-companion-core-1`: `docker compose
  restart` without the launcher fails on the generated SearXNG secret.
  Core readiness needs a separate check after the launcher's hub health.
  The hub's in-memory turn records (`GET /hub/robot-voice` with the
  `REMOTE_UI_TOKEN` bearer) give per-turn STT/LLM/TTS timings. They also
  contain transcripts, so extract only what a record needs. Piper
  `en_US-lessac-medium`; search policy Auto, Brave/Exa/Tavily rotation,
  then SearXNG.
- **Local inference:** an unrelated `ovms` container serves
  `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` on localhost:8000. Leave
  unrelated services alone.
- Hosted credentials are in gitignored `deploy/homelab/.env.local`.
  Check presence and ignore rules without printing values. No Google OAuth
  client file or live helper run has been supplied.
- Nano Tailscale endpoints to the homelab have switched between
  10.180.1.23, .54 and .254. Network cleanup remains the owner's call.

## Immediate cautions and continuation

The unexplained power loss, RTC problem, daemon recovery verification
limit and the 2–5° motion shortfall are in
[project state](docs/project-state.md#known-hardware-and-software-limitations).
The automatic error restart has one real run (2026-09-27, no motor power);
a wake-up error restart is still fake-tested only.

Inspect `git status`, recent commits and the diff before implementation.
Hardware work previously involved a separate Nano-side session; verify raw
device identity before accepting remote reports. Use
[camera socket recovery](docs/deployment.md#camera-socket-directory-recovery)
if the socket becomes a directory again. Durable build, credential, upgrade
and supervision procedures are in the deployment/development guides.
