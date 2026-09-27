# Phase 24g — Wake admission and false-trigger rejection

Status: **decisions resolved, not implemented** (2026-09-27). Next in
[the roadmap](plan.md#6-implementation-roadmap), after the closed 24e/24f
phases and before [Phase 25](phase-25.md) owner recognition.

## Scope and dependencies

Add local wake-word monitoring, initially “Hey Reachy”, and bounded
admission before an ordinary robot voice session. Build on the accepted
24c–24e conversation path. Wake admission decides whether interaction is
intended; Phase 25 separately establishes owner identity and permitted room
input/output. Neither wake detection nor relevance authorizes an action.
The existing 24e prerequisites for Phase 25 remain passed or waived.
TV/ambient false wakes belong here; speaker attribution and rejecting
unauthorized speech in an already-open session remain Phase 25 work.
Keep conversational motion off until 24f's deferred rows pass. Any optional
wake acknowledgement must obey existing motion switches and acceptance gates.

## Decisions (resolved 2026-09-27)

Preserve [service ownership](adr/0001-service-boundaries.md) and
[robot voice transport](adr/0023-robot-voice-conversation.md): embodiment
owns local capture/filtering, hub owns authenticated sessions/routing, and
core retains reasoning and action gates. Spoken wake detection is distinct
from daemon resume and the `/reachy wake` command.

On 2026-09-27 the owner settled the STT boundary and wake-start authorization,
which the [wake-started sessions addendum](adr/0023-robot-voice-conversation.md#addendum-wake-started-sessions-2026-09-27-phase-24g)
records:

- **Arming:** the owner arms monitoring per robot through an authenticated
  control, and it stays armed across restarts until disabled.
- **Before Phase 25:** anyone may converse while armed; every existing
  speaker, privacy and consent gate still applies.
- **STT boundary:** candidates that pass the robot's local acoustic gates
  are transcribed in hub memory for relevance only, through a dedicated
  endpoint. Rejected audio and transcripts never reach core, tools, the owner
  panel, logs or storage. Ordinary session STT and cloud processing are not
  candidate filters. Phase 25's pre-STT attribution gate will run before that
  upload.

Wake events cannot bypass disarm, stop, expiry, standby, DND/meeting or
authentication.

Select the wake detector and lightweight acoustic-event filter after
measuring latency, CPU and memory on the target hardware. Define candidate
deadline, maximum buffer duration/size, speech thresholds, natural-pause
allowance and follow-up timeout before acceptance. Failure, cancellation,
disconnect and late results must discard candidates without opening a
session or replaying them later. Restore the previous permitted resting
state on rejection; intervening stop/disable takes precedence. Candidate
media and transcripts must not be retained in logs or diagnostics.

## Wake admission and false-trigger rejection

A wake-word detection is a **candidate activation**, not an automatic conversation start.

After detecting the configured wake phrase, initially **“Hey Reachy”**, `reachy-embodiment` enters a short `WAKE_CANDIDATE` state and observes the following audio before opening a normal voice session.

The admission path should reject common non-conversational sounds and accidental detections, including:

- coughing;
- sneezing;
- throat clearing;
- breathing or mouth noises;
- short vocalisations such as “uh”, “hmm” or similar fillers when no request follows;
- background noise;
- silence after the candidate wake;
- speech too short or too low-confidence to constitute a turn.

The existing VAD can establish whether meaningful voiced audio follows the wake event, but VAD alone is insufficient because coughs, sneezes and throat clearing are also voiced acoustic events. Phase 24g should therefore evaluate a lightweight local non-speech/acoustic-event rejection stage before submitting audio to the ordinary conversation pipeline.

The desired flow is:

```text
wake-word monitoring
        ↓
"Hey Reachy" candidate
        ↓
WAKE_CANDIDATE
        ↓
post-wake audio buffer
        ↓
speech / acoustic admission
        ├── no speech
        ├── cough
        ├── sneeze
        ├── throat clear
        ├── noise
        └── other non-conversational event
                 ↓
              discard
                 ↓
              IDLE

        plausible speech
                 ↓
        conversational relevance check
                 ├── clearly unrelated ambient speech
                 │        ↓
                 │      discard
                 │        ↓
                 │      IDLE
                 │
                 └── plausible addressed turn
                          ↓
                  open voice session
                          ↓
                       LISTENING
```

The post-wake buffer stays on the robot until it passes the local acoustic gates. After that, the hub may transcribe it in memory for relevance only ([decisions](#decisions-resolved-2026-09-27)). Rejected audio and transcripts must not reach Companion Core, tools, durable conversation history or memory.

A wake candidate should also expire quickly. If no suitable speech begins within a bounded interval after the wake-word detection, Reachy returns silently to its previous state. There should be no error response such as “I didn't understand” for an unconfirmed activation because that would turn false positives into audible interruptions.

### Conversational relevance

A valid human voice is not by itself sufficient to open a conversation. A false wake may occur while people nearby are already speaking.

After basic acoustic filtering, the system should determine whether the captured utterance plausibly represents speech directed toward Reachy.

This stage is an **interaction-routing decision, not authentication**. It must not grant permissions or establish speaker identity.

Possible signals include:

- whether the utterance starts immediately after the wake event;
- ASR confidence and amount of intelligible speech;
- whether the text resembles a question, request, greeting or direct conversational statement;
- whether the utterance appears to be a continuation of unrelated third-person conversation;
- later, direction-of-arrival, face/presence or Phase 25 speaker-attribution evidence where available.

The first implementation should prefer conservative rejection when activation is ambiguous. If a candidate is rejected, the temporary transcript and audio are discarded and Reachy returns to wake-word monitoring.

The general principle is:

> **False wake → silence, not conversation.**

### State behaviour

`WAKE_CANDIDATE` should be distinct from the ordinary `LISTENING` state.

Reachy may give a very small local acknowledgement of a sufficiently confident wake event, such as an antenna movement, but should avoid a large animation or audible response until the subsequent turn has been admitted. This prevents false detections from repeatedly drawing attention.

Expected state transitions are:

```text
IDLE
 ↓
WAKE_CANDIDATE
 ├── rejected → IDLE
 └── admitted → LISTENING → THINKING → SPEAKING
                                      ↓
                                follow-up conversation
                                      ↓
                                  timeout/goodbye
                                      ↓
                                     IDLE
```

If the wake candidate occurred while Reachy was in another permitted resting state, rejection should restore that original state rather than blindly forcing `IDLE`.

### Acceptance requirements

Phase 24g testing should explicitly include:

- coughs at different distances;
- sneezes;
- throat clearing;
- laughter;
- humming;
- single filler sounds;
- chair/desk impacts and other office noises;
- television and podcast speech;
- nearby conversations not addressed to Reachy;
- a false wake followed by continued unrelated conversation;
- a wake candidate followed by silence;
- genuine “Hey Reachy” followed immediately by a question;
- genuine wake followed by a natural pause before the request.

For rejected candidates, verify that:

- no user-visible conversation is created;
- no TTS response occurs;
- no tools or searches execute;
- no durable transcript or memory entry is written;
- temporary audio/transcription is discarded;
- Reachy returns to the state it occupied before the candidate wake.

The false-trigger metric should therefore measure more than wake-word false positives. Phase 24g should record both:

1. **wake candidates per hour**, and
2. **false conversations admitted per hour**.

The second metric is the more important usability measure. A somewhat imperfect wake-word detector can still produce an excellent experience if the post-wake admission gate reliably suppresses false activations.

## Verification and exit criteria

Use every scenario above as a required acceptance row. Separate fixture,
real-process and physical microphone evidence. Instrument session creation,
STT, core, TTS, tools, search and persistence to verify no downstream effects
for rejected candidates under the agreed STT boundary. Cover timeout,
failure, stop/disable, reconnect and stale-result races with controlled-time
tests. Genuine immediate and naturally paused requests must retain their
initial words, create one session and preserve existing follow-up,
timeout/goodbye and privacy/consent behaviour.

Before final physical evaluation, agree numeric targets for false
conversations/hour, genuine-turn acceptance and added latency, with defined
independent trials and observation duration. Report both wake candidates/hour
and false conversations admitted/hour, exposure hours, scenario counts,
false rejects and p50/p95 admission latency. Separate calibration from
held-out evaluation; zero observed false admissions is not a universal zero
rate. Record thresholds and model versions without tuning on final trials.

Record evidence in `docs/verification/phase-24g-<date>.md`, with hardware,
software, thresholds, resource use, coverage and limitations. Completion
requires resolved STT/session-boundary decisions, passing required scenarios
and downstream-isolation checks, agreed usability targets met on the robot,
and passing conversation/authorization regressions. This documentation change
adds no runtime feature and makes no live acceptance claim.
