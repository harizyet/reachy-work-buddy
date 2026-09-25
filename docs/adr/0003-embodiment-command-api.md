# ADR 0003: Semantic Embodiment Command API

- Status: Accepted
- Date: 2026-09-21


## Phase 22 connectivity amendment (planned)

[ADR 0019](0019-robot-initiated-hub-connectivity.md) adopts robot-initiated
WSS control and a separate outbound media path. Core-to-hub HTTP, semantic
commands, hub-owned browser WebRTC and independent local fallback remain.
The original HTTP implementation described below remains current until
Phase 22 is implemented.

## Phase 24f move-preemption amendment (2026-09-25)

`reachy-mini` 1.8.4 runs overlapping REST moves concurrently (see the
[source trace](../verification/phase-24f-source-2026-09-25.md)).
`reachy-embodiment`'s daemon backend therefore keeps the UUID of the move
it last started and stops that move before starting another, so the newest
move wins at this level. It also stops the move before daemon standby and
at shutdown. It stops only its own moves, never other daemon clients'. A
stopped move holds its pose and is not followed by a return home.
`interruptible` and `priority` are still not enforced. Conversation-level
ownership and rejection are Phase 24f item 3 and need their own amendment.

## Phase 24f motion-ownership amendment (2026-09-25)

Status: accepted for implementation. Enabled behaviour is not physically
accepted yet.

One local owner, `MotionController` in `reachy-embodiment`, handles every
motion path in the service: the robot voice conversation, explicit
`POST /behaviour/{name}`, idle presence and daemon standby. Core and hub
keep their roles. No transcript or LLM output selects a gesture.

- **Switches.** `CONVERSATION_MOTION_ENABLED` covers listening and thinking
  gestures and one return home. `SPEECH_WOBBLE_ENABLED` covers the daemon's
  audio-reactive head motion while speaking. Both default to off. With both
  off, the controller takes no ownership, and every path behaves as it did
  before 24f.
- **Ownership.** While a switch is on, a robot voice conversation owns
  motion for its whole session. Explicit behaviours get HTTP 409, and idle
  presence skips its tick. Nothing is queued to play later. When `/remote`
  is active, the conversation sends no motion, because remote control owns
  the robot.
- **Fencing.** Each conversation gets a token, so calls from a replaced
  session are ignored. A gesture plays at most once per turn and state:
  returning to listening after a held segment stops the thinking gesture
  and does not replay the listening one. Repeated state reports do nothing.
- **Dispatch.** Transitions go to one worker thread, so the voice event loop
  never waits on the daemon. Only the latest transition is kept. Each
  transition states the complete motion wanted, so a dropped intermediate
  one loses nothing.
- **Stop.** Standby and shutdown call `stop()`, which invalidates pending
  work first. It then waits for any in-flight daemon call and stops that
  move by UUID. It also disables speech wobble, which zeroes the offsets
  that 1.8.4's `stop_sound` leaves applied. A voice stop, disconnect or
  failure ends ownership with a stop and no return home. Only a normal
  session end (the session length limit) returns home, with one bounded
  `/move/goto` to `IDLE_HOME` sent with fixed keys and explicit body yaw.
- **Startup.** The embodiment sends no startup home. In 1.8.4 the daemon
  reports `running` only after its wake-up, which already ends at
  `IDLE_HOME`. Cold boot, resume and once-per-boot recovery all run that
  wake-up. An embodiment restart or hub reconnect must not replay a home
  move, and has no other safe lifecycle boundary to key one to. This means
  no motion is added beyond the existing unattended-start exception.

- **Between gestures** (added after the 24f conformance run): a recorded
  gesture ends at its own final pose, and 1.8.4 starts the next recorded
  move from its first frame without a blend. So while a gesture has left
  the head away from home, the next transition first returns home. Before
  a new gesture, it allows 1.2 s for that; a newer transition or a stop
  during the wait cancels the gesture. When no gesture follows, the
  return home replaces the plain stop. Stops still hold.

Speaking uses daemon wobble, not a recorded move. It is a daemon-wide
setting, so it is enabled only during playback and disabled on every other
transition and on stop.

## Portal animation settings amendment (2026-09-25)

The owner may change the two conversational motion switches from Settings
in the operator portal. Embodiment owns runtime values via
`GET/PUT /settings/motion`; hub proxies them through owner-authenticated
`GET/PUT /robots/{robot_id}/settings/motion`, with the existing cookie/CSRF
and bearer rules. The shared contract contains only `conversation_motion`
and `speech_wobble` booleans; GET/PUT responses also report whether a
conversation is active. No model selects or changes these values.

Changes are accepted only between conversations, after pending motion has
finished. The local motion owner's dispatch/state locks serialize updates
against transitions and conversation starts. Saving settings sends no
motion command. Values live in embodiment memory; a service restart reads
`CONVERSATION_MOTION_ENABLED` and `SPEECH_WOBBLE_ENABLED` again, both off by
default. This adds no persistent store or daemon restart path. The existing
physical acceptance and supervision requirements still apply to playback.

## Context

`companion-core` needs to make Reachy express behaviours (listening,
thinking, greeting, "sent to your phone", etc.) without knowing anything
about servos, recorded-move datasets, or the Reachy daemon's REST/WebSocket
API. Coupling reasoning output to raw motor targets would violate the
cognition/embodiment boundary (ADR 0001) and make `reachy-embodiment`
un-swappable.

## Decision

`reachy-embodiment` exposes a small semantic HTTP API:

```
GET  /health
GET  /state
GET  /behaviours
POST /behaviour/{name}
POST /gaze
POST /pose
POST /audio/play
```

Callers send an `EmbodimentCommand` (see `shared/models/embodiment.py`):
`behaviour_name`, `priority`, `parameters`, `interruptible`,
`correlation_id`. `reachy-embodiment` resolves `behaviour_name` against its
own behaviour catalogue (backed by Reachy recorded-move datasets initially)
and drives the Reachy daemon itself. No caller outside `reachy-embodiment`
ever issues raw joint/pose commands to the daemon.

The initial behaviour vocabulary (see `shared/models/embodiment.py`):
listening, thinking, speaking, acknowledgement, understood, uncertain,
greeting, goodbye, waiting, task_complete, cannot_comply, sent_to_phone,
incoming_message, meeting_soon, important_notice, do_not_disturb,
idle_breathing, subtle_scan, antenna_twitch, sleep, wake.

## Consequences

- `reachy-embodiment` can be reimplemented (different robot, different
  motion backend) without touching `companion-core`.
- New behaviours are added by extending the catalogue in
  `reachy-embodiment`, not by changing `companion-core`'s output format.
- `correlation_id` ties an `EmbodimentCommand` back to the `AgentResponse`
  that requested it, for audit/debugging.
