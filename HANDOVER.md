# Handover

Current session snapshot: 2026-09-25. Read [AGENTS.md](AGENTS.md) first.
The [documentation index](docs/README.md) defines ownership;
[project state](docs/project-state.md) collects deployment limits and open
acceptance. This file holds only session continuation details.

## Current work

[Phase 24f](docs/phase-24f.md) now has a draft plan for motion conformance,
startup home and conversational animation, linked from the roadmap. No motion
code, deployment or physical checks were performed in this planning session.
24f item 1 has started. The [1.8.4 source trace](docs/verification/phase-24f-source-2026-09-25.md)
(source plus mockup-sim, no robot) settled the home targets, the wake-up
completion signal and UUID cancellation. It also found that overlapping
REST moves both run. `ReachyDaemonBackend` now stops its previous move
before starting another, and before standby and at shutdown
([ADR 0003 amendment](docs/adr/0003-embodiment-command-api.md#phase-24f-move-preemption-amendment-2026-09-25)).
This is checked against a mockup-sim daemon and is not deployed; the
embodiment image on the Nano is unchanged. Embodiment tests: 84 passed, 5
skipped, after fixing two test STT fakes missing 24e's `vocabulary`
keyword. A later session pinned the Testbench at `480b0cc`. It uses the SDK
WebSocket path into the same backend `goto_target` as REST, but REST
ignores interpolation, keeps body yaw when it's omitted, and accepts a
misspelled pose key as identity. It also found that 1.8.4 has daemon-side
speech wobble on `play_sound`, where `stop_sound` leaves the last offset
applied ([trace](docs/verification/phase-24f-source-2026-09-25.md#testbench-and-sdk-path-compared-with-rest)).
All of this is from source only. The Nano was offline (no LAN route;
Tailscale last seen 6 h earlier), so its daemon version is still
unconfirmed: next, run `reachy-venv/bin/pip show reachy-mini` and
`GET /api/daemon/status` there (read-only). Timing budgets and the
unattended-home policy still need settling before physical rollout. The 24e work below remains
outstanding.

The owner added [24e item 5](docs/phase-24e.md#5-open-palm-stop): a held
open palm stops a spoken reply and Reachy listens again. It is implemented
in `reachy_embodiment/gesture.py` with MediaPipe, behind `PALM_STOP_ENABLED`
(off). The launcher, `.env.example`, Dockerfile (`libgles2`, pinned model)
and uv lock are updated. It was checked in process and in an amd64 image
build only ([record](docs/verification/phase-24e-palm-stop-2026-09-25.md)).
Next for it: build the image on the Nano and check the startup log for
`palm stop ready`. That needs no motion.

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

- **Nano:** checkout `00a5e68` or later; embodiment image from `1a66f01`,
  voice enabled. `reachy-embodiment.service` and
  `reachy-daemon-recovery.service` enabled; container uses `--mount` and no
  restart policy. Embodiment is host-networked on 8100, daemon loopback on
  8000. Apply the [deployment boundaries](docs/deployment.md#robot-host-and-jetson-nano)
  before daemon starts or motion; `--check` stays read-only.
- **Homelab:** dev/test stack at `9251efc`, schema `008_assistant_context`.
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
