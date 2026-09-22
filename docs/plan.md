# Reachy Work Companion — Technical Plan

Document status: Working technical plan. Update architecture decisions and
exit criteria as implementation evidence accumulates.

The canonical, binding decisions from this plan are captured as ADRs in
[docs/adr/](adr/). This file is the full narrative plan (goals, roadmap,
release targets, risks) for reference.

## 1. Executive Summary

The project will be built as a new modular system that selectively reuses
proven components and design ideas from the open-source Jarvis project
rather than becoming a permanent hard fork. Jarvis remains a useful
reference because it already implements a continuous 30 Hz presence loop,
Silero VAD, local faster-whisper STT, streaming ElevenLabs TTS, Reachy
control, multi-user memory, and governance-oriented subsystems. [1]

The target system is office-first. Home Assistant and smart-home
functionality are out of scope. The primary experience is a persistent work
companion that can converse through Reachy, route private or long responses
to a phone, continue the same session over Telegram or a WebRTC phone-call
interface, use calendar/email/tasks/RAG, and remain physically expressive
even when the central agent is unavailable.

Heavy services run in the homelab. Reachy retains a small local embodiment
runtime for low-latency motion, idle behaviour, watchdog/safety functions,
and degraded operation. Reachy Mini's daemon already exposes REST and
WebSocket interfaces for remote control and supports browser/WebRTC
integration, making this service boundary compatible with the platform.
[2][3]

### Project objectives

- Provide a useful office secretary/companion rather than a generic voice chatbot.
- Keep sensitive and long-form responses private by routing them to phone/text channels.
- Maintain one persistent conversation across Reachy, Telegram, web, and phone-call interfaces.
- Decouple robot animation and presence from the LLM/orchestrator.
- Allow remote access and limited telepresence while travelling.
- Keep local motion and fallback personality available when the homelab agent or optional Jetson is offline.
- Support gradual migration between cloud and local STT/TTS/LLM providers.

### Non-goals for initial releases

- Home Assistant or smart-home automation.
- Autonomous high-impact actions without user confirmation.
- Full mobile-native applications before the web/PWA workflow is proven.
- Kubernetes deployment for the first implementation; Docker Compose is sufficient.
- LLM-generated raw motor trajectories.

## 2. Target Architecture

```
                         HOMELAB
┌─────────────────────────────────────────────────────────┐
│  companion-core                 reachy-hub               │
│  • reasoning / tools            • sessions               │
│  • memory / RAG                 • Telegram                │
│  • calendar / email / tasks     • WebRTC / web UI          │
│  • proactive workflows          • response routing         │
│  • interruption policy          • auth / robot registry    │
└──────────────────────────┬──────────────────────────────┘
                           │ secure network / VPN
                           ▼
                     REACHY MINI
              ┌────────────────────────┐
              │ reachy-embodiment      │
              │ • behaviour engine     │
              │ • presence loop        │
              │ • idle/fallback state  │
              │ • safety/watchdog      │
              └───────────┬────────────┘
                          ▼
                    Reachy daemon
```

The Reachy daemon remains the hardware-facing layer. Pollen Robotics
documents REST and WebSocket access to the daemon and explicitly positions
REST for web UIs, non-Python clients, remote control, and AI/LLM
integration. On Reachy Mini Wireless, the daemon is reachable through the
robot hostname/IP. [2][3]

### Service boundaries

See [docs/adr/0001-service-boundaries.md](adr/0001-service-boundaries.md).

### Core separation rules

- Cognition ≠ embodiment
- Embodiment ≠ transport
- Transport ≠ session
- Session ≠ memory
- Memory ≠ RAG
- LLM suggestion ≠ permission

## 3. Jarvis Reuse Strategy

Jarvis should accelerate the project but should not determine the long-term
architecture. The current repository already separates audio/VAD/STT/TTS,
vision, robot control, integration handlers, governance, planning, and
proactive-assistant functionality. [1]

| Jarvis area | Decision | Rationale |
|---|---|---|
| audio/vad.py | Reuse/adapt | Silero VAD and barge-in are already solved. |
| audio/stt.py | Reuse/adapt | Local faster-whisper is appropriate for office privacy. |
| audio/tts.py | Reuse/adapt | Retain streaming interface but make provider pluggable. |
| presence loop | Reuse concepts/code | Independent 30 Hz presence is a strong embodiment primitive. |
| robot/controller.py | Adapt | Replace direct application coupling with semantic embodiment API. |
| memory governance | Reuse concepts | Useful provenance/staleness/retention ideas. |
| audit/trust/policy | Reuse concepts | Relevant to email/calendar writes and permissions. |
| brain/conversation loop | Reference only | Replace with cross-channel session architecture. |
| Home Assistant/smart home | Remove | Outside project scope. |
| HA add-on deployment | Remove | No longer needed. |

### Repository structure (implemented)

```
reachy-work-companion/
├── services/
│   ├── companion-core/
│   ├── reachy-hub/
│   └── reachy-embodiment/
├── clients/
│   ├── web-pwa/
│   └── operator-ui/
├── shared/
│   ├── models/
│   └── protocols/
├── deploy/
│   ├── homelab/
│   └── reachy/
└── docs/
```

## 4. Interaction and Privacy Model

### Primary operating modes

| Mode | Primary input | Primary output | Use case |
|---|---|---|---|
| Desk | Reachy microphone | Reachy speaker | Home/private room |
| Office | Reachy or phone | Phone preferred | Open office |
| Silent | Text/PTT | Text | Meetings / quiet work |
| Remote | Phone/web | Phone/web + robot control | Travel / overseas |

### Response routing

The LLM may propose metadata, but a deterministic policy engine has final
authority over output routing. This is particularly important for workplace
privacy. See [shared/models/response.py](../shared/models/response.py) for
the `AgentResponse` schema.

- Short harmless answer → Reachy speech when allowed.
- Calendar/email details → phone/text by default in Office mode.
- Long response or code → Telegram/web.
- Sensitive work information → private channel only.
- Urgent event → phone alert plus Reachy attention gesture.
- Active meeting/DND → queue or silent notification.

### Cross-channel session continuity

See [docs/adr/0002-agent-session.md](adr/0002-agent-session.md).

## 5. Embodiment and Animation Service

See [docs/adr/0003-embodiment-command-api.md](adr/0003-embodiment-command-api.md)
and [docs/adr/0004-offline-fallback.md](adr/0004-offline-fallback.md).

Reachy supports built-in emotion/dance libraries and arbitrary custom
recorded-move datasets. The current recorded-move implementation loads named
JSON moves from Hugging Face datasets and the documentation explicitly
supports custom datasets. [4][5]

### Initial behaviour vocabulary

- Listening, thinking, speaking, acknowledgement, understood, uncertain.
- Greeting, goodbye, waiting, task complete, cannot comply.
- Sent-to-phone, incoming message, meeting soon, important notice, do-not-disturb.
- Idle breathing, subtle scan, antenna twitch, sleep/wake.

Local execution is important for low-latency continuous motion. Reachy
Wireless can run SDK code on the robot itself, while remote clients can use
the daemon APIs. [3]

## 6. Implementation Roadmap

Implementation status (2026-09-22): Phases 0–20 are complete. Phase 21
(hybrid local/cloud routing) is next. See
[README Status](../README.md#status) for verification evidence and
[ADR 0016](adr/0016-operator-ui.md) for the implemented operator API.

| Phase | Primary deliverable | Exit criterion |
|---|---|---|
| Phase 0 — Architecture freeze | Create repository, ADRs, service contracts, message schemas, and explicit ownership boundaries. | Every major function has one owning service; no coding begins against ambiguous interfaces. |
| Phase 1 — Stock Jarvis baseline | Run Jarvis in simulation and on Reachy; validate microphone, VAD, STT, TTS, barge-in, motion, face tracking, idle presence. | Known-good reference behaviour is documented. |
| Phase 2 — reachy-embodiment | Build semantic behaviour API over Reachy daemon/SDK; implement health/state and behaviour catalogue. | Remote HTTP call triggers a named behaviour. |
| Phase 3 — Offline personality | Move/adapt presence loop locally; implement IDLE/LISTENING/THINKING/SPEAKING/REMOTE/SLEEP/DISCONNECTED states. | Reachy remains animated when homelab services are stopped. |
| Phase 4 — Homelab control plane | Deploy companion-core, reachy-hub, PostgreSQL, optional Redis, reverse proxy via Docker Compose. | Homelab can invoke Reachy behaviours and read status. |
| Phase 5 — Unified sessions | Implement AgentSession and channel abstraction. | Two test clients share one conversation state. |
| Phase 6 — Operating modes | Implement Desk/Office/Silent/Remote as deterministic I/O policy. | Mode changes output routing without prompt changes. |
| Phase 7 — Telegram | Outbound text → inbound text → voice notes → voice replies. | Start on Reachy and continue same session in Telegram. |
| Phase 8 — Modular speech stack | Adapt Silero VAD, faster-whisper, streaming TTS behind provider interfaces. | Reachy conversation works without Jarvis monolithic loop. |
| Phase 9 — Privacy/response router | Implement response metadata, deterministic routing, audit events. | Private test payload cannot be spoken in Office mode. |
| Phase 10 — Calendar | Read-only next/list/free-busy first; later writes behind confirmation. | "What's next?" works and meeting reminders route appropriately. |
| Phase 11 — Tasks/notes/reminders | Capture, list, complete and search basic work items. | Agent can record and later retrieve explicit follow-ups. |
| Phase 12 — Work memory | Profile, working and episodic memory with provenance, sensitivity and expiry. | Stored work fact can be recalled later without transcript dumping. |
| Phase 13 — RAG | Document ingestion, embeddings/vector store, provenance-aware retrieval. | Answers identify their supporting document/section/page where available. |
| Phase 14 — Email | Read/summarize/draft/preview/approve/send. | No code path sends mail without approval gate. |
| Phase 15 — Call Reachy | PWA + WebRTC real-time audio; synchronize private audio with Reachy embodiment. | Private earbuds conversation while Reachy visibly listens/thinks/speaks. |
| Phase 16 — Remote telepresence | Camera/status/manual behaviours/speak-through-robot via secure remote UI. | Overseas user can control basic Reachy functions without Companion Core. |
| Phase 17 — Interruption intelligence | Inputs: calendar, presence, meeting, DND, urgency, privacy, last interruption. Actions: ignore/queue/text/gesture/interrupt. | Routine notifications defer correctly while user is occupied. |
| Phase 18 — Daily briefing | Combine calendar/tasks/email/reminders/project events into prioritized arrival briefing. | Reachy greets; detailed briefing is privately delivered. |
| Phase 19 — Operator UI | Login-gated web dashboard: live component health, LLM utilization, and controls for mode/DND/LLM provider settings (cloud API key, or a local base URL — primary local target is a self-hosted [OpenVINO Model Server](https://docs.openvino.ai/2026/model-server/ovms_what_is_openvino_model_server.html) instance, reachable over its OpenAI-compatible `/v1/chat/completions` endpoint). Adds a real pluggable LLM client to replace the previously unconfigured `/conversation` fallback when a provider is set — one `OpenAICompatibleChatProvider` implementation, since OVMS, OpenAI's own API, Ollama, LM Studio and vLLM all speak the same `POST {base_url}/chat/completions` shape, so "cloud key" vs "local OpenVINO URL" is only ever a `base_url`/`api_key` difference, never a code fork — so the utilization view reflects genuine calls. Also adds a real single-owner login (replacing the pasted-token flow `REMOTE_UI_TOKEN`/`clients/web-pwa/telepresence.js` use today) so the dashboard isn't gated by a shared secret typed into a text field. | An operator can log in, see every component's live status, and change mode/DND/LLM settings — including pointing the agent at a locally running OpenVINO Model Server by URL alone, no redeploy — without a shell. See [docs/adr/0016](adr/0016-operator-ui.md) (implemented and verified with real OVMS). |
| Phase 20 — Web chat channel | A text chat view in the browser (served alongside the Phase 19 dashboard) that talks to the buddy through the exact same `Channel.WEB`/`POST /messages` path every other channel already uses — no new conversational logic, just a UI for a channel this codebase already models. Exists both as a first-class regular way to talk to the buddy and as the fallback when Telegram (or any other channel) is down; the Phase 19 status dashboard is extended to show Telegram's actual poll-loop health, not just "token configured", so an outage is visible before the user needs the fallback. | A full text conversation can be held entirely through the browser, with the same session/mode/privacy routing every other channel gets; if Telegram stops responding, the dashboard shows it and the web chat still works. See [docs/adr/0017](adr/0017-web-chat-channel.md) (implemented; verified with real OVMS and a real Telegram polling failure). |
| Phase 21 — Hybrid local/cloud LLM routing | The "Optional hybrid local/cloud inference routing" item this doc's own §7 V0.3 list already named but never phased. Phase 19's LLM config is role-based from the start (`LLMRole.LOCAL`/`LLMRole.CLOUD`, each pointing at its own provider settings) precisely so this phase is additive: it populates the `CLOUD` role and adds a routing engine (`router.py`) that dispatches purely on role, never on which concrete provider backs it — local-only, cloud-only, or local-with-automatic-cloud-fallback (default once cloud is configured) — escalating to a configured frontier model (OpenAI, Anthropic, etc., still via the same OpenAI-compatible `ChatProvider` abstraction Phase 19 built) when the local call fails outright, plus a manual per-message/session override for when the user judges the local model's answer insufficient, since a real automatic quality judgment would need another LLM call to arbitrate and is deliberately out of scope for v1 (same honesty-about-scope discipline as this codebase's other placeholder classifiers). | The agent keeps working on a local-only OpenVINO setup; when a cloud role is also configured, a failed/unsatisfying local answer can escalate to it automatically or on request, and the Phase 19 utilization dashboard shows the `LOCAL`/`CLOUD` usage split. See `docs/adr/0018-hybrid-llm-routing.md` (to be written alongside implementation). |

## 7. Release Targets

### V0.1 — Useful office companion

- Reachy local embodiment service and autonomous idle behaviour.
- Homelab Companion Core + Reachy Hub.
- Unified sessions and Desk/Office/Silent modes.
- Local STT, pluggable TTS, cloud LLM initially.
- Telegram text and voice-note interaction.
- Privacy/response router.
- Read-only calendar integration.

V0.1 is deliberately useful before RAG, email, or WebRTC. It should already
support "ask Reachy → private answer to phone → continue in Telegram" while
preserving physical embodiment.

### V0.2 — Work secretary

- WebRTC "Call Reachy" PWA.
- Tasks, reminders and notes.
- Work memory.
- RAG over approved documents.
- Email read/summarize/draft with approval.
- Improved semantic animation library.

### V0.3 — Proactive companion

- Interruption engine and adaptive nudge policy.
- Daily briefing and follow-through workflows.
- Office-context awareness and better privacy inference.
- Remote telepresence controls.
- Optional hybrid local/cloud inference routing (Phase 21).
- Login-gated operator UI: component health/LLM utilization dashboard,
  mode/DND/LLM-provider controls (Phase 19).
- Web chat as a first-class channel and Telegram-outage fallback (Phase 20).

## 8. Deployment Plan

| Component | Initial location | Notes |
|---|---|---|
| Reachy daemon | Reachy | Hardware/media control; existing platform service. |
| reachy-embodiment | Reachy-side | Low-latency motion, idle state, safety/watchdog. |
| companion-core | Homelab | Canonical reasoning/tools/memory service. |
| reachy-hub | Homelab | Sessions, Telegram, WebRTC, web UI, routing. |
| PostgreSQL | Homelab | Durable structured state and metadata. |
| Vector store | Homelab | RAG; can begin with pgvector. |
| STT | Homelab initially | Local faster-whisper; raw office audio remains local network. |
| TTS | Cloud initially | Keep provider interface pluggable; later local option. |
| LLM | Cloud initially | Abstract backend; later hybrid/local routing. |
| Jetson | Optional office edge | Accelerator only; not required for system availability. |

### Remote access

Remote connectivity should use a secure overlay/VPN or equivalent
authenticated network path. Do not expose the Reachy daemon directly to the
public Internet. The hub should be the authenticated remote entry point; the
robot-facing daemon remains inside the trusted network boundary.

## 9. Security, Privacy, and Permission Model

See [docs/adr/0011](adr/0011-destructive-action-consent.md) for the binding
implementation of "explicit confirmation" below: destructive actions are
gated in code (`companion_core/consent/`), voice can never provide that
confirmation, and bulk/mass-destructive actions have no path to
confirmation at all, regardless of who's asking.

- Default-deny for consequential tool actions.
- Read-only first for calendar, email and documents.
- Explicit preview/confirmation for email sends and calendar changes.
- Deterministic output policy for workplace-private information.
- Audit every tool invocation, approval decision and outbound action.
- Attach provenance, sensitivity and expiry to memory entries.
- Keep credentials in secret storage/environment injection, never prompts or memory.
- Authenticate all remote Hub endpoints and robot-control sessions.
- Provide an emergency "disable remote control"/safe-mode control.

### Suggested permission tiers

| Tier | Examples | Policy |
|---|---|---|
| Observe | Calendar read, document search, robot state | No confirmation. |
| Prepare | Email draft, proposed calendar move | Generate preview; no external change. |
| Act | Send email, modify calendar, external notification | Explicit user confirmation. |
| Control | Remote robot audio/camera/motion | Authenticated session + visible remote-state indicator. |

## 10. Core Data Contracts

Implemented in [shared/models/](../shared/models/):

- `AgentSession` — [session.py](../shared/models/session.py)
- `AgentResponse` — [response.py](../shared/models/response.py)
- `MemoryRecord` — [memory.py](../shared/models/memory.py)
- `EmbodimentCommand` — [embodiment.py](../shared/models/embodiment.py)

## 11. Validation Strategy

Every phase has an explicit exit criterion. In addition, keep a small
end-to-end regression suite that can run against simulation before hardware
tests. Jarvis already supports simulation mode, which is useful as a
baseline reference. [1]

### Critical end-to-end scenarios

- Voice → local STT → agent → Reachy speech/gesture.
- Voice in Office mode → agent → private Telegram response.
- Reachy conversation → continue in Telegram with same session.
- Private WebRTC phone call → Reachy listening/thinking/speaking animation with no room audio.
- Homelab outage → Reachy falls back to local idle personality.
- Jetson outage → no loss of core agent or embodiment availability.
- Calendar reminder during meeting → queued/silent, not spoken.
- Email draft → preview → explicit approval → send.
- Remote travel mode → authenticated basic robot control without Companion Core.
- RAG response → provenance returned with the answer.

## 12. Immediate Next Actions

1. Create `reachy-work-companion` repository and write architecture decision records for the four main boundaries: Core, Hub, Embodiment, Daemon.
2. Clone/run upstream Jarvis in simulation and establish a behavioural baseline.
3. Define the first `EmbodimentCommand` schema and implement `/health`, `/state`, `/behaviours`, and `/behaviour/{name}`.
4. Implement 5–8 semantic behaviours using existing Reachy recorded moves before creating new animations.
5. Add a local presence/fallback state machine on the Reachy side.
6. Deploy minimal Homelab Hub/Core with Docker Compose and prove remote behaviour invocation.
7. Implement AgentSession before integrating Telegram.
8. Add Telegram text as the first external channel; then add voice notes.
9. Only after sessions and routing are stable, extract/adapt Jarvis audio components.

## 13. Key Engineering Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Over-coupling to Jarvis upstream | Merge pain / architectural lock-in | Reuse modules/interfaces selectively; maintain own service contracts. |
| Network jitter affecting motion | Unnatural embodiment | Keep continuous motion and fallback presence local to Reachy. |
| Privacy leakage through speech | Workplace confidentiality issue | Deterministic Office/Silent routing policy; tests for private content. |
| Channel session divergence | Confusing assistant state | One canonical AgentSession; channels are transports only. |
| Excessive proactive interruptions | Assistant becomes annoying | Start reactive; add interruption engine late with conservative defaults. |
| Unsafe tool autonomy | Unintended external actions | Read-only first; preview/approval/audit for writes. |
| Scope creep | Slow delivery | Treat V0.1 as product milestone; defer RAG/email/WebRTC until core routing works. |

## 14. References

[1] haasonsaas/jarvis — Embodied AI assistant for Reachy Mini; documents 30 Hz presence, Silero VAD, faster-whisper, ElevenLabs TTS, simulation, robot controller, integrations and governance. https://github.com/haasonsaas/jarvis
[2] Pollen Robotics Reachy Mini — Integrations & Apps; REST/WebSocket daemon API and browser/WebRTC integration. https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/integration.md
[3] Pollen Robotics Reachy Mini — Quickstart; running SDK on Reachy Mini Wireless and remote/local deployment. https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/quickstart.md
[4] Pollen Robotics Reachy Mini — Recorded Moves; built-in emotion/dance libraries and custom datasets. https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/examples/recorded_moves.md
[5] Pollen Robotics Reachy Mini — recorded_move.py; named move loading and default emotions/dances datasets. https://github.com/pollen-robotics/reachy_mini/blob/main/src/reachy_mini/motion/recorded_move.py
[6] Pollen Robotics Reachy Mini — AGENTS.md; daemon REST/WebSocket API and remote/AI integration guidance. https://github.com/pollen-robotics/reachy_mini/blob/main/AGENTS.md
