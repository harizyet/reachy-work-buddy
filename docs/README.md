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
| Understand scope, releases, and what comes next | [Technical plan and roadmap](plan.md) |
| Resume an agent session | [Handover](../HANDOVER.md), then [agent instructions](../AGENTS.md) |

## Plans

The [roadmap](plan.md#6-implementation-roadmap) owns phase order and status.
Detailed future requirements remain in their dedicated plans; they are not
claims that those features already work.

- [Phase 22a/22b and Phase 23](phase-22-23.md): deployment, physical acceptance,
  migrations, SecretStore, and Google Accounts.
- [Phase 24](phase-24.md): owner recognition and voice access control.
- [Phase 25](phase-25.md): meeting transcription and minutes.
- [Phase 26](phase-26.md): embodied meeting secretary — owner-present companion, then physical secretary attendance, then bounded delegation; virtual/cloud attendance is deferred.
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

## Verification records

These are dated evidence, not startup instructions or current health checks.

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
  (code/tests done, real-hardware build/run still unverified).

- [Phase 23 foundation](verification/phase-23-foundation-2026-09-23.md): migrations,
  SecretStore, isolated database recovery and built-image checks.

- [Phase 23 Accounts](verification/phase-23-accounts-2026-09-23.md): OAuth, read-only
  adapters, browser and database checks; external production gates remain open.

- [Phase 23b Desktop OAuth](verification/phase-23b-desktop-oauth-2026-09-24.md):
  loopback helper transport, fixture and real-Postgres checks; no live
  Google Desktop-client consent run performed.

## Where information belongs

| Information | Canonical home | Elsewhere |
|---|---|---|
| Project introduction and navigation | Root README | Short link |
| Phase status, scope, exit criteria | Roadmap and linked phase plans | One-line status/link |
| How to install, configure, upgrade, operate | Deployment guide | Link; env templates keep variable defaults |
| How a person uses the application | Operator guide | Link |
| How to develop, test, or troubleshoot tooling | Development guide | Link |
| Service/API navigation | Service reference; code/OpenAPI for exact schemas | Link |
| Why a boundary or policy exists | ADR | Link rather than copied decision text |
| What was actually verified | Dated verification record | Brief result/link |
| Agent conduct and required reading | AGENTS.md | Link |
| Current task, open work, transient environment | HANDOVER.md | Do not turn it into a changelog |

Update the canonical home first. Keep source/config files authoritative for
exact defaults and schemas, and label future plans versus implemented behavior.
Retain useful historical evidence without presenting obsolete instructions as
current setup. When moving a section, update all repository links and anchors.
