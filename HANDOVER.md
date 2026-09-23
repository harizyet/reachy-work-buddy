# Handover

Current session snapshot, updated 2026-09-23. Read [AGENTS.md](AGENTS.md)
before working. Durable instructions belong in the [documentation index](docs/README.md),
not repeated in this file.

## Current work

Phases 0–21 and 22a are implemented. Phase 23 implementation is complete:
versioned migrations, SecretStore, owner-bound Google OAuth, Accounts UI and
read-only Gmail/Calendar integration. Ordinary users select Connect, then enter
their username/password and approve permissions on Google's own screens.
See [ADR 0021](docs/adr/0021-google-accounts.md),
[deployment setup](docs/deployment.md) and
[Accounts evidence](docs/verification/phase-23-accounts-2026-09-23.md).

Migration `004_persona` (2026-09-23) added a configurable assistant identity:
`persona_config` (name + system prompt), owner-editable via the operator UI's
"Assistant persona" card or `GET`/`PUT /settings/persona` (hub proxy to core).
The persona's system prompt is prepended only on the generic LLM conversation
branch — see [docs/reference/services.md](docs/reference/services.md) for the
exact boundary with deterministic intent replies, which never see it.

Next: configure the installation's Google application and HTTPS callback, then
perform real-account consent/read/refresh/revoke/reconnect and audience checks.
No OAuth client file or deployed HTTPS hostname was supplied this session.
Phase 23 is not yet production-accepted. The Google-enabled physical repeat
remains deferred; Phases 24–26 are planning only.

Phase 22b (physical acceptance) started 2026-09-23 with the owner physically
present, coordinated across a homelab-side and a Nano-side Claude Code
session. Fixed a real bug blocking outbound WSS: `RobotWSClient` never
derived `ws(s)://` from the configured `http(s)://` `HUB_WS_URL` (commit
`5443a93`). With that fix, `nano-1` registered over WSS through Caddy for
the first time (real, non-simulated). The real daemon then started
successfully (`sim=false`), but **the first-ever command to real motors
found a head-motion hardware fault**: antennas track commanded poses
correctly, the head (Stewart platform) does not — it moved only ~1-2° of a
~14° commanded change and logged an IK collision warning on the initial
attempt. Motion testing was stopped by owner decision; the daemon was
stopped cleanly before ending the session so no further command could
reach the motors during the owner's physical inspection. See
[first-motion evidence](docs/verification/phase-22b-first-motion-2026-09-23.md)
for exact figures/timestamps. **Do not resume motion testing until the head
has been physically inspected** (linkage/cables/power) — this is a hardware
finding, not an embodiment/software defect (the command chain itself
dispatched and reported correctly throughout). Daemon audio is also broken
independently (`playbin failed to activate sinks`), blocking the voice/audio
acceptance rows regardless of the head issue.
[Phase 26](docs/phase-26.md) was refocused 2026-09-23 from a generic virtual
meeting bot to an embodied secretary: owner-present meeting companion (26a);
a bounded temporary-absence catch-up mode for short owner step-outs within an
already-running 26a meeting (26a.2), which tracks decisions/questions/
deadlines during the absence via an explicit `AbsenceWindow` and delivers a
private, interval-bounded delta on return; physical secretary attendance
while the owner is absent for most/all of a meeting (26b); then bounded
delegation of pre-approved questions/statements or the owner's own verbatim
reply (26c). Virtual/cloud bot joining is now deferred, not a prerequisite.
Owner-directed questions must be forwarded privately via Telegram or another
bound channel from 26a onward; the platform must never answer for the owner.
Next planning gate: 26a needs no ADR amendment (owner present throughout);
26a.2 needs a *narrow* Phase 24 ADR amendment for a capped
`TEMPORARY_MEETING_ABSENCE` lease (meeting-STT-only, no tool/general-speech
authority, auto-expiry, no silent extension into unattended recording); 26b
requires the *full* owner-absent meeting-capture-mode amendment plus
supervised hardware acceptance. These are two separate amendments, not one —
continuing to record while the owner briefly steps out is still technically
owner-absent capture under Phase 24's presence-based rule, even though the
recording began while they were present.

No production deployment was upgraded. This session did bring up and upgrade
the homelab's own disposable dev/test stack (through `004_persona`) for
interactive user testing — real owner login, OpenVINO local LLM routing with
a Together AI cloud fallback, and a bound Telegram owner chat all live there,
but it is not the production-accepted deployment Phase 23 still gates on.
Current code requires revision `004_persona`, a separate 0600
`SECRET_KEY_FILE`, and `ACCOUNTS_SERVICE_TOKEN` in both core and hub. Stop old
writers and back up before a real cutover. See the canonical deployment guide
for migration, authentication and Telegram binding
requirements. The Caddy core data proxy is closed; Accounts requires owner
cookies/CSRF, while work APIs retain authenticated owner bearer access.
Both disposable verification stacks/volumes and their temporary key/env files
were removed; the pre-existing OVMS container was left running.

## Verification and open acceptance

- Phase 23 final fast suite: **366 passed, 2 espeak-dependent skips, 10 slow
  tests deselected**, with real Postgres checks enabled. Ruff and both Chromium
  suites passed. Built images/HTTP and real browser checks used a local Google
  fixture; encrypted restore, concurrent refresh, restart, private chat/briefing
  and proxy-log redaction passed. These are not real Google/physical acceptance.
  The existing homelab launcher waits only for hub health; independently
  check core readiness before inference acceptance.
- [Implementation history](docs/verification/history.md) records Phases 0–21,
  including the successful real Together AI / `zai-org/GLM-5.3` cloud-role
  check. It was a disposable deployment, not a production configuration change.
- [Phase 22a evidence](docs/verification/phase-22-bring-up.md) consolidates
  backend, launcher, WS, and simulator checks. The
  [inventory](docs/verification/phase-22-inventory-2026-09-22.md) preserves raw
  physical-machine findings and dependency/device/memory measurements.
- The real Nano daemon woke the robot on startup and embodiment reported
  connected/non-simulated. Named moves were subsequently exercised through
  the real daemon's **simulator**, not physical Nano motors.
- WS registration/auth/heartbeat/reconnect is implemented; semantic commands
  still use the old inbound HTTP path. TLS/network-change/media acceptance,
  clean-image provisioning, physical voice/motion, and soak/restore checks
  remain open. Use the [acceptance matrix](docs/phase-22-23.md#satisfactory-run-acceptance-matrix).

## Machine-specific continuation notes

- The Nano is the sole embodiment host; losing it makes the robot inert.
  Its daemon and embodiment container were left running by owner choice on
  2026-09-23. **Recheck current state** before assuming that still holds.
  Starting the daemon wakes/moves the robot: owner presence and supervision
  are required. `--check` must never start hardware.
- Nano uses host-networked embodiment on 8100 and the loopback daemon on
  8000. Existing `.env` copies can retain obsolete bridge URLs after code
  defaults change. See [deployment](docs/deployment.md#robot-host-and-jetson-nano).
- The homelab's existing `ovms` container previously served
  `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` at `localhost:8000`; re-query
  `/v1/models` to confirm. Leave unrelated running services alone during tests.
- Hosted credentials were placed in gitignored `deploy/homelab/.env.local`
  (`TOGETHER_API_KEY` and `CLOUD_LLM_*`). Check presence without printing
  values. Temporary verification credentials/stacks were removed in prior
  sessions; no permanent owner account is implied by a successful test.
- Optional caches previously available: espeak at
  `/tmp/espeak-extract/usr/bin`, Playwright under
  `~/.npm/_npx/e41f203b7505f1fb/node_modules`, Chromium under
  `~/.cache/ms-playwright`. They may disappear; setup and sandbox socket
  caveats are centralized in [development](docs/development.md).

Before implementation, inspect `git status`, recent commits, and any existing
diff. The previous hardware work involved a separate Nano-side session;
verify raw device identity when accepting future remote hardware reports.
