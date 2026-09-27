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
  (Changed 2026-09-27: see [wake-started sessions](#addendum-wake-started-sessions-2026-09-27-phase-24g).)
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

## Addendum: open-palm stop (2026-09-25, Phase 24e)

Spoken replies are bounded (above), but a reply the owner doesn't want can
still run for up to about 30 s, and stopping it meant opening the operator
UI, which ends the whole session. [Phase 24e item 5](../phase-24e.md#5-open-palm-stop)
adds a hands-free way to cut a reply short and keep talking.

**Decision** (amended 2026-09-25, same day: detection moved from the robot
to the hub at the owner's direction, so the Nano stays a light sensor and
actuator).

- **Where.** Split across the two services. While a reply plays, the robot
  (`reachy_embodiment/gesture.py`) reads camera frames through the existing
  LOCAL media client, downscales them to 640 px wide before JPEG encoding,
  and uploads about four a second to `ROBOT_PALM_FRAME` on the hub. This is
  ADR 0019's robot-initiated media path, authenticated like a voice turn
  (robot credential, connection generation, voice session and the turn
  whose reply is playing). The hub (`reachy_hub/palm_stop.py`) runs
  MediaPipe's pretrained gesture recognizer on each frame. The model is
  pinned by version and SHA-256 in the hub image. An open palm seen in two
  consecutive frames of the same reply, with a score of at least 0.6,
  answers `stop: true`.
- **Scope of uploads.** The hub accepts frames only for the reply it is
  currently playing: an active session, matching generation, `speaking`
  state, and a turn whose outcome is `spoken`. Anything else is refused,
  and the robot stops sending until the next reply. Frames are capped at
  256 KB.
- **Effect.** The robot stops daemon playback (`stop_audio`), as a voice
  stop does, and the loop goes straight on: tail guard, then the next
  listening turn in the **same** session. The hub marks that turn's record
  "Stopped by an open palm" and keeps it `spoken`. The model's history
  therefore holds the whole reply even though the listener heard only
  part of it.
- **Not audio barge-in.** The microphone stays closed while the robot
  speaks, so half-duplex is unchanged. The camera is the only sensor added,
  and only for the reply's playback time.
- **Anyone can do it.** Any hand in view counts; nothing identifies the
  person. It only shortens speech, which a voice stop already does, so it
  needs no authentication beyond the robot's own. It cannot start capture,
  send a turn or approve anything, and consent stays text-only
  ([ADR 0011](0011-destructive-action-consent.md)). Withheld replies are
  never played, so they are never watched.
- **Privacy.** Frames leave the robot only for the owner's own hub, only
  during reply playback. The hub decodes and classifies them in memory,
  then drops them. Nothing is stored or logged on either side.
- **Failure.** Palm stop is optional. The hub loads the detector at the
  first frame, off the event loop. If it cannot load, or a frame cannot be
  classified, or the hub cannot be reached, replies play to the end and the
  conversation carries on. The earlier child-process probe for the Nano's
  Cortex-A57 is gone along with MediaPipe on the robot.
- **Enablement.** `PALM_STOP_ENABLED=true` on the hub, off by default. The
  hub tells the robot per session (`voice_start.palm_stop`), so the robot
  has no setting of its own and never reads the camera for this otherwise.
  It stays off in production until physical acceptance.

## Addendum: wake-started sessions (2026-09-27, Phase 24g)

[Phase 24g](../phase-24g.md) adds a spoken wake phrase, initially "Hey
Reachy". Until now only an owner-authenticated `start` could open a session,
and the owner's UI kept it alive by renewing a 15 s lease. A wake-started
session has no such UI. The owner made three decisions on 2026-09-27, which
this addendum records. They explicitly change the rule under
[Consequences](#consequences) that this ADR permits no unattended or
default-on capture.

**Owner decisions.**

1. **Wake monitoring is armed by the owner and stays armed until disabled.**
   It persists across hub and robot restarts. This is a deliberate ambient
   mode before Phase 25 recognition.
2. **Anyone in the room can start a conversation while monitoring is
   armed.** The speaker is not identified, just as in an owner-started
   session today. Every existing gate still applies unchanged: ADR 0006
   speaker permission, DND and meeting withholding, text-only destructive
   consent ([ADR 0011](0011-destructive-action-consent.md)), and `/reachy`
   commands only from typed text.
3. **The hub may transcribe a candidate before it is admitted.** Audio that
   passes the robot's local acoustic gates is uploaded to a dedicated hub
   endpoint. That endpoint transcribes it in memory to decide relevance.
   Rejected speech therefore reaches the homelab's STT process. It never
   reaches core, tools, the owner panel, logs or storage. This replaces
   Phase 24g's provisional no-STT-before-admission rule.

**Decision.**

- **Arming.** An owner-authenticated control (owner cookie plus CSRF, or the
  remote bearer, like `start`) arms or disarms one robot. The hub stores the
  arm in Postgres: robot, arming user, a random arm ID and time. It is
  therefore a schema revision, applied through the normal
  [upgrade path](0020-schema-and-secrets.md). Each arm gets a new arm ID.
  Disarming deletes the row. If the arming user no longer exists, the arm
  is void.
- **Delivery to the robot.** The robot advertises a `wake_admission`
  capability at registration, and `PROTOCOL_VERSION` stays 1. After every
  registration, and on every arm change, the hub sends a control-only
  `wake_arm` message with the arm ID (or none) and the candidate limits.
  The robot monitors only while it holds an arm from its current
  connection. Disconnecting ends monitoring immediately, and the hub sends
  the arm again after reconnection. This restore is intended. Unlike a
  session, an arm is standing owner authority, not a conversation.
- **When the robot listens for the wake phrase.** Only while it is armed
  and connected, no session is active (owner- or wake-started), and its
  daemon backend is running and not in standby. The standby/resume
  commands and a spoken wake are independent: a spoken wake never resumes
  the daemon.
- **Robot-side candidate.** The wake detector runs locally. It keeps only
  a pre-roll ring buffer that it continuously overwrites. A detection
  starts `WAKE_CANDIDATE`, which is distinct from `LISTENING`. The robot
  then waits up to the candidate deadline for speech to start. It captures
  one segment with the existing segmenter, capped at the maximum candidate
  length, and applies local gates: VAD speech duration and the acoustic
  event filter (cough, sneeze, throat clearing, laughter, noise). A
  candidate that fails any gate or the deadline is discarded on the robot,
  and nothing is uploaded. There is no audible or motion acknowledgement
  in 24g, since conversational motion stays off until 24f's deferred rows
  pass.
- **Hub admission.** The robot uploads a candidate that passes its gates
  to `POST /robot-media/wake-candidate` with its ADR 0019 credential, its
  connection generation and the arm ID. The hub rejects it, discarding it
  unheard, unless the arm is current, no session is active, and DND and
  meeting are off. Otherwise the hub transcribes it in memory. It then
  applies deterministic relevance rules, like `turn_completeness`, with no
  LLM. The rules reject an empty or low-confidence transcript, fillers
  only, and a transcript with no plausible wake phrase near its start. They
  also reject text that looks like the continuation of a third-party
  conversation. Ambiguous candidates are rejected.
- **Reject.** The hub answers `204` with the outcome `rejected`, and the
  robot silently restores the state it had before the candidate. A stop,
  disarm, disconnect or standby in the meantime takes precedence. Nothing
  is recorded except content-free counters: candidates and rejections by
  reason, for the per-hour metrics. A late, failed or cancelled candidate
  is discarded the same way and is never replayed.
- **Admit.** The hub creates an ordinary session for the arming user,
  marked wake-started. It sends `voice_start` and processes the candidate
  as turn 1 through the unchanged turn path, reusing its transcript, so the
  first words are kept. The upload's response is that turn's normal
  response. If the length cap cut the candidate, or it sounds unfinished,
  the hub holds turn 1 as in
  [adaptive end of turn](#addendum-adaptive-end-of-turn-2026-09-25-phase-24e).
- **Session lifecycle.** A wake-started session has no owner lease. It
  ends when speech doesn't start within the follow-up timeout after a
  reply, at the existing maximum duration, or on disarm, owner stop,
  disconnect, or DND or meeting turning on. The idle and one-in-flight-turn
  rules are unchanged. It never restarts itself, and the robot then returns
  to monitoring. Owner-started sessions are unchanged.
- **Starting values** (calibration defaults, to be confirmed before
  acceptance per [Phase 24g](../phase-24g.md#verification-and-exit-criteria)):
  3 s from wake to speech start, 10 s maximum candidate segment, and 8 s
  follow-up timeout after a reply. The upload limits are unchanged.
- **Phase 25.** Wake admission is interaction routing, never identity.
  When recognition lands, its pre-STT attribution gate runs before the
  candidate upload. This addendum's STT exception does not relax it.

**Consequences.** The robot's microphone is open for wake detection
whenever monitoring is armed. Only the local pre-roll buffer is kept before
a detection. Candidate speech, including speech from bystanders and TV, is
transcribed on the owner's homelab and then discarded. While armed, anyone
in the room can hold a spoken conversation within the existing gates. The
owner accepted this on 2026-09-27. Disarming is the privacy control.
