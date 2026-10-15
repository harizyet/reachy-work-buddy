# Documentation

Start here to find the authoritative page for a topic. Directory READMEs
point into this index rather than maintaining parallel instructions. This page
is an index: it names and links, and does not carry status. Phase status lives
in the [roadmap](plan.md#6-implementation-roadmap), current limits in
[project state](project-state.md), and evidence in the dated records.

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
Phases 0–29 are its historical ledger; remaining work follows the
[forward roadmap (Phases 30+)](plan.md#forward-roadmap-phases-30). The plans
below keep their original numbers (remaining work from 27 continues as Phase 31,
25 as 32, 26 as 33, 28 as 34, 29's extensions as 35, and open 22b–24g rows as 30).
A plan states requirements; it is not a claim that the feature works. Completed
phase pages are historical design records, not operating instructions, and change
only to correct facts or links. The mixed 22–23 page retains open acceptance matrices.

### Platform, robot and conversation

- [Phase 22a/22b and 23](phase-22-23.md): deployment, physical acceptance, migrations, SecretStore, Google Accounts.
- [Phase 24a](phase-24a.md): search-assisted, freshness-aware assistant.
- [Phase 24b](phase-24b.md): structured command and intent authorization (natural language only suggests; structured commands or existing consent paths authorize).
- [Phases 24c–24d](phase-24cd.md): robot conversation workflow and its physical proof.
- [Phase 24e](phase-24e.md): conversation hardening and the deferred 24d rows ([prerequisites for Phase 25](phase-24e.md#prerequisites-for-phase-25)).
- [Phase 24f](phase-24f.md): motion conformance and local conversational embodiment.
- [Phase 24g](phase-24g.md): local wake admission and silent false-trigger rejection.
- [Phase 25](phase-25.md): tiered owner verification and progressive trust.
- [Phase 32](phase-32.md): shared voice identity, phone-first (32A); robot recognition (32B) deferred. [32A.0 inventory](verification/phase-32a0-inventory-2026-10-15.md).
- [Phase 26](phase-26.md): security hardening and assurance.
- [Phase 30](phase-30.md): platform stabilization and acceptance.
- [Phase 37](phase-37.md) and [shadow semantic router](shadow-router.md): shadow-first semantic routing and argument validation.
- [Phase 38](phase-38.md): alarm clock and presence-gated delivery.
- [Phase 39](phase-39.md): persona-aware responses and action receipts.
- [Hybrid intent routing](verification/intent-router-2026-10-11.md) (not a numbered phase; [deployment](verification/intent-router-deployment-2026-10-11.md), [task-reply privacy fix](verification/task-privacy-named-note-2026-10-11.md), [privacy remediation and SearXNG rotation](verification/privacy-remediation-and-searxng-rotation-2026-10-11.md)).
- [Phase 29](phase-29.md): coding agent supervisor ([service reference](reference/services.md#coding-agent-service-phase-29)).
- [Phase 28](phase-28.md): embodied meeting secretary.

### Meetings, documents and notes

- [Phase 27](phase-27.md): meeting intelligence foundation (upload, transcription, diarization, alignment; see [ADR 0025](adr/0025-speech-inference-service.md)).
- [Phase 31](phase-31.md): meeting analysis, decisions, open questions, owner-reviewed actions.
- [Phase 41](phase-41.md): speaker names and reviewed transcript corrections.
- [Phase 42](phase-42.md): three-tier model escalation and the model manager.
- [Phase 43](phase-43.md): meeting deletion, summaries, minutes and meeting context.
- [Phase 49](phase-49.md): Intelligent Notepad processing ([verification](verification/phase-49-notepad-processing-2026-10-11.md), [grounding defect record](verification/record-reference-grounding-fix-2026-10-11.md)).
- [Phase 50](phase-50.md): MinerU-backed document intelligence ([ADR 0034](adr/0034-source-evidence-and-derived-artifacts.md)).
- [Phase 52](phase-52.md): spoken "begin meeting recording" in Android voice mode.
- [Phase 53](phase-53.md): multimodal meeting intelligence (slides aligned to a meeting).
- [Phase 54](phase-54.md): Identify Speakers.
- [Phase 55](phase-55.md): supervised meeting-minutes email.

### Knowledge layer (Phase 44 and 48)

- [Phase 44](phase-44.md): Reachy Brain, the semantic knowledge and context layer; the [closure report](phase-44-closure-report.md) is its authoritative handover.
- [Phase 48](phase-48.md): activation and operational acceptance of the Phase 44 flags.
- [Phase 44H](phase-44h.md): security regression cases and the unclaimed-action boundary; [receipt-boundary proposal](phase-44h-receipt-boundary-proposal.md).
- Design and plans: [44E plan](phase-44e-plan.md), [engineering completion plan](phase-44-engineering-completion-plan.md), [deployment-readiness proposal](phase-44-deployment-readiness-proposal.md), [44F implementation proposal](phase-44f-implementation-proposal.md) and [slices](phase-44f-implementation-slices.md), [offline model-cache proposal](phase-44-model-cache-proposal.md), [shadow readiness assessment](phase-44e-shadow-readiness-assessment.md), [shadow telemetry policy](phase-44e-selective-shadow-telemetry-policy.md).
- Groundedness and selective answering: [groundedness design](phase-44-groundedness-milestone-design.md), [dev11 ablation](phase-44-groundedness-dev11-ablation-2026-10-12.md), [dev12 protocol](phase-44-groundedness-dev12-protocol.md), [scoped readiness protocol](phase-44-scoped-readiness-protocol.md), [section coverage protocol](phase-44e-section-coverage-protocol.md), [dev8 acceptance protocol](phase-44e-dev8-acceptance-protocol.md), [selective-answering protocol](phase-44-selective-answering-protocol.md), [Stage B design](phase-44-selective-stage-b-design.md), [B-1 integration plan](phase-44-selective-answering-integration-plan.md).
- Scorer research (stopped 2026-10-10): [v2 validation protocol](phase-44-scorer-v2-validation-protocol.md), [v3 readiness plan](phase-44-scorer-v3-validation-readiness.md), [v3 formal protocol](phase-44-scorer-v3-formal-validation-protocol.md); rubric v5 absence semantics in [Stage B design 3.1](phase-44-selective-stage-b-design.md#31-absence-semantics-rubric-v5-2026-10-10-evidence-contract) and the [rubric addendum](../services/companion-core/benchmarks/answer_quality/selective/adjudication_rubric_v5_addendum.md).
- dev16 acceptance (not run): [deterministic criteria](phase-44-dev16-deterministic-criteria-draft.md), [execution checklist](phase-44-dev16-execution-checklist.md), [preflight](phase-44-dev16-preflight.md), [freeze recommendation](phase-44-dev16-freeze-recommendation.md), [freeze command](phase-44-dev16-freeze-command.md).

### Infrastructure and clients

- [Phase 45](phase-45.md): database connections and PgBouncer.
- [Phase 46](phase-46.md): least-privilege database roles (plan only).
- [Phase 47](phase-47.md): React web platform and Brain visualization.
- [Phase 40](phase-40.md): Android companion app ([ADR 0029](adr/0029-android-companion-app.md), [client README](../clients/android/README.md)).
- [Phase 51](phase-51.md): Home dashboard and the extended daily briefing.
- Backups (plan only): [hardening proposal](postgres-backup-hardening-proposal.md), [implementation plan](postgres-backup-implementation-plan.md).
- [Jarvis baseline](jarvis-baseline.md): upstream reuse/reference notes.

## Architecture decisions

ADRs are binding design decisions. Later dated amendments take precedence
over the original decision where they explicitly change it. Each ADR carries
its own status line.

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
| [0025](adr/0025-speech-inference-service.md) | Generalized speech inference service |
| [0026](adr/0026-semantic-routing-and-argument-validation.md) | Semantic routing with deterministic argument validation (only the shadow stage accepted) |
| [0027](adr/0027-alarms-and-presence-gated-delivery.md) | Alarms with presence-gated, privacy-aware delivery |
| [0028](adr/0028-persona-responses-and-action-receipts.md) | Persona-aware responses and authoritative action receipts |
| [0029](adr/0029-android-companion-app.md) | Native Android companion app |
| [0030](adr/0030-meeting-speaker-names-and-reviewed-corrections.md) | Meeting speaker names and reviewed transcript corrections |
| [0031](adr/0031-three-tier-local-model-escalation.md) | Three-tier model escalation (lifecycle manager accepted; tier routing proposed) |
| [0032](adr/0032-meeting-outputs-and-context.md) | Meeting deletion, generated outputs and meeting context |
| [0033](adr/0033-llm-assisted-read-routing.md) | LLM-assisted read routing with deterministic grounding |
| [0034](adr/0034-source-evidence-and-derived-artifacts.md) | Source evidence and derived artifacts |
| [0035](adr/0035-read-only-ics-calendar-and-meeting-reminders.md) | Read-only ICS calendar feed, event classification and meeting recording reminders |
| [0036](adr/0036-home-dashboard.md) | Home dashboard and the extended daily briefing |
| [0037](adr/0037-multimodal-meeting-evidence-and-slide-alignment.md) | Multimodal meeting evidence and slide alignment |
| [0038](adr/0038-meeting-speaker-identification.md) | Owner-confirmed meeting speaker identities |
| [0039](adr/0039-supervised-meeting-minutes-email.md) | Supervised meeting-minutes email through a dedicated sender |
| [0040](adr/0040-verified-processing-provenance-in-email.md) | Verified processing provenance and fixed disclosures in meeting email |
| [0041](adr/0041-shared-voice-identity.md) | Shared voice identity (phone-first): evidence, not authority; one capture path; encrypted profiles; HTTP transport limits |

## Verification records

Dated evidence, not startup instructions or current health checks. Each
record states what was and was not verified. Newest areas first; within an
area, oldest first.

### Meetings, email and calendar (2026-10)

- Calendar feed: [verification](verification/ics-calendar-meeting-reminders-2026-10-13.md), [deployment](verification/ics-calendar-deployment-2026-10-13.md), [screens and sync](verification/ics-calendar-screens-and-sync-2026-10-13.md), [navigation](verification/ics-calendar-navigation-2026-10-13.md), [sync deployment](verification/ics-calendar-sync-deployment-2026-10-13.md).
- Home dashboard: [verification](verification/home-dashboard-2026-10-13.md), [deployment](verification/home-dashboard-deployment-2026-10-14.md). [Overview vLLM card deployment](verification/overview-vllm-card-deployment-2026-10-13.md).
- [Voice recording command (Phase 52)](verification/voice-meeting-recording-2026-10-14.md).
- Phase 53: [verification](verification/phase-53-multimodal-meetings-2026-10-14.md), [document types](verification/phase-53-document-types-2026-10-14.md), [UAT rehearsal](verification/phase-53-uat-rehearsal-2026-10-14.md), [deployment](verification/phase-53-deployment-2026-10-14.md).
- Phase 54: [verification](verification/phase-54-speaker-identification-2026-10-14.md), [deployment](verification/phase-54-deployment-2026-10-14.md).
- Phase 55: [verification](verification/phase-55-meeting-minutes-email-2026-10-14.md), [deployment](verification/phase-55-deployment-2026-10-14.md). Processing provenance (ADR 0040): [verification](verification/processing-provenance-disclosure-2026-10-15.md), [deployment](verification/processing-provenance-deployment-2026-10-15.md).
- Phase 32: [32A.0 inventory](verification/phase-32a0-inventory-2026-10-15.md) (G0 approved), [Android slice verification](verification/phase-32a-android-2026-10-15.md), [GV protocol](verification/phase-32a-gv-protocol.md), [physical-phone UAT checklist](verification/phase-32a-uat-checklist.md).
- Phase 31: [local build](verification/phase-31-meeting-analysis-2026-10-12.md), [extraction quality](verification/phase-31-extraction-quality-2026-10-12.md), [model diagnostic](verification/phase-31-model-diagnostic-2026-10-12.md), [deployment preparation](verification/phase-31-deployment-preparation-2026-10-12.md), [deployment](verification/phase-31-deployment-2026-10-12.md), [trial preparation](verification/phase-31-trial-preparation-2026-10-12.md), [trial step A](verification/phase-31-trial-step-a-deployment-2026-10-12.md), [trial step B](verification/phase-31-trial-step-b-activation-2026-10-12.md).
- [Android, meetings and alarms 2026-10-07/08](verification/clients-meetings-alarms-2026-10-07.md); [meeting corrections benchmark](verification/meeting-corrections-benchmark-2026-10-07.md).
- Phase 27: [foundation](verification/phase-27-foundation-2026-09-30.md), [long-audio transport](verification/phase-27-long-audio-2026-09-30.md).

### Documents and notes (2026-10-11 and 12)

- Phase 50: [A spike](verification/phase-50a-mineru-spike-2026-10-11.md), [B library](verification/phase-50b-document-library-2026-10-12.md), [C integration](verification/phase-50c-integration-2026-10-12.md), [E conversation](verification/phase-50e-document-conversation-2026-10-12.md), [H/D/G/J summaries and UI](verification/phase-50h-summaries-and-documents-ui-2026-10-12.md), [deployment](verification/phase-50-deployment-2026-10-12.md), [extraction inspector](verification/phase-50-extraction-inspector-2026-10-12.md) and [deployment](verification/phase-50-inspector-deployment-2026-10-12.md), [chat picker](verification/phase-50-chat-document-picker-2026-10-12.md) and [deployment](verification/phase-50-chat-picker-deployment-2026-10-12.md), [Android Documents and history isolation](verification/phase-50-android-documents-and-history-isolation-2026-10-12.md) and [deployment](verification/phase-50-history-isolation-deployment-2026-10-12.md), [worker recovery](verification/phase-50-worker-recovery-2026-10-12.md), [summary buttons deployment](verification/documents-summary-buttons-deployment-2026-10-12.md), [web top-nav deployment](verification/web-top-nav-deployment-2026-10-12.md).
- Phase 49: [processing](verification/phase-49-notepad-processing-2026-10-11.md), [deployment](verification/phase-49-deployment-2026-10-11.md), [activation](verification/phase-49-activation-2026-10-11.md), [Brain provenance](verification/phase-49-brain-provenance-2026-10-11.md) and [deployment](verification/phase-49-brain-provenance-deployment-2026-10-11.md). [Note folder tags deployment](verification/note-tags-deployment-2026-10-11.md).

### Knowledge layer (Phase 44 and 48)

- Phase 44A: [contracts and migration 026](verification/phase-44a-2026-10-08.md), [holdout case review](verification/phase-44a-holdout-case-review-2026-10-08.md), [rehearsal](verification/phase-44a-rehearsal-2026-10-08.md), [deployment](verification/phase-44a-deployment-2026-10-08.md).
- Phase 44B: [index and outbox](verification/phase-44b-2026-10-08.md), [rehearsal](verification/phase-44b-rehearsal-2026-10-08.md), [deployment](verification/phase-44b-deployment-2026-10-08.md), [contention plan](verification/phase-44b-contention-test-plan-2026-10-08.md) and [result](verification/phase-44b-contention-result-2026-10-08.md), [indexing trial](verification/phase-44b-indexing-trial-2026-10-08.md), [re-trial](verification/phase-44b-indexing-retrial-2026-10-08.md), [workload trial plan](verification/phase-44b-indexing-workload-trial-plan-2026-10-10.md) and [result](verification/phase-44b-indexing-workload-trial-2026-10-09.md).
- Phase 44D: [development comparison](verification/phase-44d-dev-2026-10-08.md), [first look at the frozen holdout](verification/phase-44d-first-look-2026-10-08.md).
- Phase 44E: [development](verification/phase-44e-development-2026-10-09.md), [first look](verification/phase-44e-first-look-2026-10-09.md), [follow-up](verification/phase-44e-followup-2026-10-09.md), [holdout review](verification/phase-44e-holdout-review-2026-10-09.md), [blind review](verification/phase-44e-blind-review-2026-10-10.md), [conflict detector](verification/phase-44e-conflict-detector-2026-10-10.md), [shadow readiness](verification/phase-44e-shadow-readiness-2026-10-10.md), [selective integration](verification/phase-44e-selective-integration-2026-10-10.md), [selective shadow](verification/phase-44e-selective-shadow-2026-10-10.md), [failure taxonomy](verification/phase-44e-failure-taxonomy-2026-10-11.md), [answer-quality improvements](verification/phase-44e-answer-quality-2026-10-11.md), [evidence sufficiency](verification/phase-44e-evidence-sufficiency-2026-10-12.md), [larger-model comparison](verification/phase-44e-larger-model-comparison-2026-10-12.md), [dev8 acceptance](verification/phase-44e-dev8-acceptance-2026-10-12.md), [section coverage](verification/phase-44e-section-coverage-2026-10-12.md).
- Phase 44F and 44H: [44F implementation](verification/phase-44f-implementation-2026-10-10.md), [44H boundary deployment](verification/phase-44h-boundary-deployment-2026-10-12.md), [Phase 44 deployment](verification/phase-44-deployment-2026-10-10.md).
- Groundedness and selective answering: [dev12 acceptance](verification/phase-44-groundedness-dev12-acceptance-2026-10-12.md), [dev14 scoped readiness](verification/phase-44-scoped-readiness-dev14-2026-10-12.md), [Stage A](verification/phase-44-selective-stage-a-2026-10-12.md), [adjudication](verification/phase-44-selective-adjudication-2026-10-13.md), [B-1](verification/phase-44-selective-stage-b1-2026-10-13.md) and [extension](verification/phase-44-selective-stage-b1-extension-2026-10-13.md), [qualified-object tightening](verification/phase-44-selective-b1-qualified-object-2026-10-14.md), [scorer v2 validation](verification/phase-44-scorer-v2-validation-2026-10-13.md), [scorer v3 development](verification/phase-44-scorer-v3-development-2026-10-14.md), [corpus v5 coverage](verification/phase-44-corpus-v5-coverage-2026-10-15.md), [scorer v3 formal validation](verification/phase-44-scorer-v3-formal-validation-2026-10-10.md), [I-1/I-2](verification/phase-44-selective-i1-i2-2026-10-10.md), [I-2 follow-up](verification/phase-44-selective-i2-followup-2026-10-10.md), [final development pass](verification/phase-44-selective-final-dev-pass-2026-10-10.md), [P0 smoke test](verification/phase-44-dev16-p0-smoke-test-2026-10-10.md), [P0 reproducibility correction](verification/phase-44-dev16-p0-reproducibility-correction-2026-10-10.md), [corrected P0 smoke test](verification/phase-44-dev16-p0-smoke-test-corrected-2026-10-10.md).
- Phase 48: [48A review activation](verification/phase-48a-review-activation-2026-10-10.md), [48B eligibility](verification/phase-48b-capture-eligibility-2026-10-10.md), [48B trial log](verification/phase-48b-capture-trial-2026-10-10.md), [48C baseline](verification/phase-48c-baseline-2026-10-10.md), [48D indexing](verification/phase-48d-indexing-activation-2026-10-10.md), [48E retrieval](verification/phase-48e-retrieval-validation-2026-10-10.md), [48F selective shadow](verification/phase-48f-selective-shadow-2026-10-10.md).

### Infrastructure and web (2026-10-01 to 10-08)

- Phase 45: [connection architecture](verification/phase-45-2026-10-08.md), [homelab cutover](verification/phase-45e-deployment-2026-10-08.md).
- Phase 47: [47A](verification/phase-47a-2026-10-08.md), [47B](verification/phase-47b-2026-10-08.md), [47C](verification/phase-47c-2026-10-08.md), [47D](verification/phase-47d-2026-10-08.md) and [deployment](verification/phase-47d-deployment-2026-10-08.md), [47F](verification/phase-47f-2026-10-08.md).
- [Operator UI reorganization](verification/operator-ui-2026-10-01.md) (later rebuilt in React, Phase 47).
- [Phase 30 closure checks](verification/phase-30-2026-10-04.md).

### Robot, voice and platform (2026-09)

- [Implementation history](verification/history.md); [Phase 22a bring-up](verification/phase-22-bring-up.md); [physical inventory](verification/phase-22-inventory-2026-09-22.md).
- Phase 22b: [first motion](verification/phase-22b-first-motion-2026-09-23.md), [camera](verification/phase-22b-camera-2026-09-24.md).
- Phase 23: [foundation](verification/phase-23-foundation-2026-09-23.md), [Accounts](verification/phase-23-accounts-2026-09-23.md), [Desktop OAuth](verification/phase-23b-desktop-oauth-2026-09-24.md).
- [Phase 24a search](verification/phase-24a-search-assisted-2026-09-24.md); [24b command authorization](verification/phase-24b-command-authorization-2026-09-24.md); [24c robot voice](verification/phase-24c-conversation-2026-09-24.md); [24d physical conversation](verification/phase-24d-conversation-2026-09-24.md).
- Phase 24e: [correctness set](verification/phase-24e-correctness-2026-09-25.md), [palm stop](verification/phase-24e-palm-stop-2026-09-25.md), [physical run](verification/phase-24e-physical-2026-09-25.md).
- Phase 24f: [source trace](verification/phase-24f-source-2026-09-25.md), [conformance](verification/phase-24f-conformance-2026-09-25.md), [physical 2026-09-26](verification/phase-24f-physical-2026-09-26.md), [physical 2026-09-27](verification/phase-24f-physical-2026-09-27.md).
- Phase 24g: [detector bench](verification/phase-24g-detector-bench-2026-09-27.md), [first physical run](verification/phase-24g-physical-2026-09-27.md).
- [Clock, reply labelling and small.en](verification/clock-routing-stt-physical-2026-09-27.md); [STT model comparison](verification/stt-model-comparison-2026-09-26.md); [portal search and animation controls](verification/portal-controls-2026-09-25.md).
- Phase 25: [foundation and benchmark portal](verification/phase-25-foundation-2026-09-28.md), [speaker-verification smoke test](verification/phase-25a1-voice-benchmark-2026-09-28.md).

## Deployment records

Every production deployment has its own record, linked from its area above
(for example [Phase 55](verification/phase-55-deployment-2026-10-14.md),
[provenance](verification/processing-provenance-deployment-2026-10-15.md),
[Phase 54](verification/phase-54-deployment-2026-10-14.md),
[Phase 53](verification/phase-53-deployment-2026-10-14.md),
[Home dashboard](verification/home-dashboard-deployment-2026-10-14.md),
[calendar feed](verification/ics-calendar-deployment-2026-10-13.md),
[Phase 31](verification/phase-31-deployment-2026-10-12.md),
[Phase 50](verification/phase-50-deployment-2026-10-12.md),
[Phase 49](verification/phase-49-deployment-2026-10-11.md),
[Phase 44](verification/phase-44-deployment-2026-10-10.md)). A record holds
the image IDs, backup, rollback assets, Phase 48 boundary and downtime of one
deployment; [HANDOVER](../HANDOVER.md) lists only the rollback assets still kept.
The schema-revision history is in
[deployment](deployment.md#schema-upgrades-and-credential-keys).

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
| What was actually verified, image IDs, backups, rollback assets of one deployment | Dated verification or deployment record | Brief result/link |
| Agent conduct and required reading | AGENTS.md | Link |
| Current task, open owner items, kept rollback assets, transient host state | HANDOVER.md | Never a changelog; finished work moves to its phase page or record |

Update the canonical home first. Keep source/config files authoritative for
exact defaults and schemas, and label future plans versus implemented behavior.
Retain useful historical evidence without presenting obsolete instructions as
current setup. When moving a section, update all repository links and anchors.
