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
- Keep local motion and fallback personality available when the homelab agent is offline.
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
                           ▲ robot-initiated WSS (Phase 22a)
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

Implementation status (2026-09-24): Phases 0–21 and Phase 22a are
implemented, including the hosted-cloud verification recorded in
[implementation history](verification/history.md). Phase 22 was split into **22a — bring-up** (inventory, the
real robot backend, WSS connectivity and the Bash launchers, implemented
and partially live-verified on the Nano; a named move has been dispatched
end-to-end against the real `reachy-mini-daemon` running in its own
simulator, not yet against real Nano motors) and **22b — physical
acceptance testing** (the full acceptance matrix — started 2026-09-23/24,
owner's call, after Phase 23 so Phase 23 wasn't blocked on Nano hardware
availability). 22b is **in progress, not merely deferred**: real motor
motion (a hardware fault on three head motors found and pragmatically
accepted closed by the owner), audio, and camera capture have each been
exercised on real hardware; the endurance (8-hour desk run, 24-hour idle
soak), outage/reconnect, backup restore, privacy/consent and channels
matrix items remain open. **22c — camera LOCAL-backend acceptance**
(code/dependencies done 2026-09-24; hardware run earmarked for a later
date after the companion board went offline mid-session) was split out
separately rather than folded into 22b, since it's a self-contained
follow-up to one specific code change, not the full acceptance matrix.
See the [bring-up record](verification/phase-22-bring-up.md), [first-motion
evidence](verification/phase-22b-first-motion-2026-09-23.md) and [camera
evidence](verification/phase-22b-camera-2026-09-24.md).
Phase 23 implementation is complete, including migrations, SecretStore and
read-only Google Accounts. Isolated functional checks pass; real-account,
production-audience and deferred physical acceptance remain open. Phase 23b
adds a Desktop OAuth client transport (loopback helper) alongside the
original Web application client, for installs without a stable public HTTPS
hostname; see [ADR 0021's addendum](adr/0021-google-accounts.md). It inherits
Phase 23's open real-account acceptance item rather than closing it. Phase 22b
is in progress (above); Phase 24a is implemented and real-SearXNG-verified,
with running-deployment acceptance still open; Phase 24b is implemented and
fixture/browser-verified. See their roadmap rows below for evidence and limits.
[Phase 24c](phase-24cd.md) implemented the Reachy microphone conversation
workflow (2026-09-24), verified off the robot with a simulated microphone.
[Phase 24d](phase-24cd.md#phase-24d--physical-end-to-end-acceptance), its
physical acceptance, closed on 2026-09-25 on the conversation workflow by
owner re-scope; the deferred rows and its findings are
[Phase 24e](phase-24e.md). Phases 24e and 25–27 remain planned;
see the [deployment and accounts acceptance plan](phase-22-23.md). See
[implementation history](verification/history.md) for verification evidence and
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
| Phase 8 — Modular speech stack | Adapt Silero VAD, faster-whisper, streaming TTS behind provider interfaces. | Modular speech stack works independently of Jarvis. Physical Reachy microphone-to-speaker conversation was not proven here; it will be implemented and accepted in [Phases 24c–24d](phase-24cd.md). |
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
| Phase 21 — Hybrid local/cloud LLM routing | The "Optional hybrid local/cloud inference routing" item this doc's own §7 V0.3 list already named but never phased. Phase 19's LLM config is role-based from the start (`LLMRole.LOCAL`/`LLMRole.CLOUD`, each pointing at its own provider settings) precisely so this phase is additive: it populates the `CLOUD` role and adds a routing engine (`router.py`) that dispatches purely on role, never on which concrete provider backs it — local-only, cloud-only, or local-with-automatic-cloud-fallback (default once cloud is configured) — escalating to a configured frontier model (OpenAI, Anthropic, etc., still via the same OpenAI-compatible `ChatProvider` abstraction Phase 19 built) when the local call fails outright, plus a manual per-message override or standing routing policy for when the user judges the local model's answer insufficient, since a real automatic quality judgment would need another LLM call to arbitrate and is deliberately out of scope for v1 (same honesty-about-scope discipline as this codebase's other placeholder classifiers). | The agent keeps working on a local-only OpenVINO setup; when a cloud role is also configured, a failed local call can fall back automatically, while a valid but unsatisfying answer requires an explicit user override, and the Phase 19 utilization dashboard shows the `LOCAL`/`CLOUD` usage split. See [ADR 0018](adr/0018-hybrid-llm-routing.md) (implemented; OVMS dispatch and hosted Together AI verification recorded in [history](verification/history.md)). |
| Phase 22a — Physical bring-up | Inventory original Jetson Nano and Reachy topology; prove runtime compatibility; implement real robot backend and [outbound WSS connectivity](adr/0019-robot-initiated-hub-connectivity.md) (substrate only — command routing still HTTP), and homelab/Reachy/Nano Bash launchers with GUI access. | **Implemented and live-verified.** Real inventory on the Nano; `ReachyDaemonBackend` dispatches named moves end-to-end against the real `reachy-mini-daemon` (confirmed in its own simulator mode; connectivity confirmed live on the Nano, real motor motion not yet triggered). WS connectivity (auth/registration/generation-fencing/reconnect) was verified with real homelab containers; launcher diagnostics and daemon/container reachability were checked on the Nano. Separate outbound HTTPS media transfers not yet built. See the [bring-up evidence](verification/phase-22-bring-up.md). |
| Phase 22b — Physical acceptance testing | Run the full [acceptance plan](phase-22-23.md#satisfactory-run-acceptance-matrix) on real Nano/Reachy hardware: first real motor motion, physical voice, endurance (8-hour desk run, 24-hour idle soak), outage/reconnect, backup restore, privacy/consent, channels. | Cold starts, physical motion/media, privacy, channels, outage recovery, backup restore, 8-hour desk run and 24-hour idle soak pass with hardware evidence. **In progress** — started 2026-09-23/24 (owner's call, after Phase 23 so Phase 23 wasn't blocked on Nano hardware availability). First real motor motion found a three-head-motor hardware fault, pragmatically accepted closed by the owner (named behaviours only need to convey action/emotion, not exact joint tracking); daemon audio was root-caused and fixed; a real camera capture succeeded (its LOCAL-backend hardware acceptance split out as Phase 22c). Endurance, outage/reconnect, backup restore, privacy/consent and channels matrix items remain open. See [first-motion](verification/phase-22b-first-motion-2026-09-23.md) and [camera](verification/phase-22b-camera-2026-09-24.md) evidence. |
| Phase 22c — Camera LOCAL-backend physical acceptance | Verify `ReachyDaemonBackend.capture_frame`'s reachy_mini SDK LOCAL media-backend implementation (replacing the release/acquire+OpenCV escape hatch a first real capture used on 2026-09-24) against actual hardware: rebuilt `reachy-embodiment` image with the new PyGObject/GStreamer/`reachy_mini` dependencies, a live frame through the daemon's local IPC socket, and a deliberate fresh-scene-change check per the [acceptance matrix](phase-22-23.md#satisfactory-run-acceptance-matrix)'s "Physical identity"/"Channels and calls" rows. See [camera evidence](verification/phase-22b-camera-2026-09-24.md) for what's already done (code, tests, dependency verification) versus what this phase covers. | A live capture through the LOCAL backend succeeds on the real Nano without disrupting the daemon's audio/WebRTC, and a deliberate scene change is visibly reflected in a fresh capture. **Earmarked for physical testing at a later date** — the companion board (Jetson Nano) went offline mid-session on 2026-09-24 before the rebuilt image could be run; code/dependency work is done, hardware verification is not. |
| Phase 23 — Production Google account settings | Begin with cross-cutting versioned database migrations and shared SecretStore, including existing LLM-key migration; then owner-authenticated Gmail/Calendar Accounts UI, OAuth and read-only adapters; see the [accounts plan](phase-22-23.md). | Real-account connect/read/refresh/restart/revoke/reconnect/disconnect and privacy/isolation checks pass; applicable Google production requirements verified; repeat hardware acceptance (Phase 22b's matrix) with accounts. Implementation complete and verified with isolated database/provider/browser fixtures. Real-account, production-audience and deferred physical-repeat acceptance remain open; not yet production-accepted. |
| Phase 23b — Desktop OAuth client transport | Add a Google Desktop OAuth client type alongside Phase 23's Web application client, so a single-owner self-hosted install without a stable public HTTPS hostname can authorize Gmail/Calendar via a loopback PKCE handoff (`tools/google_auth_helper.py`) instead of provisioning a domain/DNS/certificate purely for OAuth. Ownership is unchanged (Core: configuration/exchange/refresh/credentials; Hub: owner-authenticated initiation and handoff); see [ADR 0021's addendum](adr/0021-google-accounts.md). | Isolated fixture/ASGI tests cover valid desktop connect/complete, cross-client-type flow isolation, expiry/replay/cancel, and that refresh/disconnect/reconnect behave identically to a web-originated grant. Implemented and isolated-fixture verified; see [verification](verification/phase-23b-desktop-oauth-2026-09-24.md). Inherits Phase 23's real-account/production-audience acceptance gate rather than closing it; a live Desktop-client consent/refresh run with the helper is a separate, still-open acceptance item. |
| Phase 24a — Search-assisted, freshness-aware assistant | Deterministic Off/Auto/Always search policy on the generic-conversation LLM call — Auto searches only when a fixed freshness/search-intent heuristic matches, using the current turn plus, only when referential, the prior user turn as the query. Results are delimited as untrusted external data and cited by id; provider keys stored via the existing SecretStore; self-hosted SearXNG by default, opt-in cloud provider; see the [assistant plan](phase-24a.md) and [ADR 0022](adr/0022-web-search-grounding.md). | A configured fixture/provider grounds and cites `LOCAL` and `CLOUD`/`force_frontier` answers alike only on Auto-matched or Always-policy turns, not the model's own trained claim; deterministic intents (calendar/tasks/email/RAG-docs/Gmail) never trigger a search call under any policy; embedded-instruction fixture content in results does not change model behaviour; a failed search on a search-warranted turn discloses the failure to the model rather than silently answering from stale knowledge; with policy Off or no provider configured, behaviour is unchanged. **Implemented, including a real self-hosted SearXNG instance shipped in `deploy/homelab/docker-compose.yml` and live-verified against real internet results**, plus fixture/deterministic-stub-model tests (`services/companion-core/tests/test_websearch.py`). A same-day cleanup pass made the bundled provider zero-configuration when started via `scripts/start-homelab.sh` (raw `docker compose` remains an advanced/manual path that still needs `SEARXNG_SECRET_KEY` set) — a `BUILTIN_SEARXNG` kind needs no Base URL/API key (the internal container address is hardcoded), and the launcher auto-generates the container's own deployment secret instead of asking the operator to — and added the operator UI card's first Playwright browser test. Follow-up work found during 24d (2026-09-24/25): hosted Brave, Exa and Tavily providers rotated within their free tiers with SearXNG as the last-resort fallback, follow-up searches, and owner date/time/location context; live-verified on the homelab. Answer quality with the local 1.5B model remains open 24a work. See [verification](verification/phase-24a-search-assisted-2026-09-24.md) (including its addenda) and [ADR 0022](adr/0022-web-search-grounding.md). |
| Phase 24b — Structured command and intent authorization | Deterministic namespaced slash-command parser (`/reachy standby`/`wake`/`status`, plus flat Telegram-registered aliases `/standby`/`/wake`/`/reachy_status` mapping to the same structured command) evaluated ahead of both deterministic intents and the LLM branch. Explicit structured commands or existing ADR 0011 consent/confirmation paths are the only ways to invoke consequential actions — natural-language intent only suggests, never authorizes. Retired `robot_power_intent`'s substring-only actuation (which false-positived on questions/negations, e.g. "How do I turn off Reachy?") entirely, replacing it with a separate speech-act-aware suggestion classifier rather than demoting the same matcher; see the [authorization plan](phase-24b.md). | Documented negative conversational examples never actuate the robot **or** produce a suggestion; `/reachy standby`/`wake`/`status` and their Telegram aliases work through the new parser and parse to identical commands; a request-classified natural-language match produces only a suggestion/button, never a direct action; command parsing/authorization/action results are identical across Telegram and web chat; ADR 0011's existing email/calendar consent flows and the named-behaviour-playback exception are unaffected. **Implemented and verified with isolated fixtures** (companion-core: `commands/`, `command_suggestion.py`; reachy-hub: Telegram `setMyCommands` registration; operator UI: command autocomplete and suggested-command action buttons) — no live Telegram bot run or physical robot actuation this session. See [verification](verification/phase-24b-command-authorization-2026-09-24.md). |
| Phase 24c — Complete Reachy conversation | Audit the actual mic → STT → session/core/LLM → routing/TTS → speaker chain; implement missing capture, transport, playback, controls, turn lifecycle and recovery; see the [conversation plan](phase-24cd.md). | Explicitly activated robot conversation is implemented with automated, browser and real-process speech checks; privacy, voice consent and context are preserved. Physical acceptance remains a separate gate. Implemented 2026-09-24 with a simulated microphone ([ADR 0023](adr/0023-robot-voice-conversation.md), [evidence](verification/phase-24c-conversation-2026-09-24.md)); robot capture/playback unverified on hardware. |
| Phase 24d — Physical conversation acceptance | Exercise the complete 24c workflow on the real robot with real speech/model providers, multi-turn context, channel handoff, privacy, cancellation and recovery; see the [acceptance matrix](phase-24cd.md#phase-24d--physical-end-to-end-acceptance). | The original full-matrix exit was superseded by the owner re-scope below; Phase 25 now requires the [24e conversation-path prerequisites](phase-24e.md#prerequisites-for-phase-25). Fixtures or standalone microphone/speaker checks cannot replace physical acceptance. **Closed 2026-09-25 by owner re-scope**: Normal conversation and both latency budgets pass on the robot (non-search p50 2.5 s / p95 6.9 s; search ≤ 19.3 s), all context checks are correct, cold-reboot recovery passes, and the owner accepted usability. The other matrix rows are deferred follow-up acceptance, not passed ([record](verification/phase-24d-conversation-2026-09-24.md#results)). Answer accuracy is 24a scope. |
| Phase 24e — Conversation hardening and deferred acceptance | Adaptive end of turn (hold incomplete-sounding segments; ADR 0023 amendment), deterministic search-trigger fixes and STT vocabulary bias, a fixed correctness set with an owner-agreed threshold (cloud model only if the local model fails), the seven 24d rows the owner deferred (including a 30-minute session), and Nano diagnostics (persistent journal, pre-NTP time, power evidence); see the [24e plan](phase-24e.md). | Long paused utterances are one turn; the 24d search misfires no longer search; the correctness threshold passes on the deployed voice route; every deferred row is PASS or BLOCKED with a reason; Normal conversation and Timing pass again; a reboot is diagnosable; the owner accepts usability. The [24e conversation-path prerequisites](phase-24e.md#prerequisites-for-phase-25) must PASS before Phase 25; independent quality/search/STT/diagnostic work does not block it. Planned, not implemented. |
| Phase 25 — Owner recognition and voice access control | After the [24e conversation-path prerequisites](phase-24e.md#prerequisites-for-phase-25) pass, web-portal owner enrollment, calibration and user-run accuracy testing; live face verification, speaker attribution, authenticated input and continuous room-audio gates; see the [recognition plan](phase-25.md). | Audible conversation requires fresh owner-in-view confidence strictly >60% plus privacy/liveness checks; unknown or ambiguous speakers cannot enter the conversation pipeline; spoof/outage/API-bypass tests pass on hardware; consequential actions retain authenticated text-only consent. Planned, not implemented. |
| Phase 26 — Meeting transcription and minutes | Upload or live-record (via Call Reachy) a meeting/conversation, transcribe it with the existing local STT, and hand the transcript to the LLM stack for a structured summary, key points, and action items; see the [transcription plan](phase-26.md). | A real recording (uploaded or live) produces summary/key points/action items in the operator UI via an async job the UI polls, not a blocking request; action items become tasks only after explicit owner confirmation; minutes are never spoken through Reachy's speaker and cloud delivery of a transcript requires a separate off-by-default opt-in. Planned, not implemented; depends on Phase 23's migration framework. |
| Phase 27 — Embodied meeting secretary | Reachy physically present for meetings: owner-present companion recording and minutes (27a), a bounded temporary-absence catch-up mode for short owner step-outs within an already-running 27a session under a capped `TEMPORARY_MEETING_ABSENCE` lease (27a.2), physical secretary attendance while the owner is absent for most/all of a meeting under the full owner-absent ADR amendment (27b), and bounded delegation limited to pre-approved questions/statements or the owner's own verbatim reply (27c); see the [secretary plan](phase-27.md). Virtual/cloud bot attendance is deferred, not a prerequisite. | 27a needs no ADR amendment; 27a.2 needs a narrow Phase 25 ADR amendment for a capped, meeting-STT-only absence lease with no tool/general-speech authority; 27b/27c require the full owner-absent amendment and supervised hardware acceptance; the platform never answers for the owner or makes commitments. Planned, not implemented; builds on Phase 26, requires Phase 22b hardware for every stage. |

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
- Search-assisted, freshness-aware assistant with a deterministic
  Off/Auto/Always search policy, reducing hallucinated answers from small
  local models on freshness-sensitive questions (Phase 24a).
- Structured slash-command authorization for consequential actions
  (starting with robot standby/wake), replacing substring-matched
  natural-language actuation with an explicit command gate and demoting
  free-form intent recognition to a suggestion (Phase 24b).

### V0.3 — Proactive companion

- Interruption engine and adaptive nudge policy.
- Daily briefing and follow-through workflows.
- Office-context awareness and better privacy inference.
- Remote telepresence controls.
- Optional hybrid local/cloud inference routing (Phase 21).
- Login-gated operator UI: component health/LLM utilization dashboard,
  mode/DND/LLM-provider controls (Phase 19).
- Web chat as a first-class channel and Telegram-outage fallback (Phase 20).
- Meeting transcription and minutes: summary, key points, and
  confirm-before-create action items from a recorded meeting (Phase 26).

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
| Jetson Nano | Reachy-side host | Required for the current USB-attached deployment; runs the real robot daemon and `reachy-embodiment` (see Phase 22a). Nano loss makes the robot inert; it is not an optional accelerator. |

### Robot connectivity (Phase 22a, implemented)

[ADR 0019](adr/0019-robot-initiated-hub-connectivity.md) replaces production
robot-address registration with authenticated robot-initiated WSS. The hub
routes by logical identity and active connection; separate outbound media
transfers preserve camera/audio without inbound robot ports. Existing HTTP
transport remains an explicit development/simulation option until migration.

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
- Jetson outage → homelab assistant remains available; physical embodiment
  becomes unavailable and the outage is reported as a degraded state, not
  silently masked (the Nano is the sole embodiment host — see
  [deployment](deployment.md#robot-host-and-jetson-nano)).
- Calendar reminder during meeting → queued/silent, not spoken.
- Email draft → preview → explicit approval → send.
- Remote travel mode → authenticated basic robot control without Companion Core.
- RAG response → provenance returned with the answer.

## 12. Immediate Next Actions

1. ~~Inventory the original Jetson Nano and Reachy model, OS/runtime, physical connection and device access; resolve service placement against ADR 0004.~~ Done (Phase 22a).
2. ~~Implement Phase 22's real backend, supervised deployment and Bash launchers, including GUI access, per the [detailed plan](phase-22-23.md).~~ Done (Phase 22a).
3. Complete Phase 23/23b production acceptance: register a Google OAuth client appropriate to the selected transport for the intended audience — a Desktop client, imported through Settings → Accounts and authorized by running the local helper (the default self-hosted path, no domain/HTTPS needed) or, for installs that already operate a stable HTTPS domain, a Web application client deployed behind that HTTPS callback — then run real-account consent/read/refresh/revoke/reconnect/restore checks. Implementation and isolated functional checks are complete; see [Accounts evidence](verification/phase-23-accounts-2026-09-23.md) and [Desktop OAuth evidence](verification/phase-23b-desktop-oauth-2026-09-24.md).
4. Continue the physical acceptance matrix (Phase 22b) — in progress: motion, audio and camera have been exercised; endurance, outage/reconnect, backup restore, privacy/consent and channels remain — fix blockers and record measured results before marking Phase 22 complete.
4a. Run Phase 22c (camera LOCAL-backend hardware acceptance) once the
    companion board is back: rebuild `reachy-embodiment`, run a live
    capture, and confirm a deliberate scene change shows up. Code and
    dependency work are done; only the hardware run is pending.
5. Verify real Google access and repeat deployment/privacy/recovery tests before production rollout.
6. ~~Implement Phase 24a's search-assisted assistant: Off/Auto/Always search policy ahead of the generic-conversation LLM call, untrusted-content isolation and citations, self-hosted SearXNG by default.~~ Done (2026-09-24), including a real self-hosted SearXNG instance shipped and live-verified; a hosted cloud provider and self-hosted-deployment/production acceptance of the running homelab stack remain open — see the [assistant plan](phase-24a.md), [ADR 0022](adr/0022-web-search-grounding.md) and [verification](verification/phase-24a-search-assisted-2026-09-24.md).
7. ~~Implement Phase 24b's structured command/intent-authorization redesign: the namespaced slash-command parser (with Telegram-alias registration), retiring `robot_power_intent`'s substring matching and replacing it with a separate speech-act-aware suggestion classifier.~~ Done (2026-09-24) — closes the prior false-positive actuation issue; see the [authorization plan](phase-24b.md).
8. Complete [Phase 24c](phase-24cd.md#phase-24c--audit-and-implement-the-missing-workflow): audit and implement the missing robot conversation links.
9. Phase 24d is closed on the core physical conversation workflow by owner
   re-scope. Complete and physically pass the
   [24e conversation-path prerequisites](phase-24e.md#prerequisites-for-phase-25)
   before starting Phase 25; quality/search/STT tuning and Nano diagnostics
   may proceed independently.
10. Implement Phase 25 owner enrollment, calibrated recognition and speaker/output gates; pass the [hardware and adversarial acceptance matrix](phase-25.md#acceptance-and-release-gate) before enabling ambient owner-only voice.
11. Implement Phase 26 meeting transcription and minutes: async job pipeline, chunked summarization, and confirm-before-create action items; see the [transcription plan](phase-26.md).
12. Implement Phase 27 in separately accepted stages: owner-present meeting
    companion (27a, no ADR amendment needed); a bounded temporary-absence
    catch-up mode for short owner step-outs within an already-running 27a
    meeting (27a.2, requires a narrow Phase 25 ADR amendment for a capped,
    meeting-pipeline-only `TEMPORARY_MEETING_ABSENCE` lease); physical
    secretary attendance while the owner is absent for most/all of a meeting
    (27b, requires the full Phase 25 ADR amendment for owner-absent capture);
    then bounded delegation of pre-approved questions/statements or the
    owner's own verbatim reply (27c). See the [secretary plan](phase-27.md).

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
