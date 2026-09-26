# Handover

Current session snapshot: 2026-09-26. Read [AGENTS.md](AGENTS.md) first.
The [documentation index](docs/README.md) defines ownership;
[project state](docs/project-state.md) collects deployment limits and open
acceptance. This file holds only session continuation details.

## Current work

The homelab portal was redeployed 2026-09-25 at 14:32 UTC with chat search
indicators and per-robot runtime animation controls. Live Chromium verified
five real search results, expansion, no indicator on a subsequent ordinary
turn, and disabled animation controls while Reachy is offline. Auth/CSRF
checks and three fixture browser regressions passed. See the
[deployment/test record](docs/verification/portal-controls-2026-09-25.md).
The owner kept Reachy powered off and limited this run to the web UI.
**Next:** rebuild the Nano embodiment image before live animation settings
can work; physical animation testing is still open. Runtime settings restore
environment defaults on restart; see the
[operator guide](docs/operator-guide.md#conversational-animations).

The [24e physical run](docs/verification/phase-24e-physical-2026-09-25.md)
ran with the owner on 2026-09-25 and 2026-09-26. Passed: Normal
conversation; Timing (warm re-run p50 3.63 s, p95 5.22 s); turn handling
apart from TV speech (known limit, deferred to Phase 25; continuation
window owner-set at 3.0 s, `da93df9`); stop and expiry (31 ms playback
stop); privacy by voice after the carry-over fix (`52fefdb`); consent after
the deterministic email-action refusal (`c383370`); session continuity
(robot → web → Telegram → robot); recovery from hub, network and
embodiment restarts (the audio-fault sub-row is in-process only, by owner
decision, because a daemon media release doesn't affect the ALSA mic or
speaker); open-palm stop with either hand and no false stops (owner accepts
1–2 s to silence). **Next for 24e:** the 30-minute session.

Homelab fixes after the owner ended testing (deployed, not yet exercised
on the robot): weather search keeps a question's own place instead of
appending the owner's location (`4a9dd16`), and the hub's INFO logging
(`7a597e6`). Open owner decisions from the run: whether time-of-day
questions should search or use the clock; whether a keyword in the
model's own wording (e.g. "schedule") should still be able to withhold a
public answer from the speaker; whether to try a larger STT model after
mishearings ("coil and the flue", "court would"). Known, not fixed: a
daemon media release/reacquire (any `no_media` SDK client) breaks the
embodiment camera until embodiment restarts, since the socket bind keeps
the old inode.

24f physical ([record](docs/verification/phase-24f-physical-2026-09-26.md)):
the owner's portal toggle reaches the robot. The step B motion-off
baseline is recorded. Step C (gestures on) failed on the robot's daemon
client: stopping an already-finished move made the daemon drop the
connection, and the next gesture or home move reused it. That's fixed in
`b36736d` and verified against a mockup only. The robot-side cost of
gestures was +19.5 ms median. The owner switched gestures back OFF and
ended testing for the day. **Next:** with the owner present, swap in the
`b36736d` embodiment image (built on the Nano, not deployed), check it,
then rerun step C (`docker tag reachy-embodiment:b36736d reachy-embodiment:local`
first, then the usual swap via `start-reachy.sh`): 22 lines, a Stop during the thinking gesture, and the
409 explicit-behaviour check.

[Phase 24f](docs/phase-24f.md) is in progress. Item 1 is measured on the
Nano ([record](docs/verification/phase-24f-conformance-2026-09-25.md)).
REST, the SDK (Testbench) path and Pollen's streaming method send the
same poses, and the head camera confirms the head moves as far as the
encoders report. The owner's "no visible motion" was a perception limit.
The robot stops 2–5° short of commanded poses on every path, only when a
joint's angle has to grow. The stock proportional-only gains (PID
300/0/0) predict that, so normal versus a friction or load fault on this
unit is open. Unattended development testing is allowed (owner,
2026-09-25, [AGENTS.md](AGENTS.md)), except full animations and the
daemon wake-up. `motion-conformance.py --camera` measures moves from
head-camera frames (CLAHE, frame draining and validity gates; see the
record). The Lite camera is dark by default, and raising its exposure is
the owner's call. Every item 1 case has now run: the bounded ones unattended, and
`recorded`/`preempt` with the owner watching. A recorded gesture ends at
its own final pose, and 1.8.4 starts the next without a blend. So
conversational gestures need a return home between them before
`CONVERSATION_MOTION_ENABLED` is tried (see the record).
Raw logs and frames are in the Nano's `~/24f-logs`. Item 1's outcome table
is in the record: the paths conform.

The motion owner (`reachy_embodiment/motion.py`, `4f43817`) is implemented,
with its [ADR 0003 amendment](docs/adr/0003-embodiment-command-api.md#phase-24f-motion-ownership-amendment-2026-09-25):
`CONVERSATION_MOTION_ENABLED` and `SPEECH_WOBBLE_ENABLED`, both off. It
was decided not to add a startup home, because 1.8.4's wake-up already
ends at IDLE_HOME. Tests are fake-backend and in-process only: embodiment
125 passed, 6 skipped, and ruff passes. The launcher passthrough is
untested on the Nano. Nothing is deployed: the Nano checkout was pulled to
`17a8ef9` for the conformance script, but the embodiment image is still
from 2026-09-24. `deploy/reachy/motion-conformance.py` runs one bounded
case per `--run`. Its SDK cases now reacquire daemon media: a 1.8.4
`no_media` SDK client releases the daemon's camera for everyone, which
blocked the embodiment start once.

The owner added [24e item 5](docs/phase-24e.md#5-open-palm-stop): a held
open palm stops a spoken reply and Reachy listens again. At the owner's
direction, detection now runs on the hub (`reachy_hub/palm_stop.py`,
MediaPipe). The robot (`reachy_embodiment/gesture.py`) only uploads 640 px
frames during playback when the hub's `PALM_STOP_ENABLED` (off) turns it
on for the session. Tested in process and in amd64 hub/embodiment image
builds, not deployed ([record](docs/verification/phase-24e-palm-stop-2026-09-25.md)).
Next: rebuild the hub on the homelab and the embodiment image on the Nano
(no motion needed), then the physical rows.

Branch `main`. [Phase 24e](docs/phase-24e.md) item 1 (adaptive end of turn)
is committed in `6f292be`. This session added item 2's deterministic part:
search-rule fixes in `companion_core/websearch/policy.py` (closings,
greetings and self-identity never search, bare "now" is not a freshness
cue, and follow-ups must refer back to the previous search) and an STT
`initial_prompt` with "Reachy" plus the persona name. Design choices are in
[the item 2 notes](docs/phase-24e.md#implementation-notes-item-2). A parallel
session had started the same policy rewrite and disconnected mid-edit; its
version was kept and completed. Nothing is deployed: the homelab hub and
Nano embodiment image still run the pre-24e turn path.

Verification: ruff passed. Core 380 passed, 18 skipped; hub 197 passed,
9 skipped; `slow` real-speech tests (tiny.en, espeak via
`/tmp/espeak-extract`) 11 passed, 1 skipped (no Piper model). In-process
only, not physical acceptance.

The correctness set (`services/companion-core/eval/`), its
[scoring rules](docs/phase-24e.md#correctness-set-scoring-rules) and the
owner's threshold (≥90% overall, every category ≥80%) were committed before
any measurement; plain statements with a freshness word no longer search.
The local model then passed it: 82/87 (94.3%), every category ≥ 87.5%,
in the [correctness record](docs/verification/phase-24e-correctness-2026-09-25.md);
the cloud model was not needed. Next: 24e item 4 (Nano diagnostics, needs
the owner's approval for system changes), then the physical run.
Deploy items 1–2 when the owner schedules the physical run. Phase 25
remains blocked on the
[hardware prerequisites](docs/phase-24e.md#prerequisites-for-phase-25).

## Last-reported machine state

These are previous session observations, not health checks performed during
this documentation pass. Recheck state before relying on them.

- **Nano:** booted 2026-09-26 ~02:35Z (the owner's power cycle); daemon
  running (0 errors), embodiment healthy, no overheat or recovery entries.
  Checkout `65c7e75`. The running embodiment image is `eb1e92e9`, built at
  `67bfc5f` on 2026-09-26 10:33Z, with gestures and speech wobble OFF.
  A `b36736d` image is built under the tag `reachy-embodiment:b36736d` but
  not deployed; `docker tag` it as `reachy-embodiment:local` before the swap.
  No MediaPipe on the Nano (palm stop is hub-side); voice enabled; the hub
  reports it online and voice-capable. Left at IDLE_HOME with embodiment
  active (2026-09-26 ~10:55Z). The 24f tool dependency `opencv-python-headless`
  4.11.0.86 is in `~/24f-tools` only (use `PYTHONPATH`), not in
  `reachy-venv`. Logs and frames are in `~/24f-logs`. `reachy-embodiment.service` and
  `reachy-daemon-recovery.service` enabled; container uses `--mount` and no
  restart policy. Embodiment is host-networked on 8100, daemon loopback on
  8000. Apply the [deployment boundaries](docs/deployment.md#robot-host-and-jetson-nano)
  before daemon starts or motion; `--check` stays read-only.
- **Homelab:** rebuilt 2026-09-26 14:27Z at `7a597e6`; hub and core
  healthy, nano-1 online and voice-capable. Latest pre-change backup is
  `~/reachy-backups/reachy-before-24f-deploy-20260925T131937.dump`; schema
  `008_assistant_context`. The private `.env` now sets
  `PALM_STOP_ENABLED=true` and `VOICE_CONTINUATION_WINDOW_MS=3000` (owner
  decisions, 2026-09-26). The hub now logs its own INFO lines (`7a597e6`).
  Restarting only core: `docker restart reachy-homelab-companion-core-1`,
  since `docker compose restart` without the launcher fails on the
  generated SearXNG secret.
  Start only through `scripts/start-homelab.sh`. Piper `en_US-lessac-medium`;
  search policy Auto, Brave/Exa/Tavily rotation then SearXNG. Backups in
  `~/reachy-backups/` (0600). Core readiness needs a separate check after
  launcher hub health succeeds.
- **Local inference:** an unrelated `ovms` container previously served
  `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` on localhost:8000. Re-query
  `/v1/models`; leave unrelated services alone.
- Hosted credentials are in gitignored `deploy/homelab/.env.local`.
  Check presence and ignore rules without printing values. No Google OAuth
  client file or live helper run was supplied in the preceding session.
- Nano Tailscale endpoints to the homelab switched between 10.180.1.23,
  .54 and .254; a stall caused a watchdog disconnect before its increase
  to 15 s. Network cleanup remains the owner's call.
- Robot logs from 24d are in `~/24d-logs/`; `/tmp` is cleared on reboot.
  Development caches may also be gone; use [development](docs/development.md).

## Immediate cautions and continuation

The owner reports successful official Testbench zeroing and rotations after
24d's tracking anomalies; a persistent hardware fault is not established.
Phase 24f will compare the motion paths; current evidence is recorded below
in project state.
The unexplained power loss, RTC problem and daemon recovery verification
limit are in [project state](docs/project-state.md#known-hardware-and-software-limitations).
The automatic error restart remains fake-tested only.

Inspect `git status`, recent commits and the diff before implementation.
Hardware work previously involved a separate Nano-side session; verify raw
device identity before accepting remote reports. Use
[camera socket recovery](docs/deployment.md#camera-socket-directory-recovery)
if the socket becomes a directory again. Durable build, credential, upgrade
and supervision procedures are in the deployment/development guides.
