# Phase 38: Alarm clock and presence-gated delivery

Status: **started 2026-10-05.** Scope and exit criterion are owned by the [forward roadmap](plan.md#forward-roadmap-phases-30); this page owns
the stage sequence and gates. The decision and delivery rules are [ADR 0027](adr/0027-alarms-and-presence-gated-delivery.md).

## Stages

| Stage | Work | State | Gate to the next stage |
|---|---|---|---|
| 38.0 Documents | Roadmap row, this page, ADR 0027 | **Done 2026-10-05** | Owner can redirect scope |
| 38.1 Alarm domain in core | `Alarm` model, InMemory/Postgres store, migration 015, routes (create, list, cancel, due claim, optional reminder link), tests | **Core done 2026-10-05** (in `PlannerStore`, no new injected store; Postgres durability test not yet written) | Store parity tests pass; claim-once verified |
| 38.2 Occupancy sweep | Dedicated bounded embodiment sweep operation (fixed yaw stops, frame per stop, return to start, stop-safe), hub-side person/face detection returning a boolean only; no frame retained; unknown reads as absent; on by default (owner decision 2026-10-05; `PRESENCE_SWEEP_ENABLED=false` falls back to one forward frame) | **Implemented 2026-10-05** (embodiment `/sweep` routes, hub `occupancy.py`, simulated tests; not wired into delivery yet) | Simulated backend tests; owner decision 2026-10-05: no supervision or approval needed to run it on the Nano; real sweep needs owner |
| 38.3 Station catalogue and stream playback | TuneIn OPML search, owner-saved stations, SSRF-guarded resolution, hub-side decode to a short first WAV chunk then longer ones (the robot plays WAV bytes only), a built-in chime when no station is chosen, stop path | **Implemented 2026-10-05** (core `/stations`, hub `alarm_audio.py`, embodiment `POST /audio/stop`; live TuneIn search, resolve and decode checked against a real station; no robot playback; not wired to a scheduler or UI yet) | Playback verified against a simulated backend; real robot needs owner |
| 38.4 Hub scheduler and delivery policy | Poll due alarms, apply the ADR 0027 order (privacy, availability, DND/meeting, occupancy), Telegram fallback and annotation, bounded duration | **Implemented 2026-10-05** (hub `alarm_delivery.py` policy and `AlarmDeliverer`, `alarm_loop` in `app.py` polling `/alarms/due` each notify interval; a reminder with a live linked alarm is skipped by the reminder push so it notifies once; privacy mode = no robot has a wake arm; delivery outcome recorded in core; no owner stop route yet, that is 38.6; simulation only, no live Telegram or robot) | Policy table and loop tested in-process (`test_alarm_delivery.py`, `test_alarm_loop.py`) |
| 38.5 Setting alarms | `/reachy alarm` command, natural phrases, weekday/date parsing, reminder-to-alarm offer with pending-state follow-up | **Implemented 2026-10-05** (core `alarm_intent.py`; `/alarm <when>`, `/alarms`, "set an alarm for 7am", "wake me in 30 minutes", "what alarms do I have"; `reminder_time` now parses weekdays and a bare day is due 09:00; a reminder with a day or time leaves one in-memory, session-scoped, 10-minute offer, answered by yes/no/time, anything else ends it; offers are not persisted so a core restart drops them; no `/alarm stop` yet, that needs the 38.6 hub route) | Offer flow tested through `/conversation` in `test_planner.py` |
| 38.6 Operator UI | Alarms tab (list, add, cancel, station choice, stop) with owner-cookie/CSRF proxies | **Implemented 2026-10-05** (`clients/operator-ui/alarms.js`, hub `/planner/alarms*` and `/planner/stations*` proxies, `POST /planner/alarms/stop`) | Browser fixture test `alarms.test.cjs` at both mounts; `test_operator.py` proxy test |
| 38.7 Acceptance | Deploy with migration backup, live Telegram path, physical playback and occupancy check (the owner may watch, but need not) | In progress | Live 2026-10-05: Telegram path, privacy routing, sweep with head turned to body yaw, station matching from `/alarm`, 5 s alarm poll. Stream decode fixed to be incremental (codec sniffed; a per-slice decode cut playback to 5-10 s). Full-length station playback and empty-room fallback still to re-verify after hub redeploy |

## Constraints that carry across stages

- Hub decides delivery; embodiment holds hardware only. Shared models in `shared/models`, route constants in `shared/protocols`.
- Privacy mode is checked first and never plays audio. Unknown occupancy is absent.
- The room check sweeps the head through bounded stops (owner direction 2026-10-05); `/gaze` and `/pose` stay reserved. Owner decision 2026-10-05: the alarm room sweep and alarm audio are intended design and run unattended, with no supervision or approval needed (see AGENTS.md).
- No camera frame is stored or logged; the check runs only for a due alarm or an owner request.
- Station URLs come only from the owner UI and are SSRF-guarded.
- Real robot playback is not exercised without the owner.
