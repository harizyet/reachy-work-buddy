# Phase 24f — Motion conformance and conversational embodiment

Status: **in progress** (2026-09-25). Item 1 is measured: REST, the SDK
and Pollen's streaming method agree, and the head camera confirms the
head moves as far as the encoders say. The robot stops 2–5° short of
commanded poses on every path, and whether that is normal for the stock
proportional-only gains or a fault is open
([conformance record](verification/phase-24f-conformance-2026-09-25.md)).
Item 3's motion owner is implemented behind two off-by-default switches
([ADR 0003 amendment](adr/0003-embodiment-command-api.md#phase-24f-motion-ownership-amendment-2026-09-25)).
Item 2 settled on no startup home. Nothing is deployed or accepted.
Validate motion against Pollen's version-matched SDK/Testbench, establish a
verified home after wake-up, and express conversation state locally on Reachy.
The LLM does not select trajectories or authorize motion.

## Order and dependencies

Place 24f after [24e](phase-24e.md) and before [25](phase-25.md) in the roadmap.
Source inspection and isolated tests can proceed while 24e acceptance remains
open. Accept the 24e conversation baseline before measuring animation regressions.
Physical motion work requires owner supervision under the existing deployment
rules. A persistent hardware fault is not established; use the updated
[Testbench counter-evidence](project-state.md#known-hardware-and-software-limitations)
when planning the comparison.

The existing [24e prerequisites](phase-24e.md#prerequisites-for-phase-25) remain
Phase 25's start gate. This draft does not silently add all of 24f to it.
Recommended dependency: any 24f startup/motion changes enabled on the stack used
for Phase 25 must pass their conformance, cancellation and coexistence rows
first. Phase 25 may use the accepted baseline with 24f disabled; expressive
animations alone need not delay recognition work. Rerun affected 24e gates
whenever enabled motion changes the accepted conversation path.

## Current evidence and open questions

Repository inspection confirms:

- [`voice.py`](../services/reachy-embodiment/src/reachy_embodiment/voice.py)
  changes `ServiceState.embodiment_state` in `_set_state`; it does not dispatch
  a physical behaviour there.
- [`robot.py`](../services/reachy-embodiment/src/reachy_embodiment/robot.py)
  maps listening to `attentive1` and thinking to `thoughtful1`. Speaking and
  continuous idle gestures are deliberately unmapped. The current recorded-move
  wrapper logs failures; successful return is not evidence of a settled pose.
- [`presence.py`](../services/reachy-embodiment/src/reachy_embodiment/presence.py)
  suppresses idle dispatch in active states, but state checks alone do not
  cancel a previously dispatched daemon move.

The proposal reports daemon 1.8.4, HTTP stalls during recorded motion, and
IK warnings for `yes1`. The owner subsequently reported successful official
Testbench zeroing and rotation tests with no observed issue; see
[current evidence](project-state.md#known-hardware-and-software-limitations).
These are reported observations, not checks performed in this documentation
session. Re-query deployed versions and pin source revisions before relying
on their exact semantics.

The [1.8.4 source trace](verification/phase-24f-source-2026-09-25.md) (source
plus mockup-sim, no robot) found that overlapping REST moves both run and
both report completion. The hub's call path can overlap `attentive1`,
`thoughtful1` and `waiting`. `POST /api/move/stop` by UUID cancels for real,
and `/goto` ignores `interpolation`. The daemon reports `running` only after
wake-up, which already ends at identity head, antennas ±0.1745 rad and body
yaw 0. Overlap is a candidate cause of the 24d tracking anomalies, not an
established one.

Pollen's [SDK motion documentation](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/python-sdk.md)
describes head, antennas, body yaw, duration and interpolation. The official
[Testbench source](https://huggingface.co/spaces/pollen-robotics/reachy_mini_testbench/tree/main)
is pinned at `480b0cc` in the source trace. It drives the SDK's WebSocket
path into the same backend `goto_target` as REST, but differs on
interpolation, omitted body yaw and cancellation. 1.8.4 also has
daemon-side speech wobble driven by `play_sound`, with a gap on
`stop_sound`; see the
[trace](verification/phase-24f-source-2026-09-25.md#speech-wobble-in-184). Moving `main` links are
research entry points, not the version contract for implementation.

## 1. Motion conformance

Deliver a versioned compatibility table before choosing the implementation.
Record daemon, Python SDK, Testbench, firmware if exposed, robot identity,
recorded-move dataset revision, and application/image revisions.

Compare official SDK/Testbench and our daemon REST path sequentially, from
the same initial pose, with only one controller active. Trace both routes to
the deployed backend; do not infer equivalence merely from endpoint names.

| Case | Required comparison |
|---|---|
| Identity head / zero antennas | Coordinate frame, matrix serialization, units and final measured pose |
| Roll, pitch, yaw | Small positive/negative single-axis targets; rotation order and sign |
| Antennas | Ordering, radians/degrees, zero versus manufacturer home |
| Body yaw | Explicit target versus omitted value; interaction with head yaw |
| Duration / interpolation | Defaults, supported methods, elapsed completion and final target |
| Cancellation | Real daemon cancellation, completion reporting and residual motion |
| Recorded moves | Competition with Cartesian targets, preemption and return behavior |
| Failure | Timeout, daemon error, unsupported method and stale completion |

Use canonical Cartesian transforms, never guessed Stewart joint angles.
Before physical measurement, record bounded test targets and numerical
pose/tracking tolerances justified by upstream limits and telemetry precision.
Capture requested pose, reported pose, joint tracking when available, elapsed
time, daemon errors and owner visual assessment. If telemetry cannot prove
settling, label that limit rather than turning an HTTP 200 into a PASS.
REST remains the default transport unless a demonstrated gap requires a change;
no SDK upgrade is assumed by this phase.

## 2. Startup home and zero semantics

Proposed defaults, to settle in the compatibility review:

- `ZERO`: identity head transform, antennas `[0, 0]`, explicit body yaw zero
  only after its semantics are verified. A diagnostic target, not a new API.
- `IDLE_HOME`: identity head plus the deployed manufacturer's verified home
  antenna/body targets. The proposal's approximately ±10° antenna values
  must be confirmed from pinned source; do not hardcode the approximation.

Keep these names internal unless an existing semantic contract needs a change.
Do not implement the reserved `/pose` or `/gaze` routes.

Startup sequence: observe daemon ready **and wake-up complete** → acquire local
motion ownership → send one bounded home command → observe completion and
settling → permit idle/conversation animation. Discover the actual completion
signal in item 1; a fixed sleep or HTTP liveness alone is insufficient.

Bound readiness and settling waits. Error, standby, ambiguous completion or
tracking failure inhibits automatic motion and exposes a degraded result;
never retry home indefinitely or restart the daemon to make homing succeed.
Fence work to the daemon lifecycle so a reconnect or embodiment restart cannot
blindly replay home or interrupt an already active controller. If the deployed
API cannot identify a safe lifecycle boundary, leave automatic homing disabled
until that limitation is resolved. Explicit stop cancels homing too.

Cover cold boot, explicit resume, once-per-boot error recovery, embodiment-only
restart, and hub reconnect separately. Home is not sleep/standby: never command
it after motors have been de-torqued.

This adds motion beyond the existing unattended-start exception. Keep startup
normalization disabled until supervised acceptance and an explicit owner
extension of the production policy are recorded in
[deployment](deployment.md#robot-host-and-jetson-nano). Existing restart limits
and read-only launcher `--check` behavior remain intact.

## 3. Local conversational motion policy

Keep this inside reachy-embodiment, following
[ADR 0001](adr/0001-service-boundaries.md),
[ADR 0003](adr/0003-embodiment-command-api.md) and
[ADR 0023](adr/0023-robot-voice-conversation.md). Amend the relevant ADR before
implementation to record ownership, preemption and lifecycle behavior.
Core retains reasoning/consent; hub retains sessions, authentication and speaker
permission. No transcript-derived gesture selection or LLM motor commands.

Use one local motion owner for startup, explicit behaviours, conversational
feedback and presence. All existing dispatch paths must participate. Prefer a
small controller within the service to a generic scheduling framework.

- Stop, sleep, error and shutdown invalidate pending motion first. Remote
  control excludes conversation/idle motion. Startup home runs only without
  another active owner.
- Active conversation owns motion over idle presence. Reject conflicting
  ordinary behaviour requests while it owns motion; do not queue them to play
  after a turn. Preserve higher-priority stop/standby control.
- Session/turn generations fence stale completions. Transition to a new state
  cancels the previous motion before replacement; repeated state reports do
  not restart gestures. Coalesce rapid continuation transitions.
- Dispatch must not block the voice event loop. Cancelling a Python task or
  worker thread is not daemon cancellation. Establish real stop semantics
  before enabling any long or repeated motion.

| State | Intended expression |
|---|---|
| Listening | Quiet attentive posture or one small antenna response; avoid motor noise during capture |
| Thinking | Bounded subtle gesture; cancel when the result arrives |
| Speaking | Subtle motion tied to actual local playback lifetime |
| Idle | One bounded return to home on normal completion, then optional local presence |
| Stop/error/sleep | Cancel; no automatic return-home gesture after stop |

Listening/thinking mappings are candidates, not automatic acceptance of the
whole recorded move. Adaptive-turn uploads can leave the mic open: respect
actual capture activity, not just the coarse THINKING label. Do not add a
microphone pause, tail delay or motion on every held segment to hide motor noise.

Speaking preference: version-supported daemon audio-reactive motion, provided
it works with the existing uploaded-WAV playback path. Otherwise use a small,
bounded local pattern stopped with playback. Do not substitute an arbitrary
emotion or an uncancellable long recording. Test 2 s, 15 s and 30 s audio,
playback failure and early cancellation. Withheld/private responses never
trigger speaking animation. Preserve
[response routing](adr/0006-response-routing.md) and
[text-only consent](adr/0011-destructive-action-consent.md).

Animation failure must leave audio cancellation responsive and degrade to
static conversation if the daemon/media path is still healthy. Provide an
independent disable switch for conversational motion and startup homing, both
off for initial rollout. Disabling motion cancels active work and prevents
replay; it does not restart the daemon or silently reactivate capture.

## 4. Verification and acceptance

Follow [development conventions](development.md#testing-conventions): controlled
time and injected backends for transition/preemption tests; real in-process
service boundaries for integration; isolated dependency checks and Ruff for
code changes. Record stub, simulator, real-daemon and physical results separately.

First test payload conformance and lifecycle ordering without hardware. Then
use the deployed daemon under supervision. New/expanded motion, diagnostics,
and development-session daemon starts follow the existing
[supervision rules](../AGENTS.md); this plan grants no new motion permission.

| Acceptance row | PASS evidence |
|---|---|
| Conformance | All applicable item 1 cases match the pinned reference within predeclared tolerances |
| Home lifecycle | Wake-up finishes before home; settling verified; no replay on reconnect/restart; failures inhibit motion |
| Arbitration | No overlapping controllers or stale moves across voice, explicit behaviour, remote and idle paths |
| Voice feedback | Listening/thinking visible without false VAD; speaking follows playback; held turns remain intact |
| Stop and expiry | Stop during home, thinking and playback; expiry/logout/disconnect cancel; no later replay or automatic capture |
| Coexistence | Speech plus motion plus camera requests, followed by microphone reopen; no new capture failure, self-hearing or daemon stall |
| Privacy | Withheld audio has no speaking motion; existing auth and voice-consent negatives still pass |
| Sustained use | One supervised 30-minute session with repeated short/long turns; no new IK, tracking or thermal faults |
| Rollback | Disable switches restore static baseline without daemon restart or stale motion |

Repeat 24e's latency budgets: non-search p50 ≤4 s and p95 ≤8 s; each search
turn ≤20 s; audible stop tail ≤1 s. Proposed additional budgets, fixed before
measurement: paired motion-on versus motion-off p95 first-audio regression
≤250 ms, and physical animation stop ≤1 s after cancellation. Use at least
20 comparable non-search turns per condition, report sample counts and raw
timings, and measure motion stop separately from HTTP acknowledgment. Owner
acceptance of expressiveness and noise is required alongside timings. Do not
claim simulator timing demonstrates physical stop.

Record evidence in `docs/verification/phase-24f-<date>.md`, including versions,
settings, targets, tolerances, logs, timing and PASS/FAIL/BLOCKED per row.
A blocked required row leaves that feature unaccepted and disabled; it does
not become a pass because static conversation still works.

## Delivery sequence and exit

1. Pin versions, reproduce the source paths and write the compatibility table.
   Resolve zero/home targets, cancellation support and speech-motion availability.
2. Record the local motion policy in an ADR amendment; implement arbitration,
   fencing and disable controls with deterministic tests.
3. Implement startup home behind its switch; supervise conformance and lifecycle
   acceptance before proposing unattended activation.
4. Add listening/thinking, then speaking feedback; verify each independently
   before combining with camera and adaptive turns.
5. Run the complete physical matrix against the accepted 24e baseline. Update
   deployment/operator documentation only for accepted operating behavior.

Exit: required rows pass, the owner accepts behavior, rollout/rollback is
verified, and evidence is linked from the roadmap. Hardware repair, general
health notifications, arbitrary trajectories, full-duplex speech, a daemon
upgrade and owner recognition are outside this phase. If the pinned daemon
cannot provide reliable cancellation or audio coexistence, document the gap
and keep motion disabled; propose an upgrade separately rather than expanding
24f implicitly.
