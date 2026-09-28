# ADR 0024: Owner recognition trust boundary

- Status: Accepted for Phase 25.0 (contracts and trust engine only); no
  biometric model integration, enrollment, or production gating exists yet.
- Date: 2026-09-28

## Context

[Phase 25](../phase-25.md) adds owner voice/face verification so Reachy can
tell its owner apart from anyone else in the room, without either turning
into a general biometric identification system or letting a recognition
model authorize anything itself. Before any speaker/face model is
integrated, the phase's own sequence
([Implementation sequence](../phase-25.md#implementation-sequence)) requires
the evidence contracts and the deterministic trust engine to exist first, so
expiry/downgrade behaviour is fully unit-tested against fakes before a real
model's noise is introduced. This ADR records the trust boundary those
contracts assume, so later sub-phases (25a voice, 25b visual) extend it
rather than reinterpreting it per change.

Existing boundaries this phase must fit inside, not replace:
[ADR 0001](0001-service-boundaries.md) (service ownership),
[ADR 0006](0006-response-routing.md) (response routing/privacy override),
[ADR 0011](0011-destructive-action-consent.md) (text-only destructive
confirmation, LLM has no override authority), and
[ADR 0023](0023-robot-voice-conversation.md) (the robot voice transport and
wake-started sessions this phase attaches to).

## Decision

**Evidence, trust and authorization are three distinct concepts, and no
code may collapse them:**

```text
identity evidence  →  effective trust  →  request / action authorization
```

- **Identity evidence** (`shared/models/trust.py`: `SpeakerEvidence`,
  `VisualEvidence`) is produced by a recognition model. It carries a score,
  quality/liveness/spoof fields, an owner/session/turn binding, and a
  monotonic expiry. It is never itself an authorization decision, and it is
  never persisted as session authorization — it is transient process state
  attached to the existing `VoiceSession`
  (`services/reachy-hub/src/reachy_hub/robot_voice.py`), discarded with the
  session and on reboot/reconnect.
- **Effective trust** (`reachy_hub/trust.py`'s `effective_trust`, returning
  `shared.models.trust.TrustLevel` T0–T3) is a deterministic function of
  current evidence only: fresh/stale, accepted/rejected, quality, spoof/
  liveness result, same owner, same session, association. It has no
  knowledge of which model produced the evidence (no SpeechBrain/ECAPA/
  ArcFace/SFace/MiniFASNet/Whisper/LLM awareness), so it stays auditable and
  swappable independently of model choice. It is recomputed at every
  decision point, never cached or read from a stored flag.
- **Request/action authorization** (`reachy_hub/request_sensitivity.py`'s
  `authorize_request`, plus Companion Core's existing action policy) weighs
  `TrustLevel` against `RequestSensitivity` and `InteractionMode`. Only this
  stage produces an allow/deny-shaped decision. `InteractionMode.TRUSTED`
  changes response routing only; it has no path into trust or authorization.

**Ownership stays split across existing service boundaries** ([ADR
0001](0001-service-boundaries.md)):

- `reachy-hub` owns T0–T3 computation, evidence freshness, request
  sensitivity classification, and whether an utterance may enter Companion
  Core or a response may be spoken.
- `companion-core` remains the sole owner of resource/action authorization —
  calendar/email/memory/tool access, consequential-action policy,
  confirmation requirements, bulk-action rejection. Biometric evidence
  establishes who appears to be asking; it never replaces or shortcuts
  Core's action authorization, and it carries no authority to bypass ADR
  0011's text-only destructive confirmation.
- `reachy-embodiment` remains the final physical enforcement layer for
  stopping audio when the hub revokes playback permission, following the
  existing open-palm-stop/motion-ownership pattern.

**No component may self-authorize.** A recognition library never decides
whether a request is allowed; the LLM never raises trust or bypasses this
policy, matching the project's existing rule that the LLM has no authority
over action gates (AGENTS.md).

**Freshness uses monotonic time only.** Evidence expiry is computed from
monotonic clocks (`captured_monotonic`/`expires_monotonic`), never wall
clock, because the Nano's RTC/pre-NTP timestamp issues (HANDOVER.md) must
not be able to extend or fabricate evidence freshness. Wall-clock timestamps
may still be recorded for diagnostics.

**Controlled transient STT boundary is unchanged by this ADR**, and is
recorded here only because Phase 25.0's classifier depends on it: bounded,
transient STT of unverified ambient audio for admission/sensitivity
classification is permitted (already established by
[Phase 24g](../phase-24g.md)); the resulting transcript is not a
conversation turn until `authorize_request` allows it, and it must not reach
Core, durable history, memory, RAG, calendar, email, tasks, web search
carrying private context, or consequential-action handlers before that.

**Scope of this ADR.** It covers the contracts and trust engine
(`shared/models/trust.py`, `reachy_hub/trust.py`,
`reachy_hub/request_sensitivity.py`) landing in Phase 25.0. It does not
itself approve any biometric model, the enrollment portal, camera/
microphone perception code, or production gating — those are separately
sequenced in [Phase 25's implementation sequence](../phase-25.md#implementation-sequence)
and require their own acceptance evidence before deployment.

## Consequences

- Later sub-phases (25a speaker verification, 25b face verification) attach
  real evidence producers behind these contracts; they must not introduce a
  second trust/authorization path or let a model output flow directly into
  an allow/deny decision.
- Because trust is never cached, every call site that needs a trust decision
  must recompute it explicitly at the point of use; a stored `TrustLevel`
  read later in the same request is stale by construction if any time has
  passed or evidence could have changed.
- Testing evidence expiry/downgrade requires only fakes (no model, no
  hardware) — see `services/reachy-hub/tests/test_trust.py` and
  `test_request_sensitivity.py` — so this boundary is exercised before any
  Nano/homelab perception work begins.
