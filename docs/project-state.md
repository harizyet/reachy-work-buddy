# Project state

Snapshot: 2026-09-25. This page owns current deployment and cross-phase
acceptance limits. The [phase ledger](plan.md#6-implementation-roadmap)
owns phase status and scope; dated [verification records](README.md#verification-records)
own evidence. This snapshot is not a live health check.

## Current priority and next gates

[Phase 24e](phase-24e.md) and [Phase 24f](phase-24f.md) closed by owner
re-scope on 2026-09-27. Their work is deployed, and most rows passed on
the robot. 24e deferred four items:
- the supervised 30-minute session;
- cancelling a held turn on the robot;
- item 4, the Nano diagnostics;
- renewed owner acceptance of usability.
24f deferred its remaining motion rows.

Phase 25 remains blocked until the
[24e conversation-path prerequisites](phase-24e.md#prerequisites-for-phase-25)
PASS on hardware. The 30-minute session and held-turn cancellation are
still among them. Phase 25 runs with conversational motion off until
24f's deferred rows pass. Phases 25–27 remain planned.

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
- **Conversation hardening (24e):** deployed and run on the robot with the
  owner. These passed:
  - normal conversation and timing: 22 short questions, p50 3.75 s with
    small.en;
  - turn handling with adaptive end of turn, including long utterances
    with pauses;
  - stop and expiry, privacy, consent, session continuity and recovery;
  - open-palm stop;
  - clock answers and reply labelling;
  - the correctness set.
  Open-ended questions take about 8 s to first audio, which the owner
  accepted. The phase closed by owner re-scope; the 30-minute session,
  held-turn cancellation, Nano diagnostics and renewed usability
  acceptance are deferred
  ([24e record](verification/phase-24e-physical-2026-09-25.md),
  [2026-09-27 record](verification/clock-routing-stt-physical-2026-09-27.md)).
- **Conversational motion (24f):** silent listening/thinking poses, speech
  wobble, stops, arbitration and switch-off passed physically. The
  features are off by default and switched on per robot in the portal.
  The 30-minute run with motion, mid-reply switch-off, stop while homing
  and the 2–5° shortfall are deferred
  ([record](verification/phase-24f-physical-2026-09-27.md)).

## Known hardware and software limitations

- Earlier companion/daemon runs during 24d showed `stewart_5` overheating
  and anomalous tracking (lag and drift). The owner subsequently reported
  successful zeroing and rotation tests using the official Pollen Reachy Mini
  Testbench, with no observed issue. The 24f conformance run on 2026-09-25
  then found that REST and the SDK (Testbench) path command the same poses,
  but the robot misses them on both. Several motors stop about 3° short,
  and the owner saw no head motion for an encoder-reported 16° yaw while
  hearing the motors
  ([record](verification/phase-24f-conformance-2026-09-25.md#analysis)).
  The head camera confirms the head moves as far as the encoders report,
  so this is not a mechanical decoupling, and the owner's "no visible
  motion" was a perception limit. The stock proportional-only gains (PID
  300/0/0) predict a direction-dependent shortfall like this, and the
  Testbench tolerates 5–15°, so normal versus fault is open.
  Pose-dependent motion stays disabled.
- An unplanned Nano power loss on 2026-09-25 at 02:38:20Z reported
  `TEGRA_POWER_ON_RESET`, with no undervoltage logged. The 2026-09-26
  ~02:35Z power-on reset was the owner switching it off. The owner reports
  a known issue with the shared USB hub: plugging or removing a device can
  reset the hub. The owner accepts this for development: production will
  power the Nano from a barrel-jack supply instead. Such resets
  can leave recently written files empty. A 2026-09-26 git object was
  repaired from the remote, so check `git fsck` after one.
  Its RTC loses time across power-offs; pre-NTP journal timestamps are stale.
  Power/time diagnostics are in 24e.
- Daemon 1.8.4 wake-up can fail with `time value is out of range [0,1]`.
  The once-per-boot recovery ran for real on 2026-09-27 (motor power off):
  one restart, then a stop on the second error
  ([record](verification/phase-24f-physical-2026-09-27.md#boot-with-motor-power-off-first-real-automatic-recovery)).
  Recovery from a wake-up error specifically is still fake-tested only.
- Fixed 2026-09-27: the daemon recreates its camera socket on every media
  start, including a standby wake, and a bind of the socket file used to
  leave the camera and palm stop without frames until embodiment
  restarted. The container now binds the host's `/tmp`, and the backend
  reopens the camera pipeline. This was verified with a no-motion media
  release/acquire on nano-1
  ([record](verification/phase-24f-physical-2026-09-27.md#camera-socket-fix-on-nano-1)).
  A real standby wake has not been repeated since.
- The local model passed the correctness set but still sometimes
  misreports numbers from search results and answers statements at length
  ([record](verification/phase-24e-correctness-2026-09-25.md)). small.en
  fixed the known mishearings, but proper nouns can still fail ("Tokyo" as
  "2Q"). TV or other speech is taken as a turn; that's a known limit,
  deferred to Phase 25. Acoustic echo is not addressed.
- First LOCAL camera frames can take 9–12 s while GStreamer loads plugins.
  Docker 20.10.7 seccomp prevents the external scanner from spawning;
  the documented workaround loads plugins in-process.
- Clean-image Nano provisioning and the remaining TLS/network-change,
  soak and restore acceptance have not been established by a conversation run.

Hardware findings and daemon/camera observations are preserved in the
[24d evidence](verification/phase-24d-conversation-2026-09-24.md) and
[camera record](verification/phase-22b-camera-2026-09-24.md).
