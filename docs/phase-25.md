# Phase 25 — tiered owner verification and progressive trust

Status: planned, not implemented; **follows [Phase 24g](phase-24g.md)**
in the roadmap. The 24e prerequisites passed or were waived on 2026-09-27.
Compose recognition with 24g wake admission: relevance is interaction routing,
never identity evidence. Unknown/ambiguous speakers still require rejection
during an open session; wake admission cannot relax this phase's pre-STT
attribution or input/output gates. Depends on
[Phase 24c](phase-24cd.md#phase-24c--audit-and-implement-the-missing-workflow)
implementing the baseline Reachy conversation workflow and
[Phase 24d](phase-24cd.md#phase-24d--physical-end-to-end-acceptance)
closing its core physical conversation workflow. Implementation starts only
when the [24e conversation-path prerequisites](phase-24e.md#prerequisites-for-phase-25)
pass, including adaptive end of turn and physical privacy/auth/cancellation,
expiry, recovery and sustained-use acceptance, with Normal conversation and
Timing rerun after the changes. BLOCKED or deferred prerequisites do not
satisfy this gate. The owner waived the 30-minute session and held-turn
cancellation, and renewed usability acceptance, on 2026-09-27
([waiver](phase-24e.md#prerequisites-for-phase-25)). If Phase 24f motion is enabled on the recognition stack, its
[conformance and coexistence dependency](phase-24f.md#order-and-dependencies)
also applies; expressive animation is not itself a Phase 25 start prerequisite.
Answer quality, search/STT tuning and Nano diagnostics are
not prerequisites. It also builds on the Phase 22 physical deployment substrate and the
existing Phase 19 owner login and Phase 20 web-chat session infrastructure. Phase 23
Google integration is not a prerequisite; its read-only adapters are only
regression context for the write-gating tests below. Recognition gates an already-working capture,
conversation and playback path; it must not assume isolated speech components
prove that path. This is a single-owner system:
verify the enrolled owner, leave everybody else unknown. Do not identify
bystanders or build a general face directory.

This revises the phase's original single-threshold design ("strictly >60%
calibrated confidence that the live owner is in view" as the sole room-voice
gate). That design is retired in favour of the progressive-trust model below,
which was chosen so that harmless requests do not wait on the slowest sensor:
identity evidence is continuously derived per modality, combined into a
trust level, and checked against the sensitivity of the specific request,
instead of gating all room speech behind one visual threshold. The retired
design's engineering rigour — calibrated (not raw) confidence, adversarial
and reboot/failure testing, an owner-facing calibration portal, no LLM
authority over identity, and preserved destructive-action policy — carries
forward unchanged; only the single-gate shape is replaced.

## Sub-phases and progression

```text
Phase 24g
Wake-word and relevance admission
        ↓
Phase 25a
Owner voice verification
        ↓
Provisional trust (T1)
        ↓
Low-risk interaction may proceed immediately
        ↓
Reachy orients toward the speaker using sound direction
        ↓
Phase 25b
Visual owner verification and liveness
        ↓
Higher trust (T2) for personal/private interaction
```

**Guiding principles:** respond quickly at the lowest safe trust level; trust
may rise only from fresh qualifying evidence, but it may fall immediately
whenever that evidence becomes stale, contradictory or unavailable.

### Phase 25a — owner voice verification

Determines whether the current speaker matches the enrolled owner, and
produces short-lived identity evidence — never a persistent
`authorized=true` state. Speaker evidence includes: owner identity,
utterance identifier, calibrated speaker-match confidence, capture
timestamp, evidence expiry, audio quality, model/calibration version, and a
replay/liveness result where supported. Verification runs on the exact
utterance admitted through the [Phase 24g](phase-24g.md) wake/admission
path — not on a separately captured sample.

A successful match raises the interaction to provisional owner trust (T1).
This may allow ordinary low-risk conversation immediately, but voice
verification alone does not authorize sensitive personal disclosure in an
ambient room. 25a must evaluate: unknown speakers, background speakers,
overlapping speech, recorded owner speech, synthesized/cloned speech,
varying distance and orientation, office/background noise, and microphone
variation. Identity evidence is not the same thing as full ambient
authorization.

### Phase 25b — visual owner verification and multimodal trust

Uses Reachy's camera to obtain independent evidence that the enrolled owner
is physically present. Where useful, Reachy uses microphone direction of
arrival (DoA) to orient its head toward the detected speaker before visual
verification, so face acquisition does not depend on the owner already
facing the camera.

Intended flow: wake admission succeeds → voice matches owner (T1) → Reachy
answers a permitted request immediately → in parallel, DoA orients the head
toward the speaker → camera observes the face → owner face verification and
liveness run → trust elevates to T2 if evidence qualifies. Visual
verification covers: owner face matching, face/image quality, liveness or
presentation-attack checks, evidence freshness, frozen/replayed-frame
detection, camera health, and temporal consistency with the active
interaction. DoA supports orientation and speaker-to-face association; it is
never identity evidence by itself (`DoA ≠ identity`).

## Progressive trust levels

Trust is computed from evidence, never stored as a persisted flag:

```text
if authenticated_private_channel:
    T3
elif fresh_current_owner_voice and fresh_live_owner_face and association_valid:
    T2
elif fresh_owner_voice:
    T1
else:
    T0
```

| Level | Evidence | Typical permissions |
|---|---|---|
| **T0** — unverified | 24g wake/admission only, or no fresh owner biometric evidence | Public information, harmless general conversation, generic assistant capabilities ("What time is it?", "What's the weather?", general knowledge) |
| **T1** — voice verified | Fresh Phase 25a owner-speaker verification | Normal low-risk conversation, conversational continuity, public/general queries without waiting for visual verification. T1 does not by itself unlock sensitive personal information in an ambient room |
| **T2** — multimodal owner verified | Fresh owner voice evidence + fresh live visual owner evidence + valid audio/visual association | Personal/private room responses: calendar and email reads, private notes and reminders, other sensitive information permitted by the normal privacy policy |
| **T3** — authenticated channel | Authenticated browser, authenticated private device, authenticated text channel, or other server-bound principal authentication. Not derived from biometrics | Existing operating-mode/privacy rules still apply; consequential workflows still hit their existing confirmation gates ([ADR 0011](adr/0011-destructive-action-consent.md)). Biometric or device authentication never bypasses destructive-action policy |

Effective trust is recomputed, not read from a cache, at least: after wake
admission; at utterance start; after speaker verification; after visual
verification; before admitting protected input; before tool/data access;
before TTS; throughout sensitive playback; whenever sensor state changes;
whenever evidence expires.

### Trust level × request sensitivity

Authorization is `current trust level × request sensitivity`, and the
mapping is deterministic — the LLM may classify or suggest sensitivity where
useful, but it may not raise trust or bypass policy:

| Request | Minimum trust |
|---|---|
| "What time is it?" / "What's the weather?" / "Tell me a joke." / general knowledge | T0 |
| Normal low-risk conversation | T0/T1 |
| "What's my next appointment?" / "Read my latest email." / "What's in my private notes?" | T2 |
| "Draft an email…" | T2 |
| "Send this email." | T2 plus existing authenticated-text confirmation |
| Bulk/destructive operation | Existing hard authorization policy, unchanged |

### Quality-of-life: answer at the lowest safe level

Biometric verification must not create unnecessary latency for harmless
interaction. If a request is permitted at the current trust level, Reachy
answers immediately while stronger verification proceeds asynchronously —
for example, answering "What time is it?" on a T1 voice match while DoA
orientation and T2 face/liveness verification continue in parallel, so that
a following "What's my next appointment?" can be answered immediately if
fresh T2 evidence has already landed. This lets identity verification
improve the conversation rather than becoming a mandatory delay before every
response.

## Confidence and threat model

Do not display a cosine similarity, face-detection confidence or STT word
confidence as probability of owner identity. Select a verification model per
modality (voice, face), calibrate its decision scores on held-out
owner/non-owner recordings from the deployment conditions, and version the
model, calibration and thresholds independently for each modality and each
trust level they gate. If calibration cannot support a meaningful
probability, percentage-based acceptance for that modality is blocked, not
invented — the affected trust level is simply unreachable until it can.

Evaluate false accepts/rejects as well as usability across lighting, pose,
distance, glasses and background noise. Separate enrollment, calibration and
evaluation sessions; neighbouring frames from the same clip are not
independent trials. Confidence is conditional on the evaluation conditions,
not a guarantee against a new attacker.

Required threats: owner absent; unknown person beside a visible owner;
off-camera speech; two people speaking; printed face; face video on a phone;
recorded or synthesized owner voice; replayed frames/recognition messages;
owner departure during inference/playback; recognition-service outage; and
direct API calls that claim `user_id`, trust level, or `owner_verified=true`.
Implement and evaluate liveness/presentation-attack checks, rather than
treating a blink detector or a speaker embedding as proven authentication.
NIST describes biometric limitations and presentation-attack mitigation in
[its authentication guidance](https://pages.nist.gov/800-63-4/sp800-63b.html);
its [face verification evaluation](https://pages.nist.gov/frvt/html/frvt11.html)
reports error rates at specified thresholds. These inform the test design;
this phase does not claim NIST authentication-level compliance.

## Trust evidence and expiry

Each evidence source expires independently, and none of it is a long-lived
boolean.

**Wake evidence** is not identity evidence: valid only for the immediate
candidate interaction, consumed when the first utterance is admitted,
discarded if no valid utterance follows, and it cannot carry into a later
conversation or raise T1/T2.

**Voice evidence / T1.** Speaker verification applies immediately to the
current utterance. Provisional T1 carries forward for **10 seconds** after
the end of the last successfully owner-verified utterance; a new
owner-verified utterance refreshes that timer. Sensitive requests require
speaker verification of the *current* utterance, not merely carry-forward
trust. Immediate T1 invalidation: unknown speaker; current speaker
verification failure; overlapping speech; replay/synthetic-speech detection
failure; microphone restart/reset; speaker-verification service restart;
robot/hub reconnect affecting the evidence path; session termination.

**Visual evidence / T2.** Require at least **3 qualifying observations
spanning at least 500 ms** before initially establishing T2. Each fresh
qualifying observation refreshes visual evidence; visual evidence expires
**1 second** after the last qualifying frame. Frozen or repeated copies of
the same frame cannot refresh trust. Qualifying observations must continue
to satisfy the owner-match threshold, liveness/presentation checks,
image-quality requirements and camera-health requirements.

### Downgrade, not termination, where safe

Reduced trust should reduce permissions rather than unnecessarily end the
conversation:

```text
T2 → T1   visual evidence >1 s old, voice evidence still valid
          (owner moves out of view, occlusion, insufficient lighting,
           unverifiable pose, camera stalls, liveness unavailable without
           positive spoof evidence)

T2 → T0   identity association becomes unsafe
          (current utterance fails voice verification, another/overlapping
           speaker, printed-face or displayed-face/video replay detected,
           frozen camera evidence, face/voice direction materially
           inconsistent, contradictory biometric reports, both voice and
           visual evidence stale)

T1 → T0   speaker mismatch, unknown speaker, overlap, replay/synthetic
          speech, microphone reset, verification service failure, new
          session boundary, end of the current conversation
```

Example: at T2, "What's the weather?" stays allowed after a downgrade to
T1 from the owner looking away; "Read my latest email" is not allowed at
T1 — Reachy may say stronger verification or a private channel is needed,
or route the response privately per existing policy. Likewise, once T1
expires to T0, general conversation can continue if otherwise permitted,
but private information remains unavailable.

### Sensitive-request freshness

Public/harmless requests (time, weather, general knowledge, jokes) need
only T0-or-higher, with no added biometric-freshness requirement.
Personal/private reads (calendar, email, private notes, personal reminders)
require voice verification of the current utterance *plus* fresh T2 visual
evidence no more than 1 s old — a T1 carry-forward match alone is
insufficient. Consequential actions (sending email, modifying calendar,
deleting resources) still need appropriate biometric trust *plus* the
existing deterministic authorization policy plus authenticated-text
confirmation where required; bulk/destructive restrictions are unchanged.

### Continuous output enforcement

Trust applies to output as well as input. Before sensitive TTS begins,
recompute trust, verify evidence freshness, and confirm the requested
content is still permitted. During sensitive playback, continuously refresh
owner-presence evidence; if T2 is lost, stop room playback with an audible
stop tail target of **≤1 second**. Do not resume the old private response
automatically if trust later returns — the user can request it again.
Harmless public speech does not need to stop merely because T2 expires.

### Follow-up and session expiry

Biometric expiry and conversation expiry are separate concepts. When the
[Phase 24g](phase-24g.md) follow-up conversation expires (10 s), T1/T2 are
discarded and the system returns to wake monitoring; no biometric trust
carries over into the next "Hey Reachy" interaction, matching the
[wake-started sessions addendum](adr/0023-robot-voice-conversation.md#addendum-wake-started-sessions-2026-09-27-phase-24g).

### Sensor/service failure and reboot

Unavailable sensors reduce the maximum reachable trust rather than blocking
everything: camera unavailable caps trust at T1; speaker verifier
unavailable caps trust at T0; both unavailable caps trust at T0
(public-only). Recovery of a service does not restore previous trust —
fresh evidence must be collected. T1 and T2 must be discarded (effective
trust = T0 until fresh evidence) after: Reachy reboot; embodiment restart;
recognition-service restart; relevant hub reconnect; microphone
replacement; camera replacement; active recognition model change;
calibration-profile change; owner-enrollment replacement; evidence
timestamp/clock anomaly; security-relevant processing-path change.

### Multiple-person behaviour

A visible owner does not authorize everyone nearby. If another person
speaks while the owner is visible (owner face visible + speaker mismatch),
that utterance is T0. If multiple faces or speakers make attribution
ambiguous, the system downgrades rather than guesses; the first
implementation prefers false rejection over incorrectly associating speech
with the owner.

## Architecture and implementation sequence

1. **Threat-model and boundary ADR.** Before implementation, document the
   trusted camera/microphone path, inference placement, per-modality
   evidence contracts, the trust-computation rules above, owner/channel
   mapping, playback enforcement and changes to currently trusted-network
   API access. Preserve service boundaries: perception is robot-side sensor
   processing, hub admits channel input, core authorizes tools, embodiment
   enforces actual room playback.
2. **Owner enrollment and recovery.** Add Settings → Owner recognition to
   the existing GUI. Require owner login plus fresh password reauthentication
   and CSRF protection to enroll, replace or delete templates, for both the
   voice and face profiles. Capture live samples over several poses/lighting
   conditions and several utterances/speaking styles, with quality checks.
   No automatic learning from passers-by or unauthenticated first-face/first-
   voice enrollment. Offer re-enrollment and private text recovery;
   disabling either profile caps the trust it would have supplied (voice
   disabled → max T0; face disabled → max T1).
3. **Local perception.** Evaluate face verification, liveness and speaker
   verification on actual hardware before selecting dependencies. Voice
   verification (25a) can grant T1 on its own; visual verification (25b)
   requires live/audio association, not just a nearby face, to grant T2. A
   wake word, nearby face, or STT confidence alone is insufficient for
   either level. Reject overlap by default.
4. **Short-lived evidence and the trust computation.** Define shared
   contracts per modality — owner ID, sensor/robot IDs, capture time,
   sequence/nonce, model/calibration version, confidence, quality/liveness
   status, expiry and utterance binding — and a small trust-computation
   module implementing the T0–T3 rule and the expiry/downgrade rules above.
   Validate source authentication, freshness, replay protection and owner
   mapping at service boundaries. Accept evidence only from provisioned
   perception services, never browser-submitted scores. Reset trust on
   reboot/reconnect; use monotonic local expiry so clock changes cannot
   extend permission.
5. **Input gate.** Gate STT and protected-request handling on the current
   trust level versus request sensitivity from the table above. A short,
   bounded, volatile audio buffer may be used locally for speaker/liveness
   analysis; it is not permission to transcribe/upload unknown speech.
   Recheck the whole utterance before admitting a transcript, and discard
   buffered audio, transcripts and late inference results when attribution
   fails or trust is insufficient for the request. Preserve
   `InputModality.VOICE` end to end, regardless of trust level.
6. **Output gate.** Check trust before TTS dispatch and immediately before
   playback, then continuously during playback. Stop and discard queued
   audio on loss of the trust level the response required; do not
   automatically resume an old private reply when trust returns. Implement
   cancellable playback and bounded audio buffers in the real backend.
   Cover all speaker paths: conversation, briefing/reminders, greetings with
   speech, remote speak and `/audio/play`. No direct endpoint or offline
   fallback phrase may bypass the gate. Local silent motion/presence
   continues without recognition or homelab services.
7. **Authenticated channels and tools (T3).** Audit `/messages`,
   `/voice/turn`, WebRTC signaling, Telegram sender/chat mappings, core
   direct routes and Caddy debug proxies. Bind principals server-side;
   arbitrary caller-supplied modality/user IDs are not approval. Require
   owner authentication for user calls and scoped service authentication
   internally. Preserve bearer clients using explicit privileges, not a
   universal impersonation shortcut. Private authenticated phone/browser
   calls need no room-camera presence if output stays on the private
   device; they remain VOICE and cannot confirm writes on trust alone.
   Room-speaker output from remote control still requires local owner
   presence at the trust level the response requires.
8. **GUI and diagnostics.** Show the current trust level (T0–T3) and which
   evidence produced it, per-modality evidence age, permitted input/output
   at that level, and plain-language denial reason. Show calibrated
   confidence with its limitations. Provide silent status and private
   authenticated text fallback instead of speaking an error to an unknown
   person. No guest override for personal conversations.

Owner presence does not prove the room is private. Known or unknown
bystanders do not authorize disclosure; detected additional people should
force personal content to a private channel. Office privacy remains in force
even at T2, since people outside the camera may still hear. Ordinary
non-conversational emergency stop/mute controls may always reduce activity;
they cannot expose data or authorize work actions.

## Web portal calibration and accuracy testing

Settings → Owner recognition is the complete owner-facing workflow:
**Enroll → Calibrate → Test accuracy → Review → Activate**, run separately
for the voice (T1) and face (T2) profiles. No shell commands or manually
edited threshold files are required. Use the existing authenticated portal
at `/ui/` and `/hub/ui/`, with desktop/mobile layouts. The portal controls
capture and displays results; trusted local services compute scores and
enforce activation rules. Browser-supplied scores cannot grant access.

### Guided calibration

- Show the selected robot, camera and microphone, live preview, sensor
  health, lighting/face quality and capture progress. Calibration must use
  the actual deployed Reachy sensors and processing path. A laptop
  webcam/microphone test is explicitly a separate diagnostic and cannot
  validate the robot profile.
- Guide the owner through poses, distance, lighting, glasses if applicable,
  and spoken samples. Explain each step, permit retry/cancel, and flag poor
  quality without silently accepting it. Collect consenting non-owner trials
  with anonymous labels; no non-owner identity enrollment is needed.
- Separate enrollment, calibration and held-out test sessions in the portal.
  Fit a candidate calibration without changing the active profile. Once a
  test set has informed tuning, retire it as a final holdout and collect new
  trials. Repeated video frames must not inflate the displayed sample count.
- Keep samples transient by default. Explain any optional encrypted
  diagnostic retention, its expiry and deletion before capture.
  Cancel/logout/timeout stops collection and clears transient samples; no
  unfinished profile can activate. Store versioned calibration parameters
  and aggregate results without requiring retention of raw face/audio
  recordings.

### Test accuracy

Provide a repeatable **Test accuracy** action for either the active or a
candidate profile (voice or face), with a clearly visible profile/version
and test-only mode. Offer an immediate live check and a guided evaluation
covering: owner present, owner absent, a consenting non-owner, owner
leaving, owner visible while someone else speaks, overlap, and replay
scenarios, at both the T1 (voice-only) and T2 (multimodal) checkpoints. The
owner labels expected presence/speaker before each trial; the recognizer
must not label its own ground truth. Missing scenarios remain untested, not
assumed successful.

Show, live: current trust level with valid confidence, liveness/quality and
evidence age per modality, speaker attribution, and separate "Would grant
T1" / "Would grant T2" / "Would speak" decisions with reasons. These are
dry-run decisions: diagnostic audio and transcripts never reach
conversations, memory, mail/calendar tools or approval handlers. A separate
explicit playback test uses a harmless fixed phrase and retains every trust
gate, so the owner can measure physical mute latency without exposing
personal content. Test mode cannot unlock production speech or admit guest
commands.

The results page includes:

- Counts of correct owner accepts, owner rejects, correct non-owner rejects
  and false accepts per trust level, with denominators and rates; no
  misleading single "accuracy" percentage for an imbalanced sample.
- Speaker-verification, face-presence, association and final trust/gate
  results separately, plus spoof-test outcomes and p50/p95
  acquisition/downgrade/mute latency.
- Coverage by lighting/distance/noise, independent session/participant
  counts, uncertainty and "insufficient evidence" where appropriate. Show
  calibration reliability on held-out labelled trials separately from match
  accuracy; never present a percentage as validated solely because matching
  was accurate.
- Side-by-side active/candidate results, failed acceptance criteria and a
  redacted downloadable report (JSON/CSV), without biometric media or
  secrets.

### Review and activation

The owner can retry calibration, discard a candidate, or activate one after
review. Activation requires fresh owner reauthentication, CSRF protection
and server-side validation of the applicable Phase 25 acceptance gates
below. A quick successful selfie or single-utterance check is not
sufficient. Incomplete/failed evidence keeps the candidate diagnostic-only;
show exactly which tests remain.

Keep the T1/T2 evidence and expiry rules above, and the sensitivity mapping
they gate, immutable from ordinary portal controls. More restrictive
sensitivity settings require a fresh test run; do not provide an unsafe
slider to trade false accepts for convenience. Activate atomically,
version/audit changes, invalidate old recognition leases, and reacquire live
evidence. Interrupted activation keeps the prior profile. Rollback is
available only to a previously validated profile compatible with the
current model/sensors. A changed model, camera/microphone or processing
path invalidates affected calibration and requires retesting before the
trust level it supports is re-enabled. If there is no valid active voice
profile, remain capped at T0 with text access; if there is no valid active
face profile, remain capped at T1.

## Deployment, data and timing

Prefer local inference; no raw faces, voiceprints or room audio sent to a
cloud LLM or stored in conversation memory. Encrypt enrolled templates,
restrict access, provide deletion/key rotation and document backup
retention. Discard raw enrollment captures after template creation unless
the owner explicitly opts into a bounded diagnostic dataset. Audit decisions
and model versions without recording bystander identities or raw
biometrics.

The original Jetson Nano is a candidate for perception only after Phase 22's
runtime/memory/thermal checks. If it cannot sustain the timing budgets
below, choose a supported local host or cap the reachable trust level; do
not weaken the checks themselves. Nano/perception failure may cap trust but
must not stop independent Reachy idle/fallback motion — this deliberately
degrades voice availability safely while retaining ADR 0004's embodiment
availability guarantee.

Initial implementation constants, to validate on hardware and change only
from recorded evidence, never convenience alone:

```text
VOICE_TRUST_TTL_SECONDS            = 10   # T1 carry-forward after last verified utterance
VISUAL_TRUST_TTL_SECONDS           = 1    # T2 evidence freshness
VISUAL_INITIAL_OBSERVATIONS        = 3    # to first establish T2
VISUAL_INITIAL_SPAN_MS             = 500  # minimum span for those observations
SENSITIVE_REQUEST_REQUIRE_CURRENT_VOICE = true
SENSITIVE_PLAYBACK_MAX_OWNER_LOSS_MS    = 1000  # audible stop tail budget
FOLLOW_UP_TIMEOUT_SECONDS          = 10   # matches Phase 24g's follow-up window
```

Any detected disqualifying observation locks the affected trust level
immediately, with no lower-threshold grace period. Test the actual speaker
tail, not just a cancelled HTTP request, and bound/report unavoidable audio
exposure during that interval. A frozen camera cannot renew T2 evidence by
repeatedly scoring the same frame.

## Acceptance and release gate

Phase 25 acceptance measures false accepts, false rejects, owner-acquisition
latency, trust-elevation latency, trust-downgrade latency, visual-loss
detection, speaker-change detection, replay/spoof resistance, resource
cost and QoL impact — the constants above are operating hypotheses, not
permanent policy, and change only from this recorded evidence.

| Check | Required result |
|---|---|
| Trust computation | T0/T1/T2/T3 boundaries (including 0.5999/0.6000-style edges per modality), missing/NaN/out-of-range and stale evidence all resolve to the lower level; a level is granted only when every gate for it passes; tested without real-time sleeps |
| Portal workflow | Owner completes enrollment, calibration, held-out accuracy testing, report review and activation for both voice and face profiles, entirely in the web portal on direct/proxied mounts and desktop/mobile; correct robot sensors and profile versions are visible |
| Portal safeguards | Test data cannot invoke tools or unlock production trust; forged results/labels alone cannot bypass trusted capture or activation checks; cancel/logout/failed activation preserve valid state, and incompatible rollback is blocked |
| Accuracy reporting | Known labelled fixtures yield correct confusion counts/rates and latency summaries per trust level; independent trial counts, untested scenarios, calibration reliability and insufficient evidence are reported honestly; exports contain no raw biometrics |
| T1 owner usability | At least 100 held-out live owner utterances over three sessions and representative conditions; >=95% reach T1 within the QoL latency target; report exclusions and false rejects |
| T2 owner usability | At least 100 held-out live owner trials (voice + visual) over three sessions; >=95% reach T2 within its documented acquisition budget once DoA/orientation completes; report exclusions and false rejects |
| Unknown-owner rejection | At least 300 independent non-owner attempts spanning at least 10 consenting participants and varied conditions, zero unauthorized T1/T2 grants; report participant clustering and a justified uncertainty estimate, not a claimed universal error rate |
| Spoof/attribution | At least 20 trials each for printed face, displayed face video, owner-audio replay, synthesized audio, owner visible while somebody else speaks, and overlapping speech; zero unauthorized T1/T2 grants; unavailable attack tests are BLOCKED |
| Downgrade and expiry | T2→T1, T2→T0 and T1→T0 all measured for latency against the TTLs above; owner leaves before capture, during STT, during inference and during playback; late results are dropped, no new audio starts, existing sensitive playback stops within the 1 s budget |
| Failure/reboot | Cover camera disconnect/freeze (caps at T1), speaker-verifier outage (caps at T0), both outages (T0/public-only), darkness, stale/out-of-order/fabricated evidence, service/Nano outage, reboot, time changes and model mismatch; each caps or resets trust rather than granting it |
| Multi-person attribution | Owner visible with a second person speaking; multiple faces/speakers with ambiguous attribution; both must resolve to T0 for the ambiguous utterance rather than guessing |
| Path coverage | Exercise real speaker output through every route, including remote speak and proactive delivery, at each trust level's sensitivity boundary; no backend/API bypass; authenticated private text (T3) remains available |
| Malicious actions | Unknown-, T1- and T2-trust voice requests to delete mail, send mail or create 100 events cause zero provider writes; direct forged TEXT/user-ID/trust-level requests also fail; test repeated single-action bulk evasion and pending-approval replay |
| Privacy and enrollment | No unapproved biometric persistence/cloud upload; enrollment replacement requires owner reauthentication; template deletion caps the corresponding trust level; shared-room/Office behaviour retains private routing at T2 |
| Full integration | Python/Ruff/browser checks pass, with real hardware voice+face tests and an 8-hour mixed-use run; existing Phase 22/23 startup, outage, privacy and read-only Google tests still pass |

Use safe fixtures and instrumented provider adapters to verify destructive
attempts; never test deletion or event spam on real production accounts.
Record hardware/model/calibration versions, thresholds, trial counts, false
accepts/rejects, p50/p95 timing, resource use and limitations in
`docs/verification/phase-25-<date>.md`. Keep biometric datasets outside git.
Small attack suites demonstrate only those attacks; do not claim immunity to
deepfakes or statistically strong security from zero observed failures.

Phase 25 is complete only when every required gate passes on the deployed
hardware with no unauthorized trust grant, audible disclosure or action in
the acceptance suite. If attribution/liveness or hardware throughput is
inadequate for T2, ship T0/T1 plus private text/explicit authenticated (T3)
interaction as a limited mode and leave T2 marked blocked. No
implementation, enrollment or live recognition testing is performed by this
planning change.
