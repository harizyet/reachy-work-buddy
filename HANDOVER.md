# Handover

Current session snapshot, updated 2026-09-23. Read [AGENTS.md](AGENTS.md)
before working. Durable instructions belong in the [documentation index](docs/README.md),
not repeated in this file.

## Current work

Phases 0–21 and 22a are implemented. The owner explicitly deferred physical
acceptance (22b) and chose Phase 23 next: versioned migrations and SecretStore
before production read-only Gmail/Calendar Accounts. Follow the
[Phase 23 plan](docs/phase-22-23.md); Phase 24 recognition and Phase 25 meeting
minutes are planning only. No migration framework or secret encryption is
implemented yet, and current LLM credentials are plaintext in Postgres.

Documentation was consolidated this session: root/directory READMEs are entry
points; deployment, development, operator use, and service reference each have
one guide under `docs/`. Phase history moved to verification records, stale
handover chronology was removed, and internal links were checked. No runtime
code, deployment settings, containers, or hardware were changed for this cleanup.

## Verification and open acceptance

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
- The latest recorded full Python suite in the bring-up thread was 345 tests;
  this documentation-only session did not rerun application tests. Historical
  counts are not claims about a freshly verified current deployment.

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
