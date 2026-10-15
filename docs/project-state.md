# Project state

Snapshot: 2026-10-15 (the Phase 30 priority text and the hardware limits were last reviewed 2026-10-02; everything else in this page 2026-10-15). This page owns current deployment and cross-phase
acceptance limits. The [phase ledger](plan.md#6-implementation-roadmap)
owns phase status and scope; dated [verification records](README.md#verification-records)
own evidence. This snapshot is not a live health check.

## Current priority and next gates

**Latest (2026-10-15):** the homelab database is at `037_processing_provenance`; every feature branch is merged to `main`. The meeting features through shared minutes (Phases 31, 53, 54, 55), the Home dashboard, the calendar feed and Android 0.19.0 are deployed and mostly owner-accepted (see the bullets below). The owner's order for documents remains Phase 50 (deployed and accepted; remaining: 50F federation once the Phase 48 window permits, then Proxmox last). Open owner items, kept rollback assets and machine state are in [HANDOVER](../HANDOVER.md).

Phases 0–29 are the historical ledger; remaining work follows the
[forward roadmap](plan.md#forward-roadmap-phases-30) (30 stabilization, 31 meetings,
32 owner recognition, 33 security, 34 embodied secretary, 35 optional coding-agent
extensions, 36 production readiness).

**Phase 30 (open, last reviewed 2026-10-02):** raising the head on every wake detection annoyed and
removing the raise gave no feedback (both tried 2026-10-02), so the head raise
is becoming confidence-gated: a separate `WAKE_ALERT_THRESHOLD`, with the
number chosen from measured score distributions (30.1b), not yet set. Next:
Nano deployment and calibration, then the occupied-room wake check, the
visible-false-activations metric and the fresh 24g held-out run (deferred by the
owner on 2026-09-28); see [phase-30](phase-30.md).

**Phase 32 (revised 2026-10-15, planning; [phase-32](phase-32.md)):** 32A shared voice identity, phone-first
(Android enrollment/verification, meeting speaker suggestions); 32B robot recognition deferred. G0 approved 2026-10-15; 32A.V (speaker sidecar, encrypted profiles, enrollment and verification routes, migration 038) is built and tested on the unmerged branch `feature/phase-32a-voice-identity`, with nothing deployed, no calibration and no Android client yet ([ADR 0041](adr/0041-shared-voice-identity.md)). Underlying contracts: [Phase 25](phase-25.md)
owner-recognition data collection, calibration and the verifier. Phase 25 work runs with conversational
motion off until 24f's deferred acceptance passes; its
[24e prerequisites](phase-24e.md#prerequisites-for-phase-25) passed or were waived by the owner.

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

- **Document intelligence (50): DEPLOYED and owner-accepted 2026-10-12 on the MS-01** (schema `031_documents`, `DOCUMENT_LIBRARY_ENABLED=true`, the CPU-only `document-worker` with MinerU). Upload, processing, scoped cited Q&A, summaries, Advanced-tier escalation, the extraction inspector, the chat document picker, per-chat conversation-history isolation, worker OOM recovery and Android Documents (app 0.17.0) are live and were accepted by the owner. **Not started:** 50F federated retrieval (waits for the Phase 48 window), the rest of 50J, and the Proxmox worker move. Known minor item: core's reconcile loop rewrites a ready document's `updated_at` each cycle. Backups must include the `document-source` volume. See [Phase 50](phase-50.md), [deployment](verification/phase-50-deployment-2026-10-12.md) and [HANDOVER](../HANDOVER.md).
- **Meeting intelligence (27, 31, 41–43, 53–55): DEPLOYED through schema 037; used on real recordings.** Upload, transcription, diarization, alignment, silence check, playback and line edits, titles, summaries and minutes, deletion, speaker names, owner-confirmed speaker identity (54, accepted), structured analysis with owner-confirmed actions (31, trial flag on), slide alignment against attached documents (53, web only, flag on), and the supervised minutes email with verified provenance (55 and ADR 0040, accepted after UAT). **Open:** a real 30–60 minute multi-speaker meeting reviewed by the owner (the Phase 31 acceptance criterion; the owner's first recording was two thirds silent), Phase 53 acceptance on their own deck and meeting, a real Gmail send with the provenance text (the local-only sentence has never come from a real production recording), resource measurements, and speech-service token authentication (implemented, unset in the reported deployment). File-backed transfers have [isolated 65-minute checks](verification/phase-27-long-audio-2026-09-30.md). Evidence: [27](verification/phase-27-foundation-2026-09-30.md), [31](verification/phase-31-deployment-2026-10-12.md), [53](verification/phase-53-deployment-2026-10-14.md), [54](verification/phase-54-deployment-2026-10-14.md), [55](verification/phase-55-deployment-2026-10-14.md), [provenance](verification/processing-provenance-deployment-2026-10-15.md). See [Phase 31](phase-31.md), [53](phase-53.md), [54](phase-54.md), [55](phase-55.md).
- **Calendar feed, Home dashboard and meeting-recording command (ADR 0035/0036, Phases 51 and 52): DEPLOYED, merged and owner-accepted (2026-10-13 to 15).** Schema `033_calendar_feed` ([record](verification/ics-calendar-deployment-2026-10-13.md), [sync](verification/ics-calendar-sync-deployment-2026-10-13.md)); core `GET /home` and the hub proxy, no migration ([record](verification/home-dashboard-deployment-2026-10-14.md)). The production feed URL and the owner's addresses are set and tested; the browser check, the persona location for weather and the phone bottom bar were tested working (2026-10-15, not itemised). Phase 52 is Android only: voice and typed recording command and short-recording handling work on a phone ([phase-52](phase-52.md)). Open: the Phase 48 counters of one segment that were not saved (accepted gap, in the deployment record).
- **Notepad (49) and note folders:** Phase 49 processing is deployed (migration 029, 2026-10-11) and **enabled** (`NOTEPAD_PROCESSING_ENABLED=true`); note folder tags (migration 030) are deployed. The web folder fix and the Android 0.16.0 processing panel were confirmed by the owner on 2026-10-12; no separate record. Task-query routing ("what's my task for next week?") was confirmed by the owner on 2026-10-12. See [Phase 49](phase-49.md) and the [note-tags record](verification/note-tags-deployment-2026-10-11.md).

- **Hybrid intent router (not a numbered phase): DEPLOYED 2026-10-11 and ENABLED (`INTENT_ROUTER_ENABLED=true`); owner acceptance of everyday use is open.** The local 7B picks one existing read handler for natural-language questions about the owner's records; it is read-only, fail-closed for questions that need the owner's records, and deterministic about dates and access ([ADR 0033](adr/0033-llm-assisted-read-routing.md)). The same rollout fixed task-reply privacy (replies were labelled from the question and ignored the channel ceiling) and the title-only named note, and rotated the SearXNG secret ([privacy and rotation record](verification/privacy-remediation-and-searxng-rotation-2026-10-11.md)). Core runs commit `41a81a0`. Known limits, none a deployment blocker: substring search, titles containing write verbs, questions with no personal cue still reach ordinary chat, `tasks.capture` and `tasks.complete` ceilings verified by tests only. Rollback images before 2026-10-11 12:59 UTC carry the old privacy defect. Phase 48 cohorts: boundaries 4 and 5 in the [trial log](verification/phase-48b-capture-trial-2026-10-10.md).

- **Semantic knowledge and selective answering (44, 48): engineering complete, partly activated, research acceptance outstanding.** Migrations 026 to 028 are applied and the 44H unclaimed-action boundary is live in core. Phase 48 activated, in stages each with a rollback, memory-candidate review and supervised capture, indexing, retrieval and the selective shadow (checked against the running core and `.env` 2026-10-15: all on); selective *answering* is absent from Compose and production, as is the older B1a `KNOWLEDGE_SHADOW_ENABLED` shadow. The scorer-v3 research failed its formal validation and was stopped on 2026-10-10; the scorer is research-only and enforces nothing. Stage B-1 deterministic cited answering is the release candidate but is not ready for formal acceptance (dev15: 294/307 atoms, 160/173 questions fully correct, 0 unsupported claims; dev16 not frozen or run; no independent human review). Deferred by decision: 44C and 44G. The authoritative handover is the [Phase 44 closure report](phase-44-closure-report.md); see also [Phase 44](phase-44.md), [Phase 48](phase-48.md) and the [B-1 integration plan](phase-44-selective-answering-integration-plan.md).
- **Android app and phone-facing screens (40, 38.8/38.9):** built through app
  0.19.0 (Calendar, five destinations with Home, the voice recording command, Identify speakers, Share minutes). 0.16.0 and 0.17.0 (note folders, the processing panel, Documents and the chat
  picker) were accepted by the owner on a physical phone on 2026-10-12, and 0.19.0 (including the newest tier-tags build) on 2026-10-14 and 15 (reported, not itemised), and 0.14.0 and
  earlier were verified on an emulator (including the Fold's inner-screen size and a phone
  alarm firing with the app killed and the hub down), with the hub features deployed
  (see [Phase 40](phase-40.md)). Not accepted on a Pixel Fold. Open: spoken replies on the owner's
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
