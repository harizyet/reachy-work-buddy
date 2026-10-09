# Project state

Snapshot: 2026-10-08 (the sections on Phase 30 onward and the hardware limits were last reviewed 2026-10-02). This page owns current deployment and cross-phase
acceptance limits. The [phase ledger](plan.md#6-implementation-roadmap)
owns phase status and scope; dated [verification records](README.md#verification-records)
own evidence. This snapshot is not a live health check.

## Current priority and next gates

Phases 0–29 are the historical ledger; remaining work follows the
[forward roadmap](plan.md#forward-roadmap-phases-30) (30 stabilization, then
31 meetings and 32 owner recognition, 33 security, 34 embodied secretary,
35 optional coding-agent extensions, 36 production readiness).

**Now (Phase 30):** raising the head on every wake detection annoyed and
removing the raise gave no feedback (both tried 2026-10-02), so the head raise
is becoming confidence-gated: a separate `WAKE_ALERT_THRESHOLD`, with the
number chosen from measured score distributions (30.1b), not yet set. Next:
Nano deployment and calibration, then the occupied-room wake check, the
visible-false-activations metric and the fresh 24g held-out run (deferred by the
owner on 2026-09-28); see [phase-30](phase-30.md).

**Next (Phase 31):** browser checks and a real 30–60 minute meeting through
[Phase 27](phase-27.md) (alignment now exists), then analysis and retrieval. **After
(Phase 32):** [Phase 25](phase-25.md) owner-recognition data collection,
calibration and the real verifier; its next gates are browser verification of
benchmark capture and consenting owner/non-owner recordings. Phase 25 work runs
with conversational motion off until 24f's deferred acceptance passes. Its
[24e prerequisites](phase-24e.md#prerequisites-for-phase-25) passed or were
waived by the owner; Nano diagnostics remain deferred. See
[HANDOVER](../HANDOVER.md) for concrete next-session steps.

**Shadow semantic router (Phase 37, enabled 2026-10-05):** a router-only shadow trial of up to 500 accepted turns runs in the homelab; it never executes a tool or changes a reply, and extraction is offline. Nothing is promoted: evaluation (blind grading, report) is next, and every later stage is a separate owner decision. Recorded trial files are destroyed when evaluation and testing are complete (no other deadline). See [phase-37](phase-37.md), [shadow-router](shadow-router.md) and [ADR 0026](adr/0026-semantic-routing-and-argument-validation.md).

## Deployment and production acceptance

The homelab stack is a dev/test deployment, not production-accepted. Use
[the supported launcher and upgrade procedures](deployment.md); preserve
its database and leave unrelated services running. The designated production
Nano has narrowly approved unattended-motion exceptions; those do not make
the homelab or the full system production-accepted. See the exact
[robot operating boundaries](deployment.md#robot-host-and-jetson-nano).
Last-reported host revisions and temporary paths belong in [HANDOVER](../HANDOVER.md).

## Implemented but not fully accepted

- **Semantic knowledge and selective answering (44):** deployed, all with
  indexing, retrieval and shadow OFF: migrations 026 (source sensitivity) and
  027 (knowledge index and outbox), and the 44H unclaimed-action boundary in
  core. Robot acceptance of the 44A deployment, a browser pass and Telegram
  receipt of the smoke reminder were still pending when recorded in
  [HANDOVER](../HANDOVER.md). **Not deployed:** the selective-answering work
  (Stage B-1, a deterministic cited answer layer, source and tests only, wired
  nowhere), 44F, retrieval and shadow rollout. The scorer-v3 research that was
  meant to validate a severe-hallucination detector **failed its formal
  validation and was stopped on 2026-10-10**; the scorer is research-only and
  not used for any enforcement. B-1 is the primary release candidate but is
  **not ready for formal acceptance** (free-text question decomposition, a
  gold-independent relation registry and coverage are open). See
  [Phase 44](phase-44.md), the [integration plan](phase-44-selective-answering-integration-plan.md)
  and the [I-1/I-2 record](verification/phase-44-selective-i1-i2-2026-10-10.md).
- **Meeting intelligence (27):** upload, transcription and diarization reached
  ALIGNING in the real homelab with a short synthetic single-speaker clip.
  Real multi-speaker/30–60 minute acceptance, resource measurements,
  browser recording/detail checks and explicit row/audio survival across
  restart remain open. Speech-service token authentication is implemented
  but unset in the reported deployment. Since 2026-10-07 (deployed, database
  revision 025) a meeting is aligned (a speaker per line), checked for silent
  recording gaps, playable, editable line by line, titled and described
  automatically, and summarised from the local model; see
  [the 2026-10-07 evidence](verification/clients-meetings-alarms-2026-10-07.md). The
  owner's one real recording is two thirds silent (the phone captured nothing),
  so alignment and summary quality on a clean multi-speaker recording are still
  unjudged. Analysis and retrieval remain unimplemented. File-backed transfers and longer configurable inference
  waits have [isolated 65-minute synthetic checks](verification/phase-27-long-audio-2026-09-30.md);
  these changes have not been rolled out to the live stack. See [evidence](verification/phase-27-foundation-2026-09-30.md)
  and the [next diagnostic run](phase-27.md#before-alignment-representative-speech-acceptance).

- **Android app and phone-facing screens (40, 38.8/38.9):** built through app
  0.14.0 and verified on an emulator (including the Fold's inner-screen size and a phone
  alarm firing with the app killed and the hub down), with the hub features deployed. Not
  accepted on a physical phone or Pixel Fold. Open: spoken replies on the owner's
  phone (reported silent after 0.12.1, not reproduced; 0.12.2 hardened playback),
  the phone alarm in Doze and against a real "robot unavailable" or "nobody detected"
  outcome, and the web screens against the production hub. Alarm times are read in the
  assistant's time zone but shown in the device's. See
  [the evidence](verification/clients-meetings-alarms-2026-10-07.md).
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
  The 24e correctness findings remain limitations below. See
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
  accepted, and renewed usability acceptance on 2026-09-27. The phase
  closed by owner re-scope. The owner waived the 30-minute session and
  held-turn cancellation, and the Nano diagnostics are deferred
  ([24e record](verification/phase-24e-physical-2026-09-25.md),
  [2026-09-27 record](verification/clock-routing-stt-physical-2026-09-27.md)).
- **Conversational motion (24f):** silent listening/thinking poses, speech
  wobble, stops, arbitration and switch-off passed physically. The
  features are off by default and switched on per robot in the portal.
  The 30-minute run with motion, mid-reply switch-off, stop while homing
  and the 2–5° shortfall are deferred
  ([record](verification/phase-24f-physical-2026-09-27.md)).

- **Wake admission (24g):** silent false-wake return and home on admission
  have physical evidence. Calibration rejected all 25 false-trigger cases;
  the first held-out attempt admitted only 3/4 genuine attempts. The timeout
  was increased to 6 s, but a fresh held-out run is still owed
  ([record](verification/phase-24g-physical-2026-09-27.md#admission-fix-and-calibration-follow-up)).
- **Owner recognition (25):** encrypted, opt-in benchmark capture is deployed
  and backend-verified; browser recording/capture, sizes, deletion and export
  remain unverified. Speaker wiring and the disabled sensitivity gate exist,
  but there is no real verifier or operational template store. The
  [foundation record](verification/phase-25-foundation-2026-09-28.md) and
  [speaker smoke test](verification/phase-25a1-voice-benchmark-2026-09-28.md)
  do not establish recognition accuracy.
- **Privacy routing follow-up:** the shorter context window (`56f65dc`)
  was deployed but still needs a live calendar-question/follow-up check.
  Trusted mode has [local test evidence](verification/portal-controls-2026-09-25.md#settings-and-routing-follow-up-2026-09-27);
  live UI/robot acceptance was not recorded.
  Its scope is defined by the
  [ADR 0006 amendment](adr/0006-response-routing.md#trusted-mode-exempts-the-privacy-veto-2026-09-27).

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
  "2Q"). TV or other speech is taken as a turn; that's a known limit.
  [Phase 24g](phase-24g.md) addresses false wake admission; Phase 25 retains
  speaker attribution and rejection within an open session. Acoustic echo
  is not addressed.
- First LOCAL camera frames can take 9–12 s while GStreamer loads plugins.
  Docker 20.10.7 seccomp prevents the external scanner from spawning;
  the documented workaround loads plugins in-process.
- Clean-image Nano provisioning and the remaining TLS/network-change,
  soak and restore acceptance have not been established by a conversation run.

Hardware findings and daemon/camera observations are preserved in the
[24d evidence](verification/phase-24d-conversation-2026-09-24.md) and
[camera record](verification/phase-22b-camera-2026-09-24.md).
