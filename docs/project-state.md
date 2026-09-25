# Project state

Snapshot: 2026-09-25. This page owns current deployment and cross-phase
acceptance limits. The [phase ledger](plan.md#6-implementation-roadmap)
owns phase status and scope; dated [verification records](README.md#verification-records)
own evidence. This snapshot is not a live health check.

## Current priority and next gates

[Phase 24e](phase-24e.md) is the next priority, with agreed scope but no
implementation yet. Start with the ADR 0023 amendment in its
[implementation sequence](phase-24e.md#implementation-sequence).
Phase 24d closed by owner re-scope: conversation, context, latency and
usability passed; deferred rows were not passed.

Phase 25 remains blocked until the
[24e conversation-path prerequisites](phase-24e.md#prerequisites-for-phase-25)
PASS on hardware. Quality/search/STT tuning and Nano diagnostics can proceed
independently. Session continuity is still required 24e work, but is not a
Phase 25 start gate. Phases 25–27 remain planned.

## Deployment and production acceptance

The homelab stack is a dev/test deployment, not production-accepted. Use
[the supported launcher and upgrade procedures](deployment.md); preserve
its database and leave unrelated services running. The designated production
Nano has narrowly approved unattended-motion exceptions; those do not make
the homelab or the full system production-accepted. See the exact
[robot operating boundaries](deployment.md#robot-host-and-jetson-nano).
Last-reported host revisions and temporary paths belong in [HANDOVER](../HANDOVER.md).

## Implemented but not fully accepted

- **Physical platform (22b/22c):** named behaviours were owner-accepted despite
  tracking imprecision; audio and camera have run on hardware. LOCAL-backend
  captures now work on the Nano, but a deliberate fresh-scene check is still
  owed. Endurance, outage/reconnect, backup restore, privacy/consent and
  channel acceptance remain open in the
  [platform matrix](phase-22-23.md#satisfactory-run-acceptance-matrix).
  See [camera evidence](verification/phase-22b-camera-2026-09-24.md).
- **Google Accounts (23/23b):** migrations, SecretStore, Web and Desktop OAuth
  and read-only adapters are fixture/browser/database verified. Real-account
  consent/read/refresh/restart/revoke/reconnect, intended-audience checks and
  the Google-enabled physical repeat remain open. No live Desktop-helper
  consent run is recorded. See [Accounts evidence](verification/phase-23-accounts-2026-09-23.md)
  and [Desktop evidence](verification/phase-23b-desktop-oauth-2026-09-24.md).
- **Search (24a):** SearXNG and hosted-provider rotation have live evidence;
  this does not establish production acceptance or answer correctness.
  Search-trigger misfires and the correctness set continue in 24e. See
  [search evidence and addenda](verification/phase-24a-search-assisted-2026-09-24.md).
- **Command authorization (24b):** structured commands, suggestions and UI
  buttons are fixture/browser verified. Live Telegram command and physical
  standby/resume acceptance remain open. See
  [command evidence](verification/phase-24b-command-authorization-2026-09-24.md).
- **Conversation (24c/24d):** the real robot passed normal conversation,
  all three context checks and the agreed latency budgets (non-search
  p50 2.5 s / p95 6.9 s; search at most 19.3 s). Cold-reboot recovery passed.
  The [results matrix](verification/phase-24d-conversation-2026-09-24.md#results)
  distinguishes these from deferred privacy, consent, cancellation, recovery,
  turn handling, continuity and sustained-use checks now owned by 24e.

## Known hardware and software limitations

- Earlier companion/daemon runs during 24d showed `stewart_5` overheating
  and anomalous tracking (lag and drift). The owner subsequently reported
  successful zeroing and rotation tests using the official Pollen Reachy Mini
  Testbench, with no observed issue. A persistent hardware fault is therefore
  not established. [Phase 24f](phase-24f.md#1-motion-conformance) will compare
  the deployed motion path against the pinned official reference before
  drawing further conclusions.
- An unplanned Nano power loss at 02:38:20Z reported `TEGRA_POWER_ON_RESET`,
  with no undervoltage logged. A supply dropout is suspected, not proven.
  Its RTC loses time across power-offs; pre-NTP journal timestamps are stale.
  Power/time diagnostics are in 24e.
- Daemon 1.8.4 wake-up can fail with `time value is out of range [0,1]`.
  The installed once-per-boot recovery has only fake-tested restart and
  second-error paths; no real error-triggered restart is yet recorded.
- Adaptive end of turn (24e item 1) is implemented and tested in process
  and with real Silero/Whisper on simulated audio, not yet on the robot; the
  deployed robot still splits turns at 700 ms pauses until it is rebuilt.
  The 24e item 2 search-rule fixes and STT name prompt are tested in process
  only and not deployed. The local model passed the correctness set but
  still sometimes misreports numbers from search results and answers
  statements at length ([record](verification/phase-24e-correctness-2026-09-25.md)). Acoustic echo and deliberate
  silence/noise handling still need physical acceptance.
- First LOCAL camera frames can take 9–12 s while GStreamer loads plugins.
  Docker 20.10.7 seccomp prevents the external scanner from spawning;
  the documented workaround loads plugins in-process.
- Clean-image Nano provisioning and the remaining TLS/network-change,
  soak and restore acceptance have not been established by a conversation run.

Hardware findings and daemon/camera observations are preserved in the
[24d evidence](verification/phase-24d-conversation-2026-09-24.md) and
[camera record](verification/phase-22b-camera-2026-09-24.md).
