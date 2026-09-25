# ADR 0023: Robot microphone/speaker conversation transport

- Status: Accepted for Phase 24c (implementation); physical acceptance is
  Phase 24d and has not been performed.
- Date: 2026-09-24

## Context

[Phase 24c](../phase-24cd.md) requires an owner-started, bounded conversation
through Reachy's own microphone and speaker. Before this decision the only
voice paths were `POST /voice/turn` (a caller uploads a WAV and receives a WAV)
and the browser "Call Reachy" WebRTC call. Neither captures from the robot.

The hub reaches embodiment through `EmbodimentClient`'s unauthenticated
inbound HTTP API. Exposing microphone capture on that API would let anything
on the network record the room. The hub cannot authenticate to the robot
either: [ADR 0019](0019-robot-initiated-hub-connectivity.md) keeps only
PBKDF2 verifiers of robot tokens, not plaintext. ADR 0019 already specifies
the intended media shape: the WSS control socket carries only control and
result messages, bounded microphone turns upload to authenticated hub
endpoints, and robot playback fetches bounded audio from the configured hub
origin.

## Decision

Robot conversation uses ADR 0019's robot-initiated media path, not the legacy
hub-to-embodiment HTTP adapter.

```text
operator UI --owner cookie+CSRF--> hub /robot-voice/start|renew|stop
hub --WSS voice_start / voice_stop (control only)--> reachy-embodiment
reachy-embodiment: mic -> Silero VAD -> one bounded WAV utterance
reachy-embodiment --HTTPS POST /robot-media/voice-turn, robot bearer-->
    hub: STT -> handle_inbound_message(channel=reachy, VOICE) -> core
         -> ADR 0006 routing + speaker permission -> TTS only if permitted
    <-- 200 audio/wav (speak) | 204 + outcome header (withheld/no speech/cancelled)
reachy-embodiment --WSS voice_state--> hub (listening/speaking/error)
reachy-embodiment -> daemon /media/sounds/upload + /media/play_sound
```

- **Robot identity and fencing.** The upload is authenticated with the robot's
  existing ADR 0019 credential (`X-Robot-Id` + bearer), must name the current
  connection generation, the active voice session and the next expected turn.
  A robot token alone never starts capture: only an owner-authenticated
  `start` creates a session, and the robot captures only while it holds one.
- **Control messages.** `voice_start`, `voice_stop` (hub to robot) and
  `voice_state` (robot to hub) are additive message types. The robot advertises
  a `voice_conversation` capability at registration; the hub refuses to start a
  session on a robot without it, so `PROTOCOL_VERSION` stays 1. Audio never
  travels over the WSS socket.
- **Lifecycle ownership.** The hub owns the session: one per robot, an owner
  lease the UI renews, a maximum duration, an idle timeout and one in-flight
  turn. Logout, lease lapse, expiry, robot disconnect and explicit stop end it.
  Sessions are process-local and never restored after a hub or robot restart.
  The robot also stops on WSS disconnect and on its own copy of the maximum
  duration, and never resumes capture automatically after reconnecting.
- **Speaker permission.** The hub decides whether a reply may be spoken before
  synthesis. It uses ADR 0006's `resolve_delivery_channel` and
  `apply_privacy_override`, and also withholds while DND is on or the session's
  privacy context is `meeting`. A withheld reply is shown in the owner's
  authenticated voice panel with the reason, and additionally pushed to the
  bound Telegram chat when routing selected phone/Telegram. It never falls back
  to room speech. This is a deliberate exception to ADR 0006's "reply on the
  originating channel" rule: the robot speaker is audible to the whole room,
  so it is gated like a proactive delivery.
- **Consent.** Transcripts enter core as `InputModality.VOICE` on
  `Channel.REACHY`. ADR 0011 still refuses voice confirmation, and core parses
  Phase 24b `/reachy` commands only from typed text.
- **Turn-taking.** Half-duplex. The robot discards microphone input while
  uploading, waiting and playing, plus a short tail guard, and resets VAD
  before listening again. Cancellation calls the daemon's `POST
  /api/media/stop_sound`, not only abandoning HTTP work.

Limits (defaults in `shared/models/robot_ws.py` / `robot_voice.py`): 15 s
maximum utterance (30 s for a whole turn since the
[adaptive end-of-turn addendum](#addendum-adaptive-end-of-turn-2026-09-25-phase-24e)),
700 ms end-of-speech silence, 300 ms minimum utterance, 1 MiB upload, 15 s owner lease, 10 minute session, 120 s without a transcribed
turn, one in-flight turn per session.

## Consequences

- Behaviour, camera and remaining audio commands still use the legacy HTTP
  adapter; this ADR migrates only conversation media. A robot must be WSS
  registered to converse even when an HTTP `base_url` is also registered.
- Microphone capture uses the `reachy_mini` SDK's LOCAL audio backend, which
  opens the ALSA `dsnoop` device the daemon shares. In a container this needs
  the host `~/.asoundrc`, host IPC namespace and the daemon user's UID. See
  [deployment](../deployment.md#robot-voice-conversation). This has not been
  verified on the Nano.
- Push-to-talk-free listening inside an owner-started session does not
  identify who is speaking. The UI says so. Phase 25 adds recognition before
  any ambient mode; this ADR does not permit unattended or default-on capture.
- The original `POST /voice/turn` remains a caller-upload diagnostic and is
  not the robot workflow.

## Status addendum (2026-09-25)

Physical acceptance (Phase 24d) started on 2026-09-24 on the real Nano and
Reachy: live capture, STT, conversation, Piper TTS and daemon playback ran
end to end, and stop reached the daemon in about 32 ms. The formal matrix is
still open; see the
[24d record](../verification/phase-24d-conversation-2026-09-24.md). The
decision above is unchanged. Piper replaced espeak-ng as the hub's TTS
during 24d because espeak was judged unpleasant to listen to on the robot,
a usability defect of this workflow rather than a cosmetic change.

## Addendum: bounded spoken replies (2026-09-25)

Phase 24d closed on the conversation workflow
([results](../verification/phase-24d-conversation-2026-09-24.md#results)).
Its first formal run failed the latency budget because the local 1.5B model
ignored the one-to-three-sentence spoken instruction. It gave 121–162-word
markdown replies, up to a minute of speech. Those replies also stayed in
the history and slowed later turns.

**Decision.** Core bounds every voice-modality reply deterministically,
instead of trusting the instruction:
- The local model gets `max_tokens=100`, which bounds generation time.
- Whichever provider answered, the reply is cut to whole sentences within
  75 words before it is recorded. So speech, synthesis and history are
  bounded, and the robot never stops mid-sentence.
- The cloud model gets no token cap. GLM-5.3 spends its completion budget
  on reasoning and returns empty content under a small cap (see the
  [hosted-cloud follow-up](../verification/history.md#hosted-cloud-follow-up--2026-09-22)),
  which would turn a fallback into a failure.

Typed turns are unchanged. The hub still strips citations and markdown
before TTS. The owner can ask for more detail in the web chat.

## Addendum: adaptive end of turn (2026-09-25, Phase 24e)

Phase 24d found that a fixed 700 ms end-of-speech silence split one long
utterance with natural pauses into four turns, each answered on its own
([24d record](../verification/phase-24d-conversation-2026-09-24.md)).
[Phase 24e](../phase-24e.md#1-adaptive-end-of-turn) makes the end of a
turn depend on whether the speaker sounds finished.

**Decision.**

- **Segments and the hold.** The robot still cuts a segment after the
  end-of-speech silence and uploads it as before. The hub transcribes it and
  applies fixed rules (`reachy_hub/turn_completeness.py`). If the transcript
  looks unfinished, the hub holds it: no core call, no synthesis. It answers
  `204` with the new outcome `continue`. Held text is process-local session
  state like everything else here. Stop, expiry, logout or disconnect
  discard it, and it is never answered later.
- **Completeness rules.** A trailing ellipsis, comma, colon, semicolon or
  dash marks the segment unfinished. So does a final article, possessive,
  conjunction or filler ("the", "my", "and", "because", "um", …), or a short
  unfinished phrase ("tell me", "I was wondering"). Terminal punctuation
  does not override these, because STT inserts periods. A final
  preposition ("about", "with", "to", …) means unfinished unless the segment
  ends with a question mark ("Who are you talking to?"). Everything else,
  including a finished thought without punctuation, is complete. No LLM
  takes part. These are heuristics: a false hold costs the continuation
  window in latency, and a missed hold splits the turn as before.
- **Continuation and finalize.** A held turn keeps its turn number. Each
  further segment is uploaded to `ROBOT_VOICE_TURN` with the same
  `X-Voice-Turn` and `X-Voice-Segment` set to the next segment number
  (absent means 1). The hub appends its transcript to the held text and
  decides again. A segment with an empty transcript is not held again. If
  the robot hears no new speech start within `continuation_window_ms`
  (default 1500, hub-set in `VoiceLimits`, timed from the segment cut), it
  POSTs `ROBOT_VOICE_TURN_FINALIZE` with the same identity and fencing
  headers and no body. The response has the same form as an upload's.
- **Fencing.** A continuation segment or finalize is accepted only for the
  held turn number and the exact next segment; anything else is `409`, and
  the robot ends the session, as for any refused turn. A new turn number
  while a turn is held (possible only after a lost upload) discards the held
  text and records it as cancelled. A segment or finalize is an in-flight
  turn, so the one-in-flight-turn rule is unchanged.
- **Microphone during upload.** Within a turn, the robot keeps the
  microphone open while a segment uploads, so a speaker who resumes during
  that time is not clipped. That audio is used only if the hub answers
  `continue`. Any other outcome discards it and closes the microphone
  before playback. Half-duplex is unchanged: the microphone is never open
  while the robot speaks, and the tail guard still follows playback.
  `continue` is followed by no playback and no tail guard.
- **Length cap.** `max_utterance_seconds` now bounds the merged turn, and
  its default rises from 15 s to 30 s. The robot limits each segment to the
  remaining budget. The hub holds only when at least
  `MIN_CONTINUATION_SECONDS` (1 s) of budget remains, and rejects a merged
  turn more than 1 s over the cap. A 30 s segment still fits the 1 MiB
  upload limit.
- **Compatibility.** The robot advertises `voice_turn_continuation` at
  registration. The hub holds only for robots that advertise it, and only
  when the window is non-zero; otherwise every segment is answered as
  before. `PROTOCOL_VERSION` stays 1.
- **Owner panel.** Held segments are not listed. The answered turn's record
  carries the merged transcript and its segment count.

Complete-looking turns keep their previous latency. Only turns that sound
unfinished wait for the window.
