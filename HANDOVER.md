# Handover

Current session snapshot: 2026-09-25. Read [AGENTS.md](AGENTS.md) first.
The [documentation index](docs/README.md) defines ownership;
[project state](docs/project-state.md) collects deployment limits and open
acceptance. This file holds only session continuation details.

## Current work

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

Verification: ruff passed. Core 360 passed, 18 skipped; hub 197 passed,
9 skipped; `slow` real-speech tests (tiny.en, espeak via
`/tmp/espeak-extract`) 11 passed, 1 skipped (no Piper model). In-process
only, not physical acceptance.

Next: 24e item 3 of the sequence, the correctness set. Write its scoring
rules, then get the owner's pass threshold **before** any measurement.
Deploy items 1–2 to the hub and Nano when the owner schedules the physical
run. Phase 25 remains blocked on the
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

The owner is checking `stewart_5` manually after overheating/lag/drift.
The unexplained power loss, RTC problem and daemon recovery verification
limit are in [project state](docs/project-state.md#known-hardware-and-software-limitations).
The automatic error restart remains fake-tested only.

Inspect `git status`, recent commits and the diff before implementation.
Hardware work previously involved a separate Nano-side session; verify raw
device identity before accepting remote reports. Use
[camera socket recovery](docs/deployment.md#camera-socket-directory-recovery)
if the socket becomes a directory again. Durable build, credential, upgrade
and supervision procedures are in the deployment/development guides.
