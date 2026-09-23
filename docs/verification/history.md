# Implementation verification history

Historical evidence consolidated from the former root README and handover.
Counts and limitations describe those sessions, not freshly verified runtime
health. The [roadmap](../plan.md#6-implementation-roadmap) owns phase scope,
[ADRs](../README.md#architecture-decisions) own decisions, and
[deployment](../deployment.md) owns current startup instructions.

## Phases 0–14

| Phase | Recorded verification and limits |
|---|---|
| 0 — Architecture | Service boundaries, ADRs, and shared schemas established. |
| 1 — Baseline | [Jarvis reference](../jarvis-baseline.md) reviewed for reuse. |
| 2 — Embodiment API | Semantic behaviour/state API implemented against simulation. |
| 3 — Presence | Independent presence/watchdog and offline fallback state machine tested. |
| 4 — Control plane | Real Compose/Postgres/Caddy run verified core → hub → embodiment, with durable robot registry. |
| 5 — Sessions | Independent Reachy/Telegram-channel HTTP clients shared session/conversation IDs through Caddy; active channel changed and turn history continued. |
| 6 — Modes | Identical text routed to Reachy, phone, then web solely from mode/channel changes; IDs persisted and mode survived hub restart. |
| 7 — Telegram | A real bot/account continued a session begun through a simulated Reachy call, retaining IDs. This was actual Telegram text delivery, not only an HTTP stub. |
| 8 — Speech | Real synthesized speech passed STT → conversation → TTS in tests, live processes, and deployed images through Caddy. Reply audio was re-transcribed to confirm intelligibility. Physical barge-in remained unwired. |
| 9 — Privacy | Private/sensitive content stayed off Reachy in Desk and Office modes; audit overrides survived hub restart. |
| 10 — Calendar | Seeded event produced a real “what’s next” answer; imminent reminder routed away from Reachy as work-private. Calendar survived core restart. No external calendar sync. |
| 11 — Tasks | Conversational capture, later retrieval, completion/search, and direct reads worked through live processes/Caddy and survived core restart. |
| 12 — Memory | A fact interleaved with unrelated turns/facts was selectively recalled without transcript dumping and survived restart. |
| 13 — RAG | Vacation and Expense documents were ingested; time-off query retrieved the correct document/section, surviving restart. Live Postgres exposed uncommitted extension creation and missing vector-cast bugs, both fixed. No PDF/page claim. |
| 14 — Email | Mailpit remained empty before approval; approved send produced real SMTP mail; repeat send refused; drafts persisted. Seeded inbox, not personal-account sync. Later consent work added delayed dispatch. |

## Consent and Phases 15–18

[ADR 0011](../adr/0011-destructive-action-consent.md)'s cross-cutting consent
work preceded Phase 15. Through Caddy, real speech attempting memory-forget
confirmation was refused while equivalent text succeeded, and the record was
restorable. Cancelling a queued email kept Mailpit empty; a separate queued
send dispatched after its undo window. Bulk-destructive rejection was tested
at the shared gate. These were tests of the structural consent path, not a
live Gmail/Outlook integration.

**Phase 15 — Call Reachy:** a real aiortc Python client negotiated through
Caddy, sent synthesized speech, received non-silent reply audio, and drove
listening/thinking/speaking transitions. A track-replacement/Opus sample-rate
failure was fixed by resampling. Static PWA assets served correctly. No real
cross-machine browser or physical room-audio acceptance was claimed.

**Phase 16 — Telepresence:** missing/wrong bearer returned 401, valid bearer
200. Speak-through produced synthesized WAV on the simulated robot; camera
returned JPEG; an aiortc peer received nonempty 320×240 video and robot state
changed remote → idle on close. With core stopped, messages failed 502 while
speak/state/behaviour controls continued working. An isolated embodiment image
exposed missing python-multipart masked by the shared dev venv; fixed. Physical
camera/speaker behavior remained untested. Owner-cookie access came in Phase 19.

**Build optimization:** root-context builds previously included a ~1.6GB venv.
After adding .dockerignore and uv/apt cache mounts, a measured cold three-image
build took 73 seconds; a warm one-line hub rebuild took 21 seconds. There was
no controlled before/after timing comparison. Toolchain rules now live in
[development](../development.md#docker-toolchain).

**Phase 17 — Interruptions:** through deployed Caddy, DND queued a 10-minute
reminder; a 2-minute urgent reminder produced a real simulated-robot
important_notice gesture. Clearing DND flushed queued content, updated the
last-interruption time, and recorded queue → gesture → interrupt audit actions.

**Phase 18 — Briefing:** a meeting three minutes away led the prioritized
briefing; greeting fired on the simulated robot while work-private detail
routed to Telegram rather than Reachy. With DND/urgent content, greeting still
fired while detailed delivery took the gesture path and was audited. This was
on-demand orchestration, not a background scheduler.

## Phases 19–21

**Phase 19 — Operator UI:** 278 Python tests passed, with Ruff and actual
image builds. Postgres/Caddy/Chromium checks at desktop and 390px mobile covered
login/logout, mode/DND, runtime model edits, key masking/partial updates,
telepresence cookie access, and blocked core-settings proxy bypass. OVMS
`OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` returned a real completion (first
measured call: 60 input/17 output tokens, about 1.5 seconds). Owner/settings/
usage/session state persisted through recreation. Core outage remained visible
without hiding healthy components. The separate `phase19verify` stack was
removed without altering the existing OVMS deployment.

**Phase 20 — Web chat:** 287 Python tests, Ruff/JS checks, and a committed
Chromium fixture regression passed. A separate `phase20verify` stack ran real
OVMS conversation in desktop/mobile Chromium: web → simulated Telegram-channel
HTTP → web preserved IDs/context and recalled “Teal.” Office/DND and private
calendar replies worked. A real invalid-token Bot API 401 marked polling
unhealthy while web chat continued. This was not a real Telegram-account
message; poll recovery was covered with controlled tests. The stack was removed.

**Phase 21 — Hybrid routing:** 300 Python tests, Chromium regression, Ruff,
JS/whitespace checks, and real Docker/Postgres/Caddy/OVMS runs passed. The
initial `phase21verify` run assigned OVMS to both roles: local-only success,
unreachable-local fallback with both attempts logged, and healthy-local manual
override. Real Chromium exercised cloud settings, per-role totals/reason, and
mobile layout. Settings and usage persisted across restart; an old-shape usage
table retained its historical row after the nullable escalation column upgrade.
This initially proved dispatch rather than hosted cloud; the follow-up below
completed the hosted-provider check. Temporary stacks/volumes were removed.

## Phase 22a

See the [bring-up record](phase-22-bring-up.md) and
[raw inventory](phase-22-inventory-2026-09-22.md). The real Nano daemon started,
woke the robot, and reported non-simulated connectivity. Named behaviour
commands were exercised against the real daemon's mockup simulator on the
homelab, not against physical Nano motors. WS substrate and launchers are
implemented; semantic commands still use HTTP. Physical acceptance remains
Phase 22b, explicitly deferred by the owner until after Phase 23.

## Hosted-cloud follow-up — 2026-09-22

The isolated `phase21togetherverify` stack used Together AI's compatible
`https://api.together.xyz/v1` endpoint with `zai-org/GLM-5.3` for cloud and
OVMS for local. Owner-authenticated hub requests verified local-only success,
a manual frontier override, and an unreachable-local error fallback. The
failed local row and successful cloud row retained the correct roles/reasons;
usage summaries agreed and configuration responses masked the cloud key.

GLM-5.3 spends its completion budget on reasoning as well as visible content.
A raw test with `max_tokens: 10` returned empty content and `finish_reason:
length`; the client correctly treats empty content as provider failure.
The normal client supplies no max_tokens override and the provider default
was sufficient in these checks (54–420 completion tokens). Inspect a sanitized
raw response's finish reason when diagnosing future empty/truncated replies.

The key was supplied via gitignored local verification configuration. The
local endpoint was restored before teardown; the disposable stack/volumes
were removed and OVMS left running. No production cloud configuration was
applied by this verification run.
