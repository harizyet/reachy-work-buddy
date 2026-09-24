# Phase 25 — owner recognition and voice access control

Status: planned, not implemented. Depends on Phase 22 physical deployment
and Phase 23's read-only Google integration. Implementation starts only after
[Phases 24c–24d](phase-24cd.md) complete and physically verify the baseline
Reachy conversation workflow. Recognition gates an already-working capture,
conversation and playback path; it must not assume isolated speech components
prove that path. This is a single-owner system:
verify the enrolled owner, leave everybody else unknown. Do not identify
bystanders or build a general face directory.

## Required behaviour

The robot may share audible conversation only while it has **strictly more
than 60% calibrated confidence that the live owner is currently in view**.
Exactly 60%, missing evidence, poor-quality images, stale frames, a covered
camera, missing enrollment or failed recognition all mean silence. This is
a necessary condition, not sufficient permission to speak: existing privacy,
Office/Silent/DND and private-call routing rules still apply.

Camera recognition alone cannot authorize microphone input: somebody else
could speak while the owner is visible. A room voice turn also requires
fresh owner presence and evidence linking that utterance to the live owner.
Unknown speakers, overlap, replay or ambiguous attribution must not reach
the conversational runtime, tools, durable memory or confirmation handlers.

Recognition grants no email/calendar write permission. Even a correctly
recognized owner cannot approve consequential actions by voice. Preserve
ADR 0011's text-only approval, delayed email send/undo and bulk-destructive
block. Phase 23 Google adapters remain read-only. Creating 100 calendar
events, sending email, and deleting email must never become executable just
because a face or voice matched. Any later external write capability needs
authenticated owner text confirmation bound to the exact action, resource,
parameters and expiry; deny bulk event creation and repeated-action attempts
that try to evade the bulk rule. Define bounded per-owner action rates before
enabling writes. An LLM cannot supply or override identity evidence.

## Confidence and threat model

Do not display a cosine similarity, face detection confidence or STT word
confidence as probability of owner identity. Select a verification model,
calibrate its decision scores on held-out owner/non-owner recordings from
the deployment conditions, and version the model, calibration and thresholds.
The speech decision requires calibrated confidence >0.60 **and** a stricter
match threshold if needed to meet the measured false-accept target. Never
lower the 60% floor to improve convenience. If calibration cannot support a
meaningful probability, percentage-based acceptance is blocked, not invented.

Evaluate false accepts/rejects as well as usability across lighting, pose,
distance, glasses and background noise. Separate enrollment, calibration
and evaluation sessions; neighbouring frames from the same clip are not
independent trials. Confidence is conditional on the evaluation conditions,
not a guarantee against a new attacker.

Required threats: owner absent; unknown person beside a visible owner;
off-camera speech; two people speaking; printed face; face video on a phone;
recorded or synthesized owner voice; replayed frames/recognition messages;
owner departure during inference/playback; recognition-service outage; and
direct API calls that claim `user_id`, `TEXT`, or `owner_verified=true`.
Implement and evaluate liveness/presentation-attack checks, rather than
treating a blink detector or a speaker embedding as proven authentication.
NIST describes biometric limitations and presentation-attack mitigation in
[its authentication guidance](https://pages.nist.gov/800-63-4/sp800-63b.html);
its [face verification evaluation](https://pages.nist.gov/frvt/html/frvt11.html)
reports error rates at specified thresholds. These inform the test design;
this phase does not claim NIST authentication-level compliance.

## Architecture and implementation sequence

1. **Threat-model and boundary ADR.** Before implementation, document the
   trusted camera/microphone path, inference placement, evidence contract,
   owner/channel mapping, playback enforcement and changes to currently
   trusted-network API access. Preserve service boundaries: perception is
   robot-side sensor processing, hub admits channel input, core authorizes
   tools, embodiment enforces actual room playback.
2. **Owner enrollment and recovery.** Add Settings → Owner recognition to
   the existing GUI. Require owner login plus fresh password reauthentication
   and CSRF protection to enroll, replace or delete templates. Capture live
   samples over several poses/lighting conditions with quality checks and
   guided speaker enrollment if used. No automatic learning from passers-by
   or unauthenticated first-face enrollment. Offer re-enrollment and private
   text recovery; disabling recognition leaves room voice locked.
3. **Local perception.** Evaluate face verification, liveness and speaker
   attribution on actual hardware before selecting dependencies. Voice
   verification can assist attribution but cannot be its only authorization
   signal; combine it with live visual/audio association, or require an
   authenticated owner-controlled push-to-talk session when reliable ambient
   attribution is unavailable. In that mode retain the in-view requirement
   for room voice and mark ambient mode unavailable. A wake word, nearby face,
   or STT confidence alone is insufficient. Reject overlap by default.
4. **Short-lived evidence.** Define shared contracts for owner ID, sensor
   and robot IDs, capture time, sequence/nonce, model/calibration version,
   confidence, quality/liveness status, expiry and utterance binding. Validate
   source authentication, freshness, replay protection and owner mapping at
   service boundaries. Accept evidence only from provisioned perception
   services, never browser-submitted scores. Reset trust on reboot/reconnect;
   use monotonic local expiry so clock changes cannot extend permission.
5. **Input gate.** Gate room capture before general STT. A short, bounded,
   volatile audio buffer may be used locally for speaker/liveness analysis;
   it is not permission to transcribe/upload unknown speech. Recheck the
   whole utterance before admitting a transcript, and discard buffered audio,
   transcripts and late inference results when attribution fails. Preserve
   `InputModality.VOICE` end to end, regardless of recognition success.
6. **Output gate.** Check presence before TTS dispatch and immediately before
   playback, then continuously during playback. Stop and discard queued audio
   on loss of permission; do not automatically resume an old private reply
   when a face returns. Implement cancellable playback and bounded audio
   buffers in the real backend. Cover all speaker paths: conversation,
   briefing/reminders, greetings with speech, remote speak and `/audio/play`.
   No direct endpoint or offline fallback phrase may bypass the gate. Local
   silent motion/presence continues without recognition or homelab services.
7. **Authenticated channels and tools.** Audit `/messages`, `/voice/turn`,
   WebRTC signaling, Telegram sender/chat mappings, core direct routes and
   Caddy debug proxies. Bind principals server-side; arbitrary caller-supplied
   modality/user IDs are not approval. Require owner authentication for user
   calls and scoped service authentication internally. Preserve bearer clients
   using explicit privileges, not a universal impersonation shortcut. Private
   authenticated phone/browser calls need no room-camera presence if output
   stays on the private device; they remain VOICE and cannot confirm writes.
   Room-speaker output from remote control still requires local owner presence.
8. **GUI and diagnostics.** Show Enrolled/Locked/Owner present/Uncertain/
   Sensor unavailable, evidence age, permitted input/output, and plain-language
   denial reason. Show calibrated confidence with its limitations. Provide
   silent status and private authenticated text fallback instead of speaking
   an error to an unknown person. No guest override for personal conversations.

Owner presence does not prove the room is private. Known or unknown
bystanders do not authorize disclosure; detected additional people should
force personal content to a private channel. Office privacy remains in force
even when only the owner is detected, since people outside the camera may
still hear. Ordinary non-conversational emergency stop/mute controls may
always reduce activity; they cannot expose data or authorize work actions.

## Web portal calibration and accuracy testing

Settings → Owner recognition is the complete owner-facing workflow:
**Enroll → Calibrate → Test accuracy → Review → Activate**. No shell commands
or manually edited threshold files are required. Use the existing authenticated
portal at `/ui/` and `/hub/ui/`, with desktop/mobile layouts. The portal
controls capture and displays results; trusted local services compute scores
and enforce activation rules. Browser-supplied scores cannot grant access.

### Guided calibration

- Show the selected robot, camera and microphone, live preview, sensor health,
  lighting/face quality and capture progress. Calibration must use the actual
  deployed Reachy sensors and processing path. A laptop webcam/microphone test
  is explicitly a separate diagnostic and cannot validate the robot profile.
- Guide the owner through poses, distance, lighting, glasses if applicable,
  and spoken samples. Explain each step, permit retry/cancel, and flag poor
  quality without silently accepting it. Collect consenting non-owner trials
  with anonymous labels; no non-owner identity enrollment is needed.
- Separate enrollment, calibration and held-out test sessions in the portal.
  Fit a candidate calibration without changing the active profile. Once a
  test set has informed tuning, retire it as a final holdout and collect new
  trials. Repeated video frames must not inflate the displayed sample count.
- Keep samples transient by default. Explain any optional encrypted diagnostic
  retention, its expiry and deletion before capture. Cancel/logout/timeout
  stops collection and clears transient samples; no unfinished profile can
  activate. Store versioned calibration parameters and aggregate results
  without requiring retention of raw face/audio recordings.

### Test accuracy

Provide a repeatable **Test accuracy** action for either the active or a
candidate profile, with a clearly visible profile/version and test-only mode.
Offer an immediate live check and a guided evaluation covering owner present,
owner absent, a consenting non-owner, owner leaving, owner visible while
someone else speaks, overlap and replay scenarios. The owner labels expected
presence/speaker before each trial; the recognizer must not label its own
ground truth. Missing scenarios remain untested, not assumed successful.

Show live owner confidence when valid, liveness/quality and evidence age,
speaker attribution, and separate “Would accept voice” / “Would speak”
decisions with reasons. These are dry-run decisions: diagnostic audio and
transcripts never reach conversations, memory, mail/calendar tools or approval
handlers. A separate explicit playback test uses a harmless fixed phrase and
retains every presence/privacy gate, so the owner can measure physical mute
latency without exposing personal content. Test mode cannot unlock production
speech or admit guest commands.

The results page includes:

- Counts of correct owner accepts, owner rejects, correct non-owner rejects
  and false accepts, with denominators and rates; no misleading single
  “accuracy” percentage for an imbalanced sample.
- Face-presence, speaker-attribution and final input/output gate results
  separately, plus spoof-test outcomes and p50/p95 acquisition/mute latency.
- Coverage by lighting/distance/noise, independent session/participant counts,
  uncertainty and “insufficient evidence” where appropriate. Show calibration
  reliability on held-out labelled trials separately from match accuracy;
  never present a percentage as validated solely because matching was accurate.
- Side-by-side active/candidate results, failed acceptance criteria and a
  redacted downloadable report (JSON/CSV), without biometric media or secrets.

### Review and activation

The owner can retry calibration, discard a candidate, or activate one after
review. Activation requires fresh owner reauthentication, CSRF protection and
server-side validation of the applicable Phase 25 acceptance gates below.
A quick successful selfie check is not sufficient. Incomplete/failed evidence
keeps the candidate diagnostic-only; show exactly which tests remain.

Keep the strictly >60% floor and other safety rules immutable from ordinary
portal controls. More restrictive sensitivity settings require a fresh test
run; do not provide an unsafe slider to trade false accepts for convenience.
Activate atomically, version/audit changes, invalidate old recognition leases,
and reacquire live evidence. Interrupted activation keeps the prior profile.
Rollback is available only to a previously validated profile compatible with
the current model/sensors. A changed model, camera/microphone or processing
path invalidates affected calibration and requires retesting before voice is
enabled. If there is no valid active profile, remain locked with text access.

## Deployment, data and timing

Prefer local inference; no raw faces, voiceprints or room audio sent to a
cloud LLM or stored in conversation memory. Encrypt enrolled templates,
restrict access, provide deletion/key rotation and document backup retention.
Discard raw enrollment captures after template creation unless the owner
explicitly opts into a bounded diagnostic dataset. Audit decisions and model
versions without recording bystander identities or raw biometrics.

The original Jetson Nano is a candidate for perception only after Phase 22's
runtime/memory/thermal checks. If it cannot sustain the gate's timing, choose
a supported local host or keep ambient voice disabled; do not weaken checks.
Nano/perception failure may lock voice but must not stop independent Reachy
idle/fallback motion. This deliberately degrades voice availability safely
while retaining ADR 0004's embodiment availability guarantee.

Initial timing targets, to validate on hardware: acquire permission after
at least three qualifying observations spanning 500 ms; evidence expires
within 1 s of capture; any detected disqualifying observation locks immediately
without a lower-threshold grace period. Stop audible playback within 1 s of
owner loss or sensor failure, including queued/hardware audio. Test the actual
speaker tail, not just a cancelled HTTP request. Bound and report unavoidable
audio exposure during that interval. A frozen camera cannot renew evidence
by repeatedly scoring the same frame.

## Acceptance and release gate

| Check | Required result |
|---|---|
| Threshold boundaries | 0.5999, 0.6000, missing/NaN/out-of-range and stale evidence deny; >0.60 permits only when every other gate passes; tested without real-time sleeps |
| Portal workflow | Owner completes enrollment, calibration, held-out accuracy testing, report review and activation entirely in the web portal on direct/proxied mounts and desktop/mobile; correct robot sensors and profile versions are visible |
| Portal safeguards | Test data cannot invoke tools or unlock production voice; forged results/labels alone cannot bypass trusted capture or activation checks; cancel/logout/failed activation preserve valid state, and incompatible rollback is blocked |
| Accuracy reporting | Known labelled fixtures yield correct confusion counts/rates and latency summaries; independent trial counts, untested scenarios, calibration reliability and insufficient evidence are reported honestly; exports contain no raw biometrics |
| Owner usability | At least 100 held-out live owner trials over three sessions and representative conditions; >=95% accepted within 2 s in the documented supported operating range; report exclusions and false rejects |
| Unknown-owner rejection | At least 300 independent non-owner attempts spanning at least 10 consenting participants and varied conditions, zero unauthorized admissions/playbacks; report participant clustering and a justified uncertainty estimate, not a claimed universal error rate |
| Spoof/attribution | At least 20 trials each for printed face, displayed face video, owner-audio replay, synthesized audio, owner visible while somebody else speaks, and overlapping speech; zero unauthorized admissions; unavailable attack tests are BLOCKED |
| Loss during a turn | Owner leaves before capture, during STT, during inference and during playback; late results are dropped, no new audio starts, existing playback stops within the 1 s budget |
| Failure/replay | Cover camera disconnect/freeze, darkness, stale/out-of-order/fabricated evidence, service/Nano outage, reboot, time changes and model mismatch; lock voice and retain silent presence |
| Path coverage | Exercise real speaker output through every route, including remote speak and proactive delivery; no backend/API bypass; authenticated private text remains available |
| Malicious actions | Unknown and recognized-owner voice requests to delete mail, send mail or create 100 events cause zero provider writes; direct forged TEXT/user-ID requests also fail; test repeated single-action bulk evasion and pending-approval replay |
| Privacy and enrollment | No unapproved biometric persistence/cloud upload; enrollment replacement requires owner reauthentication; template deletion locks voice; shared-room/Office behaviour retains private routing |
| Full integration | Python/Ruff/browser checks pass, with real hardware face/audio tests and an 8-hour mixed-use run; existing Phase 22/23 startup, outage, privacy and read-only Google tests still pass |

Use safe fixtures and instrumented provider adapters to verify destructive
attempts; never test deletion or event spam on real production accounts.
Record hardware/model/calibration versions, thresholds, trial counts,
false accepts/rejects, p50/p95 timing, resource use and limitations in
`docs/verification/phase-24-<date>.md`. Keep biometric datasets outside git.
Small attack suites demonstrate only those attacks; do not claim immunity
to deepfakes or statistically strong security from zero observed failures.

Phase 25 is complete only when every required gate passes on the deployed
hardware with no unauthorized speech admission, audible disclosure or action
in the acceptance suite. If attribution/liveness or hardware throughput is
inadequate, ship private text/explicit authenticated interaction as a limited
mode and leave ambient owner-only voice marked blocked. No implementation,
enrollment or live recognition testing is performed by this planning change.
