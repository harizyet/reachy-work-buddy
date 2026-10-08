# Documentation

Start here to find the authoritative page for a topic. Directory READMEs
point into this index rather than maintaining parallel instructions.

## Guides and reference

| I want to… | Read |
|---|---|
| Install or operate the homelab/robot | [Deployment](deployment.md) |
| Use chat, calls, settings, and telepresence | [Operator guide](operator-guide.md) |
| Set up development, run tests, or debug dependencies/builds | [Development](development.md) |
| Find service ownership, APIs, and implementation files | [Service reference](reference/services.md) |
| Exercise conversation/work-data APIs on a test stack | [Workflow examples](reference/workflow-examples.md) |
| Check current deployment limits and open acceptance | [Project state](project-state.md) |
| Understand scope, releases, and what comes next | [Technical plan and roadmap](plan.md) |
| Resume an agent session | [Handover](../HANDOVER.md), then [agent instructions](../AGENTS.md) |

## Plans

The [roadmap](plan.md#6-implementation-roadmap) owns phase order and status.
Phases 0–29 are its historical ledger; remaining work is sequenced by
dependency in the [forward roadmap (Phases 30+)](plan.md#forward-roadmap-phases-30),
and the phase plans below keep their original numbers (remaining work from
27 continues as Phase 31, 25 as 32, 26 as 33, 28 as 34, 29's extensions as 35,
and open 22b–24g rows as 30).
Detailed future requirements remain in their dedicated plans; they are not
claims that those features already work. Paths stay stable: completed phase
records are historical design/implementation references. The mixed 22–23 document retains open acceptance matrices.
Use the ledger for current status, deployment for procedures, and dated
verification records for empirical results. Historical records change only to
correct facts or links, not to track each new phase dependency.

- [Phase 22a/22b and Phase 23](phase-22-23.md): deployment, physical acceptance,
  migrations, SecretStore, and Google Accounts.
- [Phase 24a](phase-24a.md): search-assisted, freshness-aware assistant.
- [Phase 24b](phase-24b.md): structured command and intent authorization —
  explicit structured commands or existing consent/confirmation paths
  authorize consequential actions; natural-language intent only suggests
  them, never authorizes.
- [Phases 24c–24d](phase-24cd.md): complete the robot conversation workflow,
  then prove the core physical conversation workflow; deferred acceptance
  continues in 24e.
- [Phase 24e](phase-24e.md): conversation hardening (adaptive end of turn,
  search-trigger fixes, a correctness set) and the 24d rows the owner
  deferred, plus Nano diagnostics. Its
  [24e conversation-path prerequisites](phase-24e.md#prerequisites-for-phase-25) gated
  Phase 25; they passed or were waived by the owner on 2026-09-27, and
  the phase closed by re-scope.
- [Phase 24f](phase-24f.md): motion conformance and local conversational
  embodiment; closed by re-scope with deferred physical acceptance.
- [Phase 24g](phase-24g.md): local wake admission and silent false-trigger
  rejection; requirements and acceptance scenarios.
- [Phase 25](phase-25.md): tiered owner verification and progressive trust
  (voice verification, then visual verification, gating voice access by
  request sensitivity).
- [Phase 26](phase-26.md): security hardening and assurance — inserted
  2026-09-28 between owner verification and meeting transcription to
  review and harden the whole system, not just the new biometric surface,
  before it expands.
- [Phase 27](phase-27.md): meeting intelligence — upload-first processing,
  speaker-attributed transcripts, evidence-linked notes, reviewed actions
  and searchable meeting history; independent of physical embodiment.
  27.1–27.3 (durable job store/worker, upload API, transcription and
  diarization sidecars wired via [ADR 0025](adr/0025-speech-inference-service.md)'s
  client interfaces, operator-ui recording and detail view) landed
  2026-09-30; the live service path passed a short single-speaker smoke test.
  Real meeting acceptance remains open. Alignment
  (27.4) landed 2026-10-07; analysis and retrieval (27.5 onward) not started.
- [Phase 28](phase-28.md): embodied meeting secretary — owner-present
  companion, then physical secretary attendance, then bounded delegation;
  virtual/cloud attendance is deferred. (Formerly Phase 27; renumbered
  2026-09-28.)
- [Phase 29](phase-29.md): coding agent supervisor — a `coding-agent-service`
  runs and observes containerized Claude Code (then Codex) sessions behind a
  provider-neutral contract, feeding lifecycle/usage events into Reachy's
  existing notification pipeline; observation and relay only, no automatic
  permission approval or push/merge. 29.1–29.3 (contracts/session store,
  real-Docker container runner, real Claude Code provider) implemented
  2026-10-01, plus an early encrypted-credential store and operator-UI card
  for provider credentials (29.19); deployed to the homelab the same day.
  Revised 2026-10-02 to be subscription-first: acceptance uses the Claude
  Pro/Max path, and the next step is characterizing owner-input detection.
  See
  [service reference](reference/services.md#coding-agent-service-phase-29-planned).
- [Phase 37](phase-37.md): semantic routing and argument validation — stage sequence and gates for replacing the phrase-matcher fall-through; decision in [ADR 0026](adr/0026-semantic-routing-and-argument-validation.md).
- [Phase 38](phase-38.md): alarm clock and presence-gated delivery — stage sequence and gates; decision in [ADR 0027](adr/0027-alarms-and-presence-gated-delivery.md).
- [Phase 39](phase-39.md): persona-aware responses and action receipts — stage sequence and gates; decision in [ADR 0028](adr/0028-persona-responses-and-action-receipts.md).
- [Phase 40](phase-40.md): Android companion app (built through version 0.14.0) — stage sequence and gates; decision in [ADR 0029](adr/0029-android-companion-app.md).
- [Phase 41](phase-41.md): meeting speaker names and reviewed transcript corrections — stage sequence and gates; decision in [ADR 0030](adr/0030-meeting-speaker-names-and-reviewed-corrections.md).
- [Phase 42](phase-42.md): three-tier model escalation — stage sequence and gates; decision in [ADR 0031](adr/0031-three-tier-local-model-escalation.md).
- [Phase 43](phase-43.md): meeting deletion, summaries, minutes and meeting context — decision in [ADR 0032](adr/0032-meeting-outputs-and-context.md).
- [Phase 44](phase-44.md): Reachy Brain, a semantic knowledge and context layer over memory, documents, meetings and planner data (proposed; 44A schema reconciliation written, no code).
- [Phase 45](phase-45.md): database connection architecture and pooling (shared pools, PgBouncer evaluation, direct admin path); audit, shared-pool refactor, PgBouncer evaluation and failure exercises done on disposable infrastructure ([evidence](verification/phase-45-2026-10-08.md)); homelab cutover done ([deployment record](verification/phase-45e-deployment-2026-10-08.md)).
- [Phase 46](phase-46.md): least-privilege database roles (plan only, written 2026-10-08; no credential or production change authorised).
- [Phase 47](phase-47.md): React web platform and Brain visualization. Owner decisions D1 to D6 recorded 2026-10-08; 47A (foundation at `/web/`) and 47B (the whole operator UI in React) built and merged to main, not deployed, awaiting the owner's user test; 47C (3D Brain, synthetic data) in progress.
- [Phase 44E plan](phase-44e-plan.md): context builder and end-to-end answer-quality evaluation with the local 7B (plan for review; no code).
- [Shadow semantic router](shadow-router.md): shadow-mode router, extractor and validator that only records what it would propose; contract, flags, trial procedure, retention and evidence.
- [Phase 30](phase-30.md): platform stabilization and acceptance — verify the
  no-alert-pose wake build, add the visible-false-activations metric, run the
  held-out 24g session and triage the open 22b/22c/24e/24f rows.
- [Jarvis baseline](jarvis-baseline.md): upstream reuse/reference notes.

## Architecture decisions

ADRs are binding design decisions. Later dated amendments take precedence
over the original decision where they explicitly change it.

| ADR | Decision |
|---|---|
| [0001](adr/0001-service-boundaries.md) | Service ownership |
| [0002](adr/0002-agent-session.md) | Cross-channel sessions |
| [0003](adr/0003-embodiment-command-api.md) | Semantic embodiment API |
| [0004](adr/0004-offline-fallback.md) | Offline fallback and Nano topology |
| [0006](adr/0006-response-routing.md) | Mode/privacy response routing |
| [0010](adr/0010-calendar.md) | Calendar storage and read surface |
| [0011](adr/0011-destructive-action-consent.md) | Consent and undo guarantees |
| [0012](adr/0012-call-reachy-webrtc.md) | Conversational WebRTC calls |
| [0013](adr/0013-remote-telepresence.md) | Remote camera/audio/control |
| [0014](adr/0014-interruption-intelligence.md) | Proactive interruption policy |
| [0015](adr/0015-daily-briefing.md) | Briefing orchestration |
| [0016](adr/0016-operator-ui.md) | Owner login, dashboard, runtime inference |
| [0017](adr/0017-web-chat-channel.md) | Web chat and Telegram polling health |
| [0018](adr/0018-hybrid-llm-routing.md) | Role-based local/cloud inference |
| [0019](adr/0019-robot-initiated-hub-connectivity.md) | Robot-initiated connectivity |
| [0020](adr/0020-schema-and-secrets.md) | Versioned schema and core-owned credentials |
| [0021](adr/0021-google-accounts.md) | Owner-bound read-only Google accounts |
| [0022](adr/0022-web-search-grounding.md) | Web-search grounding for the generic conversation branch |
| [0023](adr/0023-robot-voice-conversation.md) | Robot microphone/speaker conversation transport |
| [0024](adr/0024-owner-recognition-trust.md) | Owner recognition trust boundary (evidence/trust/authorization split) |
| [0025](adr/0025-speech-inference-service.md) | Generalized speech inference service (target architecture and migration path) |
| [0026](adr/0026-semantic-routing-and-argument-validation.md) | Semantic routing with deterministic argument validation (shadow accepted; promotion proposed) |
| [0027](adr/0027-alarms-and-presence-gated-delivery.md) | Alarms with presence-gated, privacy-aware delivery |
| [0028](adr/0028-persona-responses-and-action-receipts.md) | Persona-aware responses and authoritative action receipts |
| [0029](adr/0029-android-companion-app.md) | Native Android companion app |
| [0030](adr/0030-meeting-speaker-names-and-reviewed-corrections.md) | Meeting speaker names and reviewed transcript corrections |
| [0031](adr/0031-three-tier-local-model-escalation.md) | Three-tier model escalation (proposed) |
| [0032](adr/0032-meeting-outputs-and-context.md) | Meeting deletion, generated outputs and meeting context |

## Verification records

These are dated evidence, not startup instructions or current health checks.

- [Phase 47B 2026-10-08](verification/phase-47b-2026-10-08.md): the operator UI in React (169 component tests, 100 browser tests against a real hub, hub characterisation tests, session-isolation mutation checks, bugs found, bundle growth). Not deployed.

- [Phase 47A 2026-10-08](verification/phase-47a-2026-10-08.md): React foundation tests (Vitest, Playwright against a real hub), hub image build, bundle sizes, API compatibility. Not deployed.

- [Phase 44D first look at the frozen holdout 2026-10-08](verification/phase-44d-first-look-2026-10-08.md): B1a and B1b frozen then scored once each; paired
  case-level differences, zero exposure, development-only investigation of lexical versus hybrid.

- [Phase 44D development comparison 2026-10-08](verification/phase-44d-dev-2026-10-08.md): lexical, hybrid and reranked retrieval against the baselines on the
  development split, with authorization, latency, CPU and memory. Holdout not scored; nothing wired.

- [Phase 44B rehearsal 2026-10-08](verification/phase-44b-rehearsal-2026-10-08.md): migration 027 on a restored production copy, trigger overhead,
  storage, rollback, the real write paths and the retention review. Nothing deployed.

- [Phase 44B 2026-10-08](verification/phase-44b-2026-10-08.md): the knowledge index, transactional outbox, worker, reconciliation and retrieval-time
  revalidation on disposable Postgres; mutation checks; the embedding load measurement. Local only.

- [Phase 44B production deployment 2026-10-08](verification/phase-44b-deployment-2026-10-08.md): migration 027 on the homelab with indexing off,
  backup, rollback readiness and smoke tests. [Contention test plan](verification/phase-44b-contention-test-plan-2026-10-08.md) and [result](verification/phase-44b-contention-result-2026-10-08.md) (run 2026-10-08, no abort). [Indexing trial 2026-10-08](verification/phase-44b-indexing-trial-2026-10-08.md): production backfill, validation, early revert and the connection-limit finding.

- [Phase 44A production deployment 2026-10-08](verification/phase-44a-deployment-2026-10-08.md): migration 026 on the homelab, backup
  and restore check, rollback assets, thirteen smoke checks, downtime; the robot gate is pending.

- [Phase 44A migration 026 rehearsal 2026-10-08](verification/phase-44a-rehearsal-2026-10-08.md): live read-only preflight, an isolated
  restored copy migrated with the real keyring, the rollback proven, disposal; nothing on the live stack changed.

- [Phase 44A 2026-10-08](verification/phase-44a-2026-10-08.md): knowledge-layer contracts, migration 026 on a disposable database,
  the pinned Ossie export, hub forwarding of classification and the retrieval benchmark baseline; the failing tests
  classified as baseline or regression. Fixture evidence only; nothing deployed.

- [Android, meetings and alarms 2026-10-07/08](verification/clients-meetings-alarms-2026-10-07.md):
  deploys with their backups, the real silent recording, emulator checks (including the
  unfolded Fold layout and the phone alarm with the app killed), test counts and what is
  still unverified.

- [Operator UI reorganization](verification/operator-ui-2026-10-01.md): feature
  settings tabs, dashboard, meeting sidebar and durable web records; Chromium
  fixtures, in-process API and isolated real-Postgres checks, with one existing
  hub voice-test failure recorded. Not deployed.

- [Implementation history](verification/history.md): phase-level verification,
  including the real hosted-cloud follow-up.
- [Phase 22a bring-up](verification/phase-22-bring-up.md): consolidated backend,
  launcher, WS, Nano, and simulator results, with unverified items explicit.
- [Physical inventory](verification/phase-22-inventory-2026-09-22.md): original
  raw hardware/runtime findings and subsequent dependency/device/memory checks.
- [Phase 22b first motion](verification/phase-22b-first-motion-2026-09-23.md):
  first real WSS registration and first-ever real-motor command, which found
  a head-motion hardware fault; session stopped for physical inspection.
- [Phase 22b camera](verification/phase-22b-camera-2026-09-24.md): a daemon
  error-state finding and recovery, first real camera capture, and the
  subsequent refactor to reachy_mini's recommended LOCAL media backend
  (LOCAL-backend captures since exercised on the Nano; deliberate fresh-scene
  acceptance still open).

- [Phase 23 foundation](verification/phase-23-foundation-2026-09-23.md): migrations,
  SecretStore, isolated database recovery and built-image checks.

- [Phase 23 Accounts](verification/phase-23-accounts-2026-09-23.md): OAuth, read-only
  adapters, browser and database checks; external production gates remain open.

- [Phase 23b Desktop OAuth](verification/phase-23b-desktop-oauth-2026-09-24.md):
  loopback helper transport, fixture and real-Postgres checks; no live
  Google Desktop-client consent run performed.

- [Phase 24a search-assisted assistant](verification/phase-24a-search-assisted-2026-09-24.md):
  fixture/deterministic-stub-model checks plus a real self-hosted SearXNG
  container live-verified against real internet results; hosted cloud
  provider and running-homelab-stack production acceptance remain open.

- [Phase 24c robot voice conversation](verification/phase-24c-conversation-2026-09-24.md):
  automated, browser and real-process checks with a simulated robot
  microphone, real Whisper, OVMS and TTS; no physical robot.

- [Phase 24d physical conversation acceptance](verification/phase-24d-conversation-2026-09-24.md):
  the real Nano/Reachy conversation run passed (context, latency, owner
  usability, cold-reboot recovery); closed by owner re-scope, with the
  remaining matrix rows and Nano diagnostics deferred to Phase 24e; motor
  inspection remains the owner's separate follow-up.

- [Phase 24e correctness set](verification/phase-24e-correctness-2026-09-25.md):
  in-process run of the voice-turn correctness set on the local model;
  passed the owner's pre-agreed threshold, with grounded-number and
  statement-length failures recorded.

- [Phase 24e open-palm stop](verification/phase-24e-palm-stop-2026-09-25.md):
  in-process tests, the real MediaPipe model on still photos and an amd64
  image build; the Nano build and physical rows are open.

- [Phase 24f motion source trace](verification/phase-24f-source-2026-09-25.md):
  pinned 1.8.4 daemon source plus a mockup-sim probe; overlapping REST moves
  both run, real UUID stop exists, `running` follows wake-up; no robot.

- [Phase 24f physical run](verification/phase-24f-physical-2026-09-26.md):
  motion-off baseline, gestures on (daemon stop 500 reset the next request;
  fixed); the acceptance rows continued on 2026-09-27.

- [Phase 24f physical run, 2026-09-27](verification/phase-24f-physical-2026-09-27.md):
  first real once-per-boot recovery (motor power off), `b36736d` swap,
  step C stopped by the owner; recorded gestures replaced by silent poses,
  then the step C rerun with them passed, as did wobble, stops, palm stop
  and switch-off; a standby wake leaves the camera socket stale.

- [Clock, reply labelling and small.en on the robot](verification/clock-routing-stt-physical-2026-09-27.md):
  clock answers, a public "start the morning" reply and the known
  mishearings pass; open-ended replies take 7.8–9.9 s (model length).

- [Phase 24g detector cost on the Nano](verification/phase-24g-detector-bench-2026-09-27.md):
  file-driven benchmark; openWakeWord takes 23% of one core continuously,
  YAMNet 30 ms per 0.96 s patch; the community Edge Impulse "Hey Reachy"
  model is cheap but caught 4 of 15 synthetic phrases; after a live session
  with the owner it was selected as the initial detector.

- [Phase 24g first physical run](verification/phase-24g-physical-2026-09-27.md):
  first wake/pose runs and later calibration; the held-out attempt found
  a pause-timeout failure, with fresh acceptance still owed after its fix.

- [Phase 24f motion conformance](verification/phase-24f-conformance-2026-09-25.md):
  Nano versions, predeclared tolerances, supervised REST vs SDK run; paths
  agree; robot stops 2–5° short on both, normal vs fault still open.

- [Phase 25 foundation and benchmark portal](verification/phase-25-foundation-2026-09-28.md):
  consolidated local checks and encrypted-capture backend deployment; browser
  and biometric acceptance remain open.

- [Phase 25a.1 speaker-verification pipeline smoke test](verification/phase-25a1-voice-benchmark-2026-09-28.md):
  dev-box only, SpeechBrain ECAPA-TDNN scoring pipeline confirmed sane
  (same/different speaker separation) on the model card's own example
  clips; no owner/non-owner recording, homelab run, or AASIST anti-spoof
  evaluation yet.

- [Phase 24b command authorization](verification/phase-24b-command-authorization-2026-09-24.md):
  isolated-fixture checks for the retired substring matcher's replacement
  (structured `/reachy` commands, the fail-closed suggestion classifier,
  Telegram alias/menu registration, and operator-UI command autocomplete/
  action buttons); no live Telegram bot run or real robot actuation
  performed.

- [Portal search and animation controls](verification/portal-controls-2026-09-25.md):
  homelab redeploy, live search/browser checks and powered-off robot UI;
  Nano deployment and physical animation remain open.

- [STT model comparison](verification/stt-model-comparison-2026-09-26.md):
  synthetic noisy-speech comparison of Whisper models on the homelab CPU;
  small.en is more accurate but adds about 0.55 s per turn.

- [Phase 27.1 foundation](verification/phase-27-foundation-2026-09-30.md):
  automated companion-core/reachy-hub checks for meeting upload/tracking/
  restart-recovery and the owner-authenticated proxy, plus a live homelab
  speech smoke test. Real multi-speaker meeting and browser acceptance remain open.

- [Phase 27 long-audio transport](verification/phase-27-long-audio-2026-09-30.md):
  bounded audio-transfer regressions and isolated real-model 65-minute WAV
  checks; representative meeting quality and live rollout remain open.

## Where information belongs

| Information | Canonical home | Elsewhere |
|---|---|---|
| Project introduction and navigation | Root README | Short link |
| Phase status and delivery ledger | Roadmap | One-line status/link |
| Future scope and exit criteria | Active phase plans linked from the roadmap | Link |
| Completed design/implementation narrative | Historical phase records | Link; do not use as operating instructions |
| Current deployment limits, hardware issues, cross-phase acceptance | Project state | Brief link; dated proof stays in verification |
| How to install, configure, upgrade, operate | Deployment guide | Link; env templates keep variable defaults |
| How a person uses the application | Operator guide | Link |
| How to develop, test, or troubleshoot tooling | Development guide | Link |
| Service/API navigation | Service reference; code/OpenAPI for exact schemas | Link |
| Why a boundary or policy exists | ADR | Link rather than copied decision text |
| What was actually verified | Dated verification record | Brief result/link |
| Agent conduct and required reading | AGENTS.md | Link |
| Current task, next session steps, transient host state | HANDOVER.md | Do not turn it into a changelog or duplicate project state |

Update the canonical home first. Keep source/config files authoritative for
exact defaults and schemas, and label future plans versus implemented behavior.
Retain useful historical evidence without presenting obsolete instructions as
current setup. When moving a section, update all repository links and anchors.
