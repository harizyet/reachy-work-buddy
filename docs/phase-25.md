# Phase 25 — tiered owner verification and progressive trust

Status: **in progress**. The [phase ledger](plan.md#6-implementation-roadmap)
owns delivery status; the [implementation sequence](#implementation-sequence)
distinguishes existing wiring from planned model integration. See the
[foundation/portal verification](verification/phase-25-foundation-2026-09-28.md)
and [speaker pipeline smoke test](verification/phase-25a1-voice-benchmark-2026-09-28.md)
for evidence and limitations. No real biometric model, operational template,
calibration or enabled production sensitivity gate exists yet.

This phase **follows [Phase 24g](phase-24g.md)**
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
gate) in favour of the progressive-trust model below, so that harmless
requests do not wait on the slowest sensor: identity evidence is continuously
derived per modality, combined into a trust level, and checked against the
sensitivity of the specific request, instead of gating all room speech behind
one visual threshold. The retired design's engineering rigour — calibrated
(not raw) confidence, adversarial and reboot/failure testing, an owner-facing
calibration portal, no LLM authority over identity, and preserved
destructive-action policy — carries forward unchanged; only the single-gate
shape is replaced. Extend the existing robot-voice path rather than building
a separate biometric-session subsystem (see
[Existing implementation to reuse](#existing-implementation-to-reuse)).

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

**Guiding principles:** respond at the lowest safe trust level, while
stronger verification continues asynchronously; trust may rise only from
fresh qualifying evidence, but it may fall immediately whenever that evidence
becomes stale, contradictory or unavailable. Equally: **recognition models
produce evidence, not authorization.** Recognition libraries never decide
whether a request is allowed — that split is architectural, not incidental
(see [Authorization ownership](#authorization-ownership)).

### Phase 25a — owner voice verification

Determines whether the current utterance matches the enrolled owner, and
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

## Existing implementation to reuse

The project already has the right lifecycle and ownership boundaries for
this phase to extend rather than duplicate.

The current robot voice path:

```text
reachy-embodiment                    reachy-hub                       companion-core
microphone, VAD,           →         RobotVoiceManager,       →       reasoning, memory,
WakeMonitor,                         wake admission, STT/TTS,         RAG, calendar/email/
VoiceConversation                    session mgmt, response           tasks/tools
                                      routing
```

`RobotVoiceManager` (`services/reachy-hub/src/reachy_hub/robot_voice.py`)
and its `VoiceSession`/`VoiceLimits` (`shared/models/robot_voice.py`) remain
the canonical owner of ambient Reachy voice sessions. Phase 25 attaches
trust/evidence state to that existing session rather than creating a second
biometric-session manager (see
[Integration into `RobotVoiceManager`](#integration-into-robotvoicemanager)).

[Phase 24g](phase-24g.md) already provides primitives this phase reuses
directly: persistent wake arm; robot credential and connection-generation
fencing; short robot-side audio buffers; local wake-word inference; bounded
utterance capture; wake candidate upload; transient in-memory STT;
deterministic relevance admission; the wake-started `VoiceSession`;
follow-up timeout; session expiry; rejected-candidate isolation; the
camera-upload precedent already established by open-palm stop; and
robot-side local state/motion integration.

## Progressive trust levels

Trust is computed from evidence, never stored as a persisted flag:

```python
def effective_trust(
    speaker: SpeakerEvidence | None,
    visual: VisualEvidence | None,
    authenticated_channel: bool,
    now: float,
) -> TrustLevel:
    if authenticated_channel:
        return TrustLevel.T3
    if (
        speaker and speaker.fresh(now) and speaker.accepted
        and visual and visual.fresh(now) and visual.accepted
        and speaker.owner_id == visual.owner_id
        and speaker.voice_session_id == visual.voice_session_id
        # association (DoA-to-face consistency) valid
    ):
        return TrustLevel.T2
    if speaker and speaker.fresh(now) and speaker.accepted:
        return TrustLevel.T1
    return TrustLevel.T0
```

The trust engine understands only evidence fields — fresh/stale,
accepted/rejected, same owner, same session, quality valid, spoof/liveness
result, association consistency — and nothing about which model produced
them (no SpeechBrain, ECAPA, ArcFace, SFace, MiniFASNet, Whisper or LLM
awareness). This keeps trust computation auditable and swappable
independently of model choice.

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

### Trust, evidence and authorization are three distinct concepts

```text
identity evidence  →  effective trust  →  request / action authorization
```

Do not collapse these into one boolean. A recognition result such as
`speaker_similarity = 0.82` must never directly become `authorized = true`
— it becomes one field of `SpeakerEvidence`, which the trust engine turns
into a `TrustLevel`, which the request authorizer then weighs against
`RequestSensitivity` and the existing action policy.

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
for example, answering "What time is it?" on a T1 voice match while STT and
speaker verification for that utterance run concurrently
(`asyncio.gather`) and DoA orientation plus T2 face/liveness verification
continue in parallel, so that a following "What's my next appointment?" can
be answered immediately if fresh T2 evidence has already landed. If face
verification stays unavailable, the session simply stays capped at T1:
public interaction remains usable, and personal requests fall back to
`REQUIRE_VERIFICATION` or a private-channel route rather than blocking the
whole conversation.

## Authorization ownership

Authorization is deliberately split across the existing service boundaries
([ADR 0001](adr/0001-service-boundaries.md)); Phase 25 must not collapse it
into one component.

- **`reachy-hub` — interaction authorization.** Owns T0–T3 computation,
  biometric-evidence freshness, request sensitivity, whether an ambient
  utterance may enter Companion Core, whether a response may be spoken
  through Reachy, trust downgrade/expiry, and current voice/session
  association. New modules: `reachy_hub/trust.py`,
  `reachy_hub/request_sensitivity.py`, `reachy_hub/speaker/`,
  `reachy_hub/face/`, `reachy_hub/recognition_store.py` (see
  [Proposed code layout](#proposed-code-layout)).
- **`companion-core` — resource/action authorization.** Remains responsible
  for calendar/email/memory/tool access, consequential-action policy,
  destructive-action restrictions, confirmation requirements, bulk-action
  rejection and text-only confirmation. Biometric evidence establishes who
  appears to be asking; it never replaces existing action authorization.
  Example: at T2, "Send the email" is admitted to Core because the owner is
  verified, but sending is still consequential — voice cannot confirm it,
  so Core still requires authenticated text confirmation.
- **`reachy-embodiment` — physical enforcement.** Remains the final
  physical enforcement layer: when the hub revokes sensitive-playback
  permission, embodiment stops audio; when session generation changes,
  stale playback cannot resume; when trust/session evidence disappears, no
  stale private output continues. This follows the same pattern already
  used by open-palm stop and motion ownership.

## Controlled transient STT

The pre-24g intuition that "unknown speech must never reach STT" is
incompatible with the quality-of-life goal above, because the system must
understand what was asked before it can know whether the request is public
or private. Phase 25 keeps a narrower rule instead:

> Unverified ambient audio may undergo bounded, transient local/homelab STT
> solely for wake/request admission and sensitivity classification. The
> resulting transcript is not yet a conversation turn.

This is consistent with [Phase 24g](phase-24g.md), which already
transcribes admitted wake candidates in hub memory for relevance only,
without creating a durable conversation turn. Phase 25 reuses that same
transient boundary for `RequestSensitivity` classification, and extends it
so that, before trust/sensitivity authorization completes, the transcript
must not reach: Companion Core; durable conversation history; memory; RAG;
calendar; email; tasks; web search carrying private context; or
consequential-action handlers. A short, bounded, volatile audio buffer may
additionally be used locally for speaker/liveness analysis; that raw-audio
buffer is separate from the transcript and is never itself a transcription
or upload of unknown speech beyond what admission already allows.

### Request sensitivity classification

`AgentResponse.privacy` (`shared/models/response.py`) already classifies
*output*. Phase 25 adds a pre-Core *input* sensitivity classifier:

```python
class RequestSensitivity(StrEnum):
    PUBLIC = "public"
    PERSONAL = "personal"
    CONSEQUENTIAL = "consequential"
    UNKNOWN = "unknown"
```

The table below describes target categories, not the coverage of today's
regex-only implementation. For example, "Why is the sky blue?" and
"Explain Kubernetes" currently return `UNKNOWN`.

| Request | Sensitivity |
|---|---|
| "What time is it?" / "What's the weather?" / "How tall is Mount Everest?" | PUBLIC |
| "What's my next appointment?" / "Read my latest email." / "What's in my private notes?" | PERSONAL |
| "Draft an email to Alice." | PERSONAL / CONSEQUENTIAL-preparation |
| "Send this email." / "Delete my email." | CONSEQUENTIAL |
| Ambiguous request | UNKNOWN |

Classification must resolve deterministically:

```text
transient transcript → deterministic high-confidence rules → obvious?
  yes → use it
  no  → small local sensitivity classifier proposes one enum value
        → deterministic validation/policy resolves
        → ambiguous, invalid, unavailable or timed out? → UNKNOWN
```

The second stage is a required 25a.4 deliverable before production gate
enablement, not optional polish or an indefinitely growing regex list.
Prefer a dedicated small local classifier over the main conversational LLM;
its structured output contains only `PUBLIC`, `PERSONAL`, `CONSEQUENTIAL`
or `UNKNOWN`. It receives bounded transient input, without tools, retrieval,
cloud forwarding or durable transcript storage. Preserve deterministic
consequence/privacy precedence; model output cannot downgrade a rule's
sensitive result, set trust or authorize a request. The deterministic
`RequestAuthorizer` remains the authority, per
[ADR 0024](adr/0024-owner-recognition-trust.md).

`UNKNOWN` returns `REQUIRE_VERIFICATION` at **every trust level**, including
T2/T3. Better biometrics cannot resolve classification ambiguity. Invalid
output, model failure and uncertainty must remain `UNKNOWN`; do not default
them to `PUBLIC`. Evaluate ordinary general questions, personal requests,
action requests, mixed requests and adversarial phrasing on held-out data,
reporting confusion counts, sensitive-to-public errors, unknown rates and
latency alongside concurrent STT/speaker inference on the actual homelab.
Agree acceptance thresholds before evaluating that held-out set.

### Request authorizer

A deterministic hub-side component turns `(sensitivity, trust,
interaction_mode)` into a decision:

```python
class InteractionDecision(StrEnum):
    ALLOW = "allow"
    WITHHOLD = "withhold"
    PRIVATE_ROUTE = "private_route"
    REQUIRE_VERIFICATION = "require_verification"
    DENY = "deny"


def authorize_request(
    sensitivity: RequestSensitivity,
    trust: TrustLevel,
    interaction_mode: InteractionMode,
) -> InteractionDecision: ...
```

Examples: `PUBLIC + T0 → ALLOW`; `PERSONAL + T1 → REQUIRE_VERIFICATION` or
`PRIVATE_ROUTE`; `PERSONAL + T2 → ALLOW`; `CONSEQUENTIAL + T2 → ALLOW`, but
only as far as Core's existing action-policy stage, which still applies its
own confirmation requirements. `Trusted` interaction mode ([response
policy](reference/services.md)) does not bypass identity or action policy —
it changes response routing, not authorization.

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
evaluation sessions; neighbouring frames from the same clip or video are not
independent trials. Confidence is conditional on the evaluation conditions,
not a guarantee against a new attacker.

Required threat scenarios:

- **Voice:** unknown speaker; owner absent; recorded owner speech; replay
  through a speaker; synthetic/cloned owner voice; overlapping speech;
  owner + unknown speaker; background TV/podcast; varying distance and
  orientation; noisy office conditions.
- **Face:** owner absent; unknown face; printed photograph; face displayed
  on phone/tablet; recorded owner video; frozen valid camera frame;
  darkness; poor angle; partial occlusion; glasses; owner departure.
- **Multimodal:** owner face + stranger voice; owner voice recording + no
  owner face; owner voice recording + owner photograph; owner visually
  present while another person speaks; DoA materially inconsistent with the
  visible owner; two speakers; two visible people; visual trust
  disappearing during private TTS.
- **API/security:** caller-provided fake `owner_verified=true` or trust
  level; forged user ID; stale evidence; replayed evidence nonce/sequence;
  mismatched robot/session/turn; direct calls bypassing the normal voice
  route.

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

Recommended `SpeakerEvidence` schema, in `shared/models/trust.py`:

```python
class SpeakerEvidence(BaseModel):
    owner_id: str
    robot_id: str
    voice_session_id: str
    turn: int

    captured_monotonic: float
    expires_monotonic: float

    model_version: str
    calibration_version: str

    similarity_score: float
    calibrated_confidence: float | None

    quality_ok: bool
    spoof_check: Literal["pass", "fail", "unavailable"]

    accepted: bool
```

Wall-clock timestamps may be recorded for diagnostics, but authorization
expiry uses monotonic time — the Nano's known RTC/pre-NTP timestamp issues
must not be able to extend or fabricate evidence freshness.

**Visual evidence / T2.** Require at least **3 qualifying observations
spanning at least 500 ms** before initially establishing T2. Each fresh
qualifying observation refreshes visual evidence; visual evidence expires
**1 second** after the last qualifying frame. Frozen or repeated copies of
the same frame cannot refresh trust. Qualifying observations must continue
to satisfy the owner-match threshold, liveness/presentation checks,
image-quality requirements and camera-health requirements.

Recommended `VisualEvidence` schema, also in `shared/models/trust.py`:

```python
class VisualEvidence(BaseModel):
    owner_id: str
    robot_id: str
    voice_session_id: str

    captured_monotonic: float
    expires_monotonic: float

    frame_sequence: int

    model_version: str
    calibration_version: str

    calibrated_confidence: float | None

    quality_ok: bool
    liveness_ok: bool
    frozen_frame: bool

    doa_consistent: bool | None

    accepted: bool
```

Never expose biometric embeddings/templates to browsers.

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

Trust applies to output as well as input. Recompute effective trust,
response privacy, interaction mode and the trust the response requires: (1)
before TTS begins; and (2) again immediately before playback, because trust
may have expired during Core inference, search, tool calls or TTS
generation itself. During sensitive playback, continuously refresh T2; if
T2 disappears, stop room audio with an audible stop tail target of **≤1
second**. Do not resume the old private response automatically if trust
later returns — the user can request it again. Harmless public speech does
not need to stop merely because T2 expires; it continues as long as its own
minimum trust remains satisfied.

### Follow-up and session expiry

Biometric expiry and conversation expiry are separate concepts. When the
[Phase 24g](phase-24g.md) follow-up conversation expires (10 s), T1/T2 are
discarded and the system returns to wake monitoring; no biometric trust
carries over into the next "Hey Reachy" interaction, matching the
[wake-started sessions addendum](adr/0023-robot-voice-conversation.md#addendum-wake-started-sessions-2026-09-27-phase-24g).

### Sensor/service failure and reboot

Unavailable sensors reduce the maximum reachable trust rather than blocking
everything: camera unavailable caps trust at T1 (public conversation may
continue); speaker verifier unavailable caps trust at T0 (public
conversation may still continue); both unavailable caps trust at T0
(public-only). Recovery of a service does not restore previous trust —
fresh evidence must be collected. T1 and T2 must be discarded (effective
trust = T0 until fresh evidence) after: Reachy reboot; embodiment restart;
hub restart affecting recognition state; recognition-service restart;
relevant hub reconnect; microphone replacement; camera replacement; active
recognition model change; calibration-profile change; owner-enrollment
replacement; evidence timestamp/clock anomaly; security-relevant
processing-path change.

### Multiple-person behaviour

A visible owner does not authorize everyone nearby. If another person
speaks while the owner is visible (owner face visible + speaker mismatch),
that utterance is T0 for that utterance. If multiple faces or speakers make
attribution ambiguous, the system downgrades or rejects rather than
guessing; the first implementation prefers false rejection over incorrectly
associating speech with the owner.

## Architecture and implementation sequence

1. **Threat-model and boundary ADR.** Before implementation, document the
   trusted camera/microphone path, inference placement, per-modality
   evidence contracts, the trust-computation rules above, owner/channel
   mapping, playback enforcement and changes to currently trusted-network
   API access. Preserve service boundaries: perception is robot-side sensor
   processing, hub admits channel input and computes trust, core authorizes
   tools, embodiment enforces actual room playback.
2. **Owner enrollment and recovery.** Add Settings → Owner recognition to
   the existing GUI, with separate Voice and Face sub-sections (see
   [Enrollment portal](#enrollment-portal)). Require owner login plus fresh
   password reauthentication and CSRF protection to enroll, replace or
   delete templates, for both profiles. Capture live samples over several
   poses/lighting conditions and several utterances/speaking styles, with
   quality checks; do not require the wake phrase during voice enrollment —
   wake detection and speaker identity remain independent systems. No
   automatic learning from passers-by or unauthenticated first-face/first-
   voice enrollment. Offer re-enrollment and private text recovery;
   disabling either profile caps the trust it would have supplied (voice
   disabled → max T0; face disabled → max T1).
3. **Local perception.** Evaluate face verification, liveness and speaker
   verification on actual hardware before selecting dependencies (see
   [Recommended library stack](#recommended-library-stack) and
   [Recommended dependency rollout](#recommended-dependency-rollout)). Voice
   verification (25a) can grant T1 on its own; visual verification (25b)
   requires live/audio association, not just a nearby face, to grant T2. A
   wake word, nearby face, or STT confidence alone is insufficient for
   either level. Reject overlap by default.
4. **Short-lived evidence and the trust engine.** Implement the
   `SpeakerEvidence`/`VisualEvidence` contracts and the deterministic
   `TrustEngine` (`reachy_hub/trust.py`) before any biometric model
   integration lands in production, so expiry/downgrade behaviour is fully
   unit-tested against fakes first. Validate source authentication,
   freshness, replay protection and owner mapping at service boundaries.
   Accept evidence only from provisioned perception services, never
   browser-submitted scores. Reset trust on reboot/reconnect; use monotonic
   local expiry so clock changes cannot extend permission.
5. **Input gate.** Gate the [controlled transient STT](#controlled-transient-stt)
   boundary, `RequestSensitivity` classification and `RequestAuthorizer`
   decision on the current trust level versus request sensitivity. Recheck
   the whole utterance before admitting a transcript to Core, and discard
   buffered audio, transcripts and late inference results when attribution
   fails or trust is insufficient for the request. Preserve
   `InputModality.VOICE` end to end, regardless of trust level.
6. **Output gate.** Check trust before TTS dispatch and immediately before
   playback, then continuously during playback (see
   [Continuous output enforcement](#continuous-output-enforcement)). Stop
   and discard queued audio on loss of the trust level the response
   required; do not automatically resume an old private reply when trust
   returns. Implement cancellable playback and bounded audio buffers in the
   real backend. Cover all speaker paths: conversation, briefing/reminders,
   greetings with speech, remote speak and `/audio/play`. No direct
   endpoint or offline fallback phrase may bypass the gate. Local silent
   motion/presence continues without recognition or homelab services.
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

### Integration into `RobotVoiceManager`

Do not create a second biometric session manager. Extend the existing
`VoiceSession` (`services/reachy-hub/src/reachy_hub/robot_voice.py`) with a
contained, transient trust context rather than a parallel store:

```python
@dataclass
class VoiceTrustContext:
    speaker: SpeakerEvidence | None = None
    visual: VisualEvidence | None = None


@dataclass
class VoiceSession:
    ...
    trust: VoiceTrustContext
```

Do not persist live evidence to the database as session authorization — it
is transient process state, discarded with the session and on the
reboot/reconnect events above.

### Proposed code layout

```text
shared/models/
├── trust.py                # SpeakerEvidence, VisualEvidence, TrustLevel, TrustLimits
├── robot_voice.py           # existing VoiceSession/VoiceLimits/WakeLimits
└── session.py                # existing InteractionMode/InputModality/PrivacyContext

services/reachy-hub/src/reachy_hub/
├── trust.py                  # deterministic TrustEngine
├── request_sensitivity.py     # RequestSensitivity, RequestAuthorizer
├── recognition_store.py       # encrypted template storage/access
├── robot_voice.py              # existing RobotVoiceManager/VoiceSession, extended
├── speaker/
│   ├── base.py                 # SpeakerVerifier protocol
│   ├── ecapa.py                 # SpeechBrain ECAPA-TDNN adapter
│   ├── anti_spoof.py            # AASIST adapter (benchmark first)
│   └── calibration.py
└── face/
    ├── base.py                  # FaceVerifier protocol
    ├── detector.py                # YuNet adapter
    ├── verifier.py                 # SFace adapter
    ├── liveness.py                  # MiniFASNet/Silent-Face adapter
    └── calibration.py

services/reachy-embodiment/src/reachy_embodiment/
├── wake.py                     # existing
├── voice.py                     # existing
├── motion.py                     # existing MotionController
└── sound_direction.py              # ReachyDoAProvider
```

## Recommended library stack

| Function | Recommended candidate | Initial location |
|---|---|---|
| Wake word | Existing Edge Impulse "Hey Reachy" | Robot |
| VAD | Existing Silero path | Robot |
| STT | Existing faster-whisper | Homelab |
| Speaker verification | SpeechBrain ECAPA-TDNN | Homelab |
| Voice anti-spoofing | AASIST, initially benchmark/evaluation only | Homelab |
| Sound direction | Existing Reachy DoA | Robot |
| Face detection | OpenCV YuNet | Homelab |
| Face verification | OpenCV SFace or InsightFace `buffalo_l` — benchmark both | Homelab |
| Face anti-spoof | MiniFASNet / Silent-Face candidate | Homelab |
| Trust computation | Project-owned deterministic code | Hub |
| Request authorization | Project-owned deterministic code | Hub |
| Tool/action authorization | Existing project policy | Core |
| Playback enforcement | Existing robot voice/audio controls | Embodiment |

The selected ML libraries provide evidence only, per
[Authorization ownership](#authorization-ownership) above.

**Speaker verification.** SpeechBrain ECAPA-TDNN is the initial baseline:
an established academic architecture, a mature speaker-verification
implementation with pretrained VoxCeleb recipes, Apache-2.0 framework
licensing, straightforward Python integration, and it is replaceable behind
a `SpeakerVerifier` protocol. Do not initially run ECAPA on the Jetson Nano:
audio is already uploaded for STT, so running verification in the homelab
avoids extra Nano RAM/CPU, ARM dependency complexity, and keeps a future Pi
5 migration simpler by keeping heavy perception off the robot. Run STT and
speaker verification concurrently (`asyncio.gather`) to avoid adding
sequential latency.

**Voice anti-spoofing.** AASIST is a research-grounded baseline for
synthesized/converted/replayed speech; treat it as a benchmark candidate
first, not an immediate production dependency. Speaker match and
anti-spoofing are separate evidence channels — do not treat ECAPA
similarity as proof of liveness.

**Face detection/verification.** OpenCV YuNet (lightweight, CPU-friendly,
fits existing OpenCV tooling) for detection. For verification, benchmark
OpenCV SFace against InsightFace `buffalo_l` and choose whichever gives
better owner/non-owner separation, pose robustness and latency on the real
Reachy camera — this project is personal, non-commercial and not
redistributed as a product/service, which is consistent with InsightFace's
pretrained-model non-commercial research restriction, so InsightFace is a
serious verification candidate here, not merely a benchmark-only
alternative. This is a deployment-scope judgment, not a technical one: the
same pretrained weights would need re-clearing before any commercial or
redistributed use, so document the model license regardless of which one
is chosen (see
[Model licensing requirements](#model-licensing-requirements)). Keep the
`FaceVerifier` protocol either way — not because of licensing, but so
Phase 25b stays swappable between SFace and InsightFace (or a future
model) based on actual Reachy-camera benchmark results rather than being
hard-coupled to one library.

**Face anti-spoof/liveness.** Silent-Face-Anti-Spoofing / MiniFASNet as a
passive RGB liveness candidate, kept as an independent evidence signal
(face identity match + passive presentation check + fresh frames +
audio/visual association → `VisualEvidence`). Prefer passive liveness for
ordinary use; reserve active challenges (blink, turn head, gesture) for
enrollment, calibration, suspicious/ambiguous cases, or explicit
diagnostics — do not impose an active challenge on every conversation.

### Model licensing requirements

Model selection must document, separately: source-code license,
pretrained-weight license, training-data restrictions where known,
commercial-use implications, and redistribution requirements. Do not assume
a permissive code license extends to pretrained weights — InsightFace is a
concrete example where its code is MIT but its commonly distributed
pretrained recognition packs (including `buffalo_l`) carry a non-commercial
research-use restriction separate from the code license. For this project's
current scope — personal use, non-commercial, not redistributed as a
product/service — that restriction is satisfied, so InsightFace's
pretrained packs are acceptable to use and benchmark now. That acceptance
is scope-bound, not a one-time clearance: it does not carry over
automatically if the project's use ever becomes commercial or is
redistributed, at which point the pretrained-weight license would need
re-evaluating before continuing to use it. Record the exact model pack and
license text alongside the model/version/hash so this constraint stays
visible if scope ever changes.

### Recommended dependency rollout

Do not add all biometric libraries directly to the production hub image
during exploration. Use separate benchmark environments/images first —
`speechbrain`/`torch`/`torchaudio` plus optional AASIST dependencies for
voice; `opencv-python-headless` plus YuNet, SFace, InsightFace `buffalo_l`
and MiniFASNet models for vision — then, only after benchmarking: choose
models (SFace vs. InsightFace on measured owner/non-owner separation, pose
robustness and latency); record model/version/license/hash; freeze
dependencies; integrate only the selected runtimes into deployment. This
avoids turning Phase 25 into dependency churn.

## Web portal calibration and accuracy testing

Settings → Owner recognition is the complete owner-facing workflow:
**Enroll → Calibrate → Test accuracy → Review → Activate**, run separately
for the voice (T1) and face (T2) profiles. No shell commands or manually
edited threshold files are required. Use the existing authenticated portal
at `/ui/` and `/hub/ui/`, with desktop/mobile layouts. The portal controls
capture and displays results; trusted local services compute scores and
enforce activation rules. Browser-supplied scores cannot grant access.

### Enrollment portal

The implemented portal captures an explicitly enabled **benchmark dataset**;
it does not enroll an operational identity or grant trust. See the
[operator guide](operator-guide.md#owner-recognition-benchmark-dataset) for
controls, [deployment](deployment.md#owner-recognition-benchmark-storage)
for storage configuration, and [service reference](reference/services.md#owner-recognition)
for APIs. Browser acceptance remains open in
[project state](project-state.md#implemented-but-not-fully-accepted).

The operational enrollment flow below remains planned and must follow the
[benchmark/operational data policy](phase-26.md#26d-addendum-benchmark-vs-operational-data-policy-owner-decision-2026-09-28),
using a separate derived-template store.

```text
Settings
└── Owner Recognition
    ├── Voice
    │   ├── Enrolled / Not enrolled
    │   ├── Enroll, Calibrate, Test accuracy, Replace, Delete
    ├── Face
    │   ├── Enrolled / Not enrolled
    │   ├── Enroll, Calibrate, Test accuracy, Replace, Delete
    └── Live diagnostic
        ├── Speaker result, Face result, Liveness
        ├── Evidence age, Effective T0/T1/T2, Reason
```

Enrollment changes require an authenticated owner session, fresh password
reauthentication, CSRF protection and server-side validation. Do not expose
a casual "security threshold" slider that trades false accepts for
convenience outside a fresh, evaluated test run.

Voice enrollment collects approximately 5–10 short utterances across
multiple natural sentences and more than one enrollment session, at normal
Reachy operating distance with slightly varied head orientation and
representative background noise; it does not require the wake phrase.

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
cloud LLM or stored in conversation memory, and no biometric data in LLM
prompts. Encrypt enrolled templates at rest, restrict access, provide
deletion/key rotation and document backup retention. Discard raw enrollment
captures after template creation unless the owner explicitly opts into a
bounded diagnostic dataset. Audit decisions and model versions without
recording bystander identities or raw biometrics — unknown people remain
`UNKNOWN`, not identified individuals, and this stays a single-owner
system with no bystander identity directory.

The original Jetson Nano is a candidate for perception only after Phase 22's
runtime/memory/thermal checks. If it cannot sustain the timing budgets
below, choose a supported local host or cap the reachable trust level; do
not weaken the checks themselves. Nano/perception failure may cap trust but
must not stop independent Reachy idle/fallback motion — this deliberately
degrades voice availability safely while retaining ADR 0004's embodiment
availability guarantee.

Initial implementation constants (`TrustLimits`, in `shared/models/trust.py`),
to validate on hardware and change only from recorded evidence, never
convenience alone:

```python
class TrustLimits(BaseModel):
    voice_ttl_seconds: float = 10.0        # T1 carry-forward after last verified utterance
    visual_ttl_seconds: float = 1.0        # T2 evidence freshness

    visual_initial_hits: int = 3           # qualifying observations to first establish T2
    visual_initial_span_ms: int = 500      # minimum span for those observations

    sensitive_playback_loss_ms: int = 1000  # audible stop tail budget
```

```text
FOLLOW_UP_TIMEOUT_SECONDS = 10  # matches Phase 24g's follow-up window
SENSITIVE_REQUEST_REQUIRE_CURRENT_VOICE = true
```

Any detected disqualifying observation locks the affected trust level
immediately, with no lower-threshold grace period. Test the actual speaker
tail, not just a cancelled HTTP request, and bound/report unavoidable audio
exposure during that interval. A frozen camera cannot renew T2 evidence by
repeatedly scoring the same frame.

## Implementation sequence

**Phase 25.0 — Contracts and trust engine.** Implement before any biometric
model integration: `TrustLevel`, `RequestSensitivity`, `SpeakerEvidence`,
`VisualEvidence`, `TrustLimits`, the deterministic `TrustEngine` and
`RequestAuthorizer`, unit tests for expiry/downgrade, and the boundary ADR.
No production biometric gating yet.

**Phase 25a.1 — Voice model benchmark.** Evaluate SpeechBrain ECAPA, audio
quality handling and the optional AASIST anti-spoof path against real
Reachy recordings, across owner/non-owner/replay/synthetic conditions.
Use consenting owner/non-owner recordings from the real Reachy microphone,
with noise, distance and orientation variation; browser microphone samples
alone are insufficient. Select thresholds from measured FAR/FRR rather than
the model default. Record model hashes and versions.

**Phase 25a.2 — Voice enrollment.** Implement the portal workflow, a secure
speaker-profile store, enrollment/replace/delete, calibration and held-out
accuracy testing.

**Phase 25a.3 — Robot voice integration (wiring done 2026-09-28, no real
model yet).** `reachy_hub/speaker/base.py` defines the `SpeakerVerifier`
protocol and a `NoSpeakerVerifier` default; `robot_voice.py`'s
`VoiceSession` now carries a `VoiceTrustContext` (`trust.speaker`,
`trust.visual`), and `run_turn` runs `pipeline.verify_speaker` concurrently
with `pipeline.transcribe` on the same WAV (`asyncio.gather`), including
for pretranscribed Phase 24g wake-admission turns, and never lets a
broken verifier fail the turn (it degrades to no evidence, matching the
documented speaker-verifier-outage behavior). 25a.4 consumes this evidence
when its gate is enabled. No real adapter is wired in: `NoSpeakerVerifier` is still the only
implementation, so voice trust stays at T0 everywhere until a benchmarked
model (25a.1) is actually integrated behind this protocol. 6 new unit
tests (`services/reachy-hub/tests/test_speaker_verification.py`).

**Phase 25a.4 — Input sensitivity gate (wired 2026-09-28, off by
default).** `RequestSensitivity`/`RequestAuthorizer` existed since 25.0;
this adds `classify_sensitivity()` (deterministic rules only, no
LLM-assist layer — an ordinary question that isn't one of the recognized
public phrasings comes out `UNKNOWN`, which is withheld even at T2/T3,
unlike a confidently classified personal/consequential request) and wires it
into `_answer` in `robot_voice.py`: before a transcript reaches Core, classify it, compute
`effective_trust` from the session's `VoiceTrustContext`, and
`authorize_request`; anything short of `ALLOW` withholds the turn
(`VoiceTurnOutcome.WITHHELD`) instead of calling `pipeline.converse`.
Gated behind `VOICE_SENSITIVITY_GATE_ENABLED` (default `false`) — **not
enabled anywhere**, deliberately: with no real speaker verifier (still
`NoSpeakerVerifier` everywhere) and no visual verifier at all, voice trust
remains T0, so turning this on today would withhold every
PERSONAL/CONSEQUENTIAL/UNKNOWN voice request — most everyday questions,
given the classifier's conservative rules-only stage — not just sensitive
ones. A real speaker verifier alone is insufficient: the
[second-stage classifier](#request-sensitivity-classification) must also be
implemented and accepted. Full production enablement additionally requires
25b's live visual verification and output enforcement, with their acceptance
checks. Keep the gate off until these prerequisites pass and the owner
explicitly approves enablement. Any earlier T0/T1-only limited-mode trial
needs separately scoped acceptance and must keep personal requests blocked;
it is not full production acceptance. 11 new tests
across `test_request_sensitivity.py` (classifier) and
`test_sensitivity_gate.py` (wiring).

**Phase 25a acceptance.** Run physical owner/non-owner/noise/replay/
synthetic/overlap/latency/false-accept/reject tests. Do not yet unlock
private ambient room data.

**Phase 25b.1 — DoA-guided acquisition.** Implement the Reachy DoA
abstraction (`ReachyDoAProvider` / `sound_direction.py`) and bounded
orient-to-speaker movement through `MotionController` — no raw trajectory
generation, no emotion-animation requirement.

**Phase 25b.2 — Face/liveness benchmark.** Evaluate YuNet, SFace, InsightFace
`buffalo_l` and MiniFASNet/Silent-Face on real Reachy-camera captures; choose
between SFace and InsightFace for verification based on measured
owner/non-owner separation, pose robustness and latency, not on licensing
alone. Record model licenses, hashes, latency, accuracy and spoof
performance.

**Phase 25b.3 — Visual enrollment.** Implement the face-enrollment portal:
capture, calibration, quality feedback, passive liveness checks,
replace/delete.

**Phase 25b.4 — Live T2 evidence.** Implement camera frame acquisition,
sequence/freeze detection, face detection, face verification, liveness, DoA
consistency, `VisualEvidence`, and trust elevation/downgrade.

**Phase 25b.5 — Output trust enforcement.** Add the trust check before
private TTS, the recheck immediately before playback, continuous T2 refresh
during private playback, ≤1 s stop-on-loss, and no automatic resume.

**Phase 25b acceptance.** Run owner/non-owner, multiple-people, owner-face
+ stranger-voice, replay/photo/video attack, owner-departure,
camera-loss/freeze, restart/reconnect, and mixed-use soak tests.

## Tests to implement before hardware runs

- **Trust engine unit tests:** T0 default; T1 fresh voice; T1 expiry at the
  TTL boundary; T2 requires all conditions; visual-TTL boundary; stale
  visual → T1; stale voice + stale visual → T0; spoof failure → downgrade;
  session mismatch → reject; wrong owner → reject; model/calibration
  mismatch; restart invalidation.
- **Request authorization tests:** PUBLIC+T0; PERSONAL+T0; PERSONAL+T1;
  PERSONAL+T2; CONSEQUENTIAL+T2; UNKNOWN fails upward; `Trusted`
  interaction mode does not bypass identity/action policy.
- **Voice pipeline tests:** speaker verifier + STT run in parallel;
  verifier timeout; verifier failure; transient transcript not persisted
  before authorization; denied turn never reaches Core; denied turn never
  triggers search/tool/memory.
- **Visual tests:** fresh frame sequencing; frozen frame cannot refresh;
  face missing; liveness failure; DoA disagreement; multiple faces; owner
  leaves view.
- **Output tests:** private TTS refused without T2; T2 expires before
  playback; T2 disappears during playback; stop tail bounded; public
  playback continues when visual evidence expires.

## Acceptance and release gate

Phase 25 acceptance measures false accepts, false rejects (FAR/FRR, EER
where useful), owner-acquisition latency, trust-elevation latency,
trust-downgrade latency, visual-loss detection, speaker-change detection,
replay/spoof resistance, resource cost (CPU/RAM) and QoL impact — the
constants above are operating hypotheses, not permanent policy, and change
only from this recorded evidence, never convenience alone. Do not claim
universal biometric error rates from a small private dataset.

| Check | Required result |
|---|---|
| Trust computation | T0/T1/T2/T3 boundaries (including 0.5999/0.6000-style edges per modality), missing/NaN/out-of-range and stale evidence all resolve to the lower level; a level is granted only when every gate for it passes; tested without real-time sleeps |
| Portal workflow | Owner completes enrollment, calibration, held-out accuracy testing, report review and activation for both voice and face profiles, entirely in the web portal on direct/proxied mounts and desktop/mobile; correct robot sensors and profile versions are visible |
| Portal safeguards | Test data cannot invoke tools or unlock production trust; forged results/labels alone cannot bypass trusted capture or activation checks; cancel/logout/failed activation preserve valid state, and incompatible rollback is blocked |
| Accuracy reporting | Known labelled fixtures yield correct confusion counts/rates and latency summaries per trust level; independent trial counts, untested scenarios, calibration reliability and insufficient evidence are reported honestly; exports contain no raw biometrics |
| Sensitivity classifier | Accepted second-stage classifier on held-out general/personal/consequential/mixed/adversarial requests; pre-agreed error, unknown-rate and latency thresholds met on the actual homelab; model failure/invalid output remains UNKNOWN at T0–T3; no downgrade of deterministic sensitive rules or action authorization bypass |
| T1 (25a) usability | At least 100 held-out live owner utterances over three sessions and representative conditions, from multiple independent owner sessions and consenting non-owner speakers using the real Reachy microphone path; >=95% reach T1 within the QoL latency target; report exclusions and false rejects |
| T2 (25b) usability | At least 100 held-out live owner trials (voice + visual) over three sessions; >=95% reach T2 within its documented acquisition budget once DoA/orientation completes; report exclusions and false rejects |
| Unknown-owner rejection | At least 300 independent non-owner attempts spanning at least 10 consenting participants and varied conditions, zero unauthorized T1/T2 grants; report participant clustering and a justified uncertainty estimate, not a claimed universal error rate |
| Spoof/attribution | At least 20 trials each for printed face, displayed face video, owner-audio replay, synthesized audio, owner visible while somebody else speaks, and overlapping speech; zero unauthorized T1/T2 grants; unavailable attack tests are BLOCKED |
| Downgrade and expiry | T2→T1, T2→T0 and T1→T0 all measured for latency against the TTLs above; owner leaves before capture, during STT, during inference and during playback; late results are dropped, no new audio starts, existing sensitive playback stops within the 1 s budget |
| Failure/reboot | Cover camera disconnect/freeze (caps at T1), speaker-verifier outage (caps at T0), both outages (T0/public-only), darkness, stale/out-of-order/fabricated evidence, service/Nano outage, reboot, time changes and model mismatch; each caps or resets trust rather than granting it; recovery of a service does not restore prior trust |
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

Phase 25a is separately considered done when: owner voice enrollment/
calibration works through the authenticated portal; speaker verification
runs on the real Reachy microphone path; false accept/reject metrics are
recorded from held-out tests; replay/synthetic tests are measured; T1
expiry/downgrade works; public requests proceed with low latency; personal
requests remain blocked/private-routed without T2; and no unverified/
private transcript reaches Core. Phase 25b is separately done when: Reachy
orients toward the speaker using existing DoA; face enrollment/calibration
works; visual verification and passive liveness run from the real camera;
frozen/replayed frames do not renew trust; T2 establishes and expires per
policy; owner-face + stranger-voice never authorizes the stranger;
personal/private requests require current voice plus fresh visual
evidence; private playback stops within ≤1 s of owner-evidence loss; trust
does not survive reboot/reconnect/model/profile changes; no biometric data
reaches LLM prompts or durable memory; and destructive-action behaviour is
unchanged. Phase 25 as a whole is complete only when every required gate
above also passes on the deployed hardware with no unauthorized trust
grant, audible disclosure or action in the acceptance suite. If
attribution/liveness or hardware throughput is inadequate for T2, ship
T0/T1 plus private text/explicit authenticated (T3) interaction as a
limited mode and leave T2 marked blocked. No implementation, enrollment or
live recognition testing is performed by this planning change.

## Relationship to existing policies

Phase 25 must not alter: [ADR 0011](adr/0011-destructive-action-consent.md)
text-only consequential confirmation; bulk destructive restrictions;
interaction-mode privacy behaviour; Office/Silent/DND routing; private-
channel authentication; [Phase 24g](phase-24g.md) wake/relevance semantics;
LLM authority boundaries; or the no-raw-servo-trajectory rule
([ADR 0003](adr/0003-embodiment-command-api.md)). Biometrics provide
stronger identity evidence but do not weaken any existing authorization
layer.

## Final architecture

```text
                          REACHY
┌───────────────────────────────────────────────┐
│ Wake / VAD / microphone / camera / DoA         │
│ MotionController → bounded orient-to-speaker   │
└─────────────────────┬───────────────────────────┘
                       │
                       ▼
                     HOMELAB
┌───────────────────────────────────────────────┐
│ faster-whisper                                 │
│ SpeechBrain ECAPA, optional AASIST              │
│ YuNet + SFace, passive face-liveness model      │
│                                                 │
│              ↓ evidence only                    │
│                                                 │
│                TrustEngine                       │
│                     ↓                            │
│              RequestAuthorizer                    │
│                     ↓                              │
│              RobotVoiceManager                      │
└─────────────────────┬───────────────────────────────┘
                      │ authorized request
                      ▼
                Companion Core
                      │ tool/action policy
                      ▼
                Hub output gate
                      ▼
               Reachy playback
```

The architectural rule to preserve throughout Phase 25:

> Perception models establish evidence. `reachy-hub` converts that evidence
> into conversational trust, `companion-core` authorizes data and actions,
> and `reachy-embodiment` enforces the resulting physical output decision.
> Neither an ML model nor the LLM may authorize itself.
