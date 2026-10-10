# Phase 48B: capture eligibility from channel trust, not robot state; disposable-stack evidence, 2026-10-10

**Status: implemented (commit `0304ab8`) and verified on a disposable stack and in the test suites. NOT DEPLOYED. Production still runs the Phase 44 image with `MEMORY_CANDIDATES_ENABLED=true` and `MEMORY_CANDIDATES_CAPTURE_ENABLED=false`; the production candidate table is empty. Capture activation awaits the owner's approval.**

## 1. The change

Before: every capture first asked the hub `GET /privacy/state`, which says "privacy mode off" only while a registered robot is armed for wake listening, so Web and Android memory depended on robot state. Now (`memory/candidate_service.py`):

| Interaction (channel, modality) | Eligible |
|---|---|
| typed, `web` (Web and Android: the app sends `web`), `phone`, `telegram` | yes, no embodiment lookup at all |
| spoken, `reachy` (robot voice) | only if the hub reports an explicit `privacy_mode: false`; on, unknown, malformed or unreachable = no |
| spoken on any non-robot channel, typed on `reachy`, any other channel | no |
| sensitive-labelled turn or sensitive text, attached meeting, turn another handler answered, assistant text | no (unchanged) |
| capture flag off, or review flag off | never (no capture object exists; with review off the routes are 404, so no hidden queue) |

**Trust source.** No client-supplied trust field was added. Channel and modality are assigned on the hub's authenticated paths: in the owner-bound deployment `/messages` requires the owner session or the bearer token (a bare request gets 401), the Telegram poll loop accepts only the owner's private chat, and core itself rejects any request without the service token before a handler runs. `GET /privacy/state` stays, but is consulted for robot-voice turns only. Core was not changed to attest the hub's auth mode: a core started without the service token (not possible via Compose, which requires it) would accept any channel string.

**Behavioural note for the owner.** Robot voice is now eligible whenever a robot is armed, as the target policy says. Speaker identity is not verified (Phase 32), so anyone speaking near an armed robot can produce a proposal; proposals still need the owner's text review and are capped at 5 per hour and 20 per day. A one-line default (`DEFAULT_CHANNELS`) removes the robot channel if the owner prefers.

## 1a. Owner decision after this record: robot voice is ineligible (2026-10-10)

Speaker identity is not verified, so an armed robot does not establish that the speaker is the owner. `ROBOT_VOICE_ELIGIBLE = False` (a code constant, not an environment setting) makes every robot-origin turn ineligible (counter `excluded_robot_unverified`, no hub lookup). The wake-arm/privacy logic stays for the future Phase 32 integration and is exercised by tests that set the constant true. Regression test `test_an_armed_robot_with_unverified_voice_proposes_nothing`: armed robot (privacy off) + robot voice = 0 candidates. **Robot-origin memory capture is deferred until owner verification is available.** In the table below, the two robot-voice rows describe the retained logic as first built (the stub-armed case would now give 0).

## 2. Automated tests

85 candidate tests pass (unit, real-PostgreSQL production lifespan, hub), covering: typed web/phone/telegram capture with privacy on, unknown, or the hub down, and the hub never consulted; robot voice for each privacy state; spoken-on-other-channel and typed-on-robot exclusions; sensitive turns on every channel; each flag combination across every channel; a bare request refused with 401 and nothing captured; a web turn on a database with no robot accepted into exactly one memory and one `memory.created` receipt. Full suites on the committed tree: companion-core, reachy-hub and shared 2,393 passed, 20 skipped, **3 failed, all known baseline failures** (`test_reconcile_repairs...`, `test_historical_mode_reaches_the_prefilter...`, hub `test_spoken_command_text_does_not_actuate_the_robot`). `ruff` clean.

## 3. Disposable stack (images built from a clean worktree of `0304ab8`, a new `pgvector/pgvector:pg16`, new keyring and credentials, migration to 028; removed afterwards)

No robot existed anywhere. No language model was present (replies read "heard: ..."), so this proves eligibility and workflow, not reply quality. The Telegram poll loop was not run; the telegram case calls core with the hub's contract. The "armed robot" case uses a stub hub returning `privacy_mode: false`; the "privacy on" case uses the real hub, which has no registered robot.

| Case | New candidates |
|---|---|
| Web, owner session, through the hub | 1 |
| Android: bearer token, channel `web`, through the hub (same contract) | 1 |
| Telegram owner private (core contract) | 1 |
| Robot voice, real hub reporting privacy on | 0 |
| Robot voice, stub hub reporting privacy off | 1 |
| Unauthenticated through the hub (401) / direct to core without service token (401) | 0 / 0 |
| Sensitive-labelled web turn | 0 |
| Spoken turn on the web channel | 0 |
| Capture off, review on (web, telegram, phone, robot voice): list route 200 | 0 |
| Review off, capture on: routes 404 | 0 |
| Both off: routes 404 | 0 |
| All on, after the hourly cap of 5 was reached | 1 of 4 (cap) |
| Reply parity, three turns on three channels, flags off versus on | identical replies (same hash) |
| Accept: 5 concurrent requests plus a repeat | one 200, four 409, repeat 200; exactly 1 memory and 1 receipt added |
| UI (Chromium on the new hub): pending list shows web and robot-origin suggestions with provenance; Save to memory works | pass |

Not covered: a real robot, the Telegram poll loop, Android on a device, a real language model, owner browser on production, and the robot-voice path through a real armed robot (48H regression).

## 4. Next

Owner approval of 48B activation requires deploying these images (core and hub; the hub change is a docstring only, so core alone is enough) and then `MEMORY_CANDIDATES_CAPTURE_ENABLED=true`, followed by the supervised trial in [Phase 48](../phase-48.md#4-48b--supervised-candidate-capture).
