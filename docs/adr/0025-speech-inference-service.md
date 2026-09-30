# ADR 0025: Generalized speech inference service

- Status: Accepted as target architecture and migration plan for Phase 27;
  no `speech-service` code exists yet. Transitional implementations
  (reachy-hub's in-process conversational STT, the standalone diarization
  sidecar, and a planned standalone transcription sidecar) are explicitly
  sanctioned, not a violation of this decision.
- Date: 2026-09-30

## Context

[Phase 27](../phase-27.md) (meeting intelligence) needs long-form speech-to-text
and speaker diarization. Conversational STT already exists in
`reachy-hub` (`reachy_hub/stt.py`, `FasterWhisperSTT`), because Hub already
owned the inbound voice-turn media path when that was built (Phase 8). A
30–90 minute meeting recording is not that workload: it is asynchronous,
may need significant CPU/GPU time, model residency, queueing, retries and
long-running job state — none of which are transport concerns.

Putting meeting STT in `reachy-hub` would keep expanding a service whose
job is sessions/channels/transport/auth into an offline-inference owner; a
Hub restart could then kill an in-progress transcription for no transport
reason. Putting it in `companion-core` instead would make Core own Whisper,
audio codecs and inference runtimes — collapsing "what was said" into "what
it means for the user's work," and duplicating whatever stays in Hub for
conversational STT unless that is also moved (itself undesirable — see
Consequences). Sibling imports across services are prohibited (ADR 0001),
so `companion-core` could not shortcut this by importing
`reachy_hub.stt.FasterWhisperSTT` even as a stopgap.

[Phase 27.3](../phase-27.md#273--diarization) already deployed a real,
narrow answer to one piece of this: `deploy/homelab/diarization/`, an
OpenVINO-accelerated Nemotron-3/NeMo-Sortformer HTTP sidecar (ported from
the owner's own prior local experimentation), gated behind the
`--diarization` Compose profile. This ADR generalizes the pattern that
sidecar already follows into an explicit, permanent architectural boundary,
rather than treating it as a one-off.

## Decision

**Speech inference is a distinct homelab capability, independent of
interaction transport, work-agent cognition and embodiment:**

```text
transport ≠ speech inference
speech inference ≠ cognition
speech observation ≠ authorization
speaker cluster ≠ identity        (unchanged from phase-27.md's own principles)
transcript ≠ instruction          (unchanged from phase-27.md's own principles)
```

The target architecture introduces a generalized `speech-service`
(homelab-only, no public listener) that owns speech-to-text, speaker
diarization, and compatible future speech-inference capabilities —
speaker embeddings, overlap detection, language detection, speech-quality
estimation. It transforms audio into structured speech observations
(`TranscriptSegment`-shaped STT output, `DiarizationSegment`-shaped
speaker-cluster output) and assigns no business meaning to them.

**Ownership split:**

- `reachy-hub` keeps owning interaction/session transport: WebRTC,
  Telegram, robot voice sessions, wake/session lifecycle, channel routing,
  authentication, privacy routing. It does not become the permanent owner
  of long-form or model-heavy speech inference merely because its
  conversational STT already lives there today.
- `speech-service` owns audio normalization, STT, diarization, model
  loading/warm-up/residency, device placement (CPU/GPU/iGPU), inference
  queueing and speech-model telemetry. It never creates a `Task`, a
  `MeetingDecision`, or any other work artifact, and it never becomes a
  second durable media repository — it consumes meeting audio temporarily
  for inference and discards its own working copy; the canonical
  recording stays owned by `companion-core`'s meeting audio store
  (`MEETING_AUDIO_DIR`) per its existing retention policy
  ([phase-27.md §27.17](../phase-27.md#2717--retention)).
- `companion-core` keeps owning `MeetingJob`/`Meeting` and every
  downstream work artifact (transcript persistence, `MeetingMinutes`,
  `MeetingDecision`, `MeetingActionItem`, `MeetingOpenQuestion`, tasks,
  work memory, retrieval, LLM-based meeting analysis, provenance). It
  consumes speech observations over HTTP and decides what they mean; it
  must never import a speech-runtime implementation from `reachy-hub` or
  any other sibling service (ADR 0001 is unchanged, not superseded).
- `reachy-embodiment` is unaffected: it does not become a speech-model
  runtime.

**Companion Core depends on interfaces, not deployment names.** Its
meetings code should be designed around client abstractions (a
transcription client, a diarization client) rather than a concrete
container hostname, so that pointing those clients at a future unified
`speech-service` instead of separate sidecars is a configuration change,
not a workflow rewrite. This ADR does not mandate a specific class shape;
it only requires that `companion_core.meetings.worker`'s calls into speech
inference stay behind such a seam.

**STT and diarization are not a true inference dependency chain**, even
though `MeetingJobStatus`'s documented sequence
(`PREPROCESSING → TRANSCRIBING → DIARIZING → ALIGNING`) reads as one. Both
consume the same normalized audio and may run concurrently once both are
implemented; a future revision of `MeetingWorker` running them in parallel
and reconciling partial failure (STT failed / diarization complete, or the
reverse) as distinct, legible states is preferred over serializing them
for the sake of matching the status enum's reading order. Until both
exist, TRANSCRIBING remaining the sole blocking stage (current behavior,
unchanged by this ADR) is correct, not a bug.

**Alignment is not model inference and does not have to live in
`speech-service`.** The service may provide generic temporal-alignment
primitives; `companion-core` remains the owner of the canonical
`TranscriptSegment` artifact and its links to `Meeting`/`MeetingSpeaker`/
`MeetingDecision`/`MeetingActionItem`.

**Migration is incremental and does not gate Phase 27 functionality.**
Existing `reachy-hub` conversational STT and the deployed diarization
sidecar remain valid transitional implementations, not something this ADR
requires removing on landing. The expected path:

```text
today:        diarization sidecar (deployed) + reachy-hub conversational STT
near term:     + a standalone transcription sidecar for meetings
intermediate:  transcription + diarization sidecars, both behind client
               interfaces in companion-core
target:        speech-service (unified API/model-lifecycle/telemetry),
               reachy-hub's conversational STT migrated to it only after
               interactive-latency validation shows no regression
```

`reachy-hub`'s in-process `FasterWhisperSTT` is not touched by Phase 27's
initial meeting work and stays the conversational path until that
validated migration happens as its own separately tested change.

**Security and privacy carry over unchanged from this codebase's existing
rules, applied to the new boundary:** homelab/internal-only reachability,
authenticated service-to-service calls, bounded upload sizes, temporary
files cleaned up after processing, sanitized error responses (no
model/provider secrets returned to callers), no transcript logging at
normal log level. Biometric evidence produced here (if Phase 25 speaker
verification later moves behind this service) is still never authorization
— [ADR 0024](0024-owner-recognition-trust.md)'s
evidence/trust/authorization split is unchanged and unaffected by where
the evidence-producing model happens to run.

## Consequences

- `docs/phase-27.md`'s 27.2/27.3/27.4 implementation-sequence entries are
  revised to reflect this: 27.2 becomes long-form STT *plus* the client-
  interface groundwork for later consolidation, not STT alone; 27.3's
  "integrate" work (build, verify, and wire `MeetingWorker` to the already
  -deployed diarization sidecar) remains open; 27.4 gains the parallel-
  execution framing.
- New meeting-processing code must be written against a client
  abstraction from the start, even while only one sidecar exists behind
  it — retrofitting that seam later, after `MeetingWorker` has direct
  hostnames baked in, is exactly the rework this ADR exists to avoid.
- A future PR introducing the first transcription sidecar or the unified
  `speech-service` does not need a new ADR for the ownership question —
  this one already answers it — but should still record its own dated
  verification evidence (build, `/health`, a real recording processed)
  the same way [the diarization deployment did](../verification/phase-27-foundation-2026-09-30.md#addendum-273-diarization-service-deployment--2026-09-30).
- `reachy-hub`'s conversational STT is not scheduled for removal or
  replacement by this ADR alone; migrating it requires its own latency
  evidence and is explicitly a separate, later change per the migration
  path above.
- No component gains new authority to bypass Core's action policy or ADR
  0011's text-only destructive confirmation because it now sits behind a
  dedicated inference service — this ADR only moves *where audio becomes
  text/speaker-labels*, not who may act on the result.
