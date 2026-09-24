# Handover

Current session snapshot, updated 2026-09-24. Read [AGENTS.md](AGENTS.md)
before working. Durable instructions belong in the [documentation index](docs/README.md),
not repeated in this file.

## Current work

Phase 24a (search-assisted, freshness-aware assistant) is implemented
(2026-09-24): `shared/models/websearch.py`, migration `006_search_config`
(bumps `shared.database.SCHEMA_REVISION`), `companion_core/websearch/`
(deterministic Off/Auto/Always policy and referential-query heuristics,
`SearXNGSearchProvider`, untrusted-content-isolated prompt construction
with citation/failure-notice messages, SecretStore-backed settings store),
wiring in `app.py`'s generic conversation branch only (every deterministic
intent above it in the `if`/`elif` chain is structurally unaffected), core
+ hub `GET`/`PUT /settings/websearch`, and the operator UI's "Web search"
card. `deploy/homelab/docker-compose.yml` now ships a real self-hosted
`searxng` service (internal-only, `deploy/homelab/searxng/settings.yml`)
— live-verified this session: `SearXNGSearchProvider` run directly against
a container built from the checked-in config returned real internet
results, and the exact compose service was brought up under a separate
disposable project, reached by its production DNS name from another
container, and torn down, without touching the running homelab stack.
Also verified against a fixture SearXNG-shaped provider, a deterministic
stub chat model, and real disposable Postgres (migration + SecretStore
round-trip). **Not yet done:** a hosted cloud provider (e.g. Brave), and
actually upgrading/reconfiguring the running homelab stack itself to
include this service and a non-Off policy (self-hosted-deployment/
production acceptance); the operator UI card was not exercised in a real
browser. See [ADR 0022](docs/adr/0022-web-search-grounding.md) and
[verification](docs/verification/phase-24a-search-assisted-2026-09-24.md).
Phase 24b (structured command and intent authorization) is implemented
(2026-09-24): `companion_core/commands/` (`parser.py`'s deterministic
`/reachy standby`/`wake`/`status` parser plus Telegram flat aliases
`/standby`/`/wake`/`/reachy_status`, all parsing to an identical structured
`Command`; `replies.py`'s formatting, moved from the retired
`robot_power_intent.py`) evaluated in `app.py` at the same precedence
position the retired substring matcher occupied — only this parsed
`Command` may call `HubClient.standby_robots`/`resume_robots`/
`get_robot_state` now. `companion_core/command_suggestion.py` adds the
separate, schema-validated (`shared/models/command_suggestion.py`),
fail-closed natural-language suggestion classifier: gated by a cheap
"mentions reachy" pre-filter (an over-inclusive cost/latency gate only —
it never decides suggestion outcome, only whether the classifier is worth
calling), it replaces the model's answer with a suggested-command reply
only when it resolves `speech_act == "request"` above a confidence
threshold; any failure/timeout/malformed output/non-request speech act
falls back to the ordinary conversational reply, verified by call-count
assertions in `test_command_suggestion.py` (fixture LLM transport, no
mocks of companion-core's own code). reachy-hub now calls Telegram's
`setMyCommands` at startup (best-effort) to register the three flat
aliases in its bot menu. The operator UI's web chat renders `/reachy`
command autocomplete while typing and a real clickable button under any
reply containing a suggested `/reachy <action>` command — clicking it
re-sends the literal command text through the normal `/messages` path
(the click is the authorization event), never via HTML injection (Chromium
Playwright test "web chat renders command autocomplete and dispatches
suggested-command buttons" in `clients/operator-ui/tests/chat.test.cjs`).
All
of docs/phase-24b.md's negative conversational examples ("How do I turn
off Reachy?", "Don't turn off Reachy.", etc.) are covered by parametrized
tests proving no actuation and, separately, that the classifier itself
resolves them to a non-`"request"` speech act rather than merely failing
to match. Route strings `/robots`, `/robots/standby`, `/robots/resume` are
now `shared/protocols/operator_api.py` constants, imported by both
`hub_client.py` and `reachy_hub/app.py`'s route decorators, per AGENTS.md.
**Verified only against isolated fixtures** (`pytest services shared`:
463 passed; `ruff check services shared`: clean; both operator-ui
Playwright suites pass) — no live Telegram bot run, no real robot
actuation, and the `/reachy gesture <name>` syntax `docs/phase-24b.md`
uses as an illustrative example is deliberately **not** parsed
(`_KNOWN_ACTIONS` covers only the three actions actually wired to a hub
call, per AGENTS.md's "no speculative endpoints" rule).

Phases 0–21 and 22a are implemented. Phase 23 implementation is complete:
versioned migrations, SecretStore, owner-bound Google OAuth, Accounts UI and
read-only Gmail/Calendar integration. Ordinary users select Connect, then enter
their username/password and approve permissions on Google's own screens.
See [ADR 0021](docs/adr/0021-google-accounts.md),
[deployment setup](docs/deployment.md) and
[Accounts evidence](docs/verification/phase-23-accounts-2026-09-23.md).

Phase 23b (2026-09-24) added a Desktop OAuth client transport alongside the
Web application client: a self-hosted install without a stable public HTTPS
hostname can now authorize Gmail/Calendar via a loopback PKCE helper
(`tools/google_auth_helper.py`) instead of provisioning a domain/DNS/
certificate purely for OAuth. Core/Hub ownership is unchanged; see
[ADR 0021's addendum](docs/adr/0021-google-accounts.md#addendum-phase-23b-2026-09-24-desktop-oauth-client-transport).
Migration `005_desktop_oauth` adds a `client_type` column to
`google_oauth_states`. Isolated-fixture tests cover the desktop flow and its
failure cases; no live Desktop-client consent run was performed this session.
See [verification](docs/verification/phase-23b-desktop-oauth-2026-09-24.md).

Migration `004_persona` (2026-09-23) added a configurable assistant identity:
`persona_config` (name + system prompt), owner-editable via the operator UI's
"Assistant persona" card or `GET`/`PUT /settings/persona` (hub proxy to core).
The persona's system prompt is prepended only on the generic LLM conversation
branch — see [docs/reference/services.md](docs/reference/services.md) for the
exact boundary with deterministic intent replies, which never see it.

Next: configure the installation's Google application (Desktop app client
recommended, or Web application with an HTTPS callback), then perform
real-account consent/read/refresh/revoke/reconnect and audience checks. No
OAuth client file, deployed HTTPS hostname, or live helper run was supplied
this session. Phase 23/23b are not yet production-accepted. The
Google-enabled physical repeat remains deferred. Phase 24a is implemented
against a fixture provider (see above); Phases 24b–27 remain planning only.

Phase 22b (physical acceptance) started 2026-09-23 with the owner physically
present, coordinated across a homelab-side and a Nano-side Claude Code
session. Fixed a real bug blocking outbound WSS: `RobotWSClient` never
derived `ws(s)://` from the configured `http(s)://` `HUB_WS_URL` (commit
`5443a93`). With that fix, `nano-1` registered over WSS through Caddy for
the first time (real, non-simulated). The real daemon then started
successfully (`sim=false`), but **the first-ever command to real motors
found a head-motion hardware fault**: antennas track commanded poses
correctly, the head (Stewart platform) does not. A per-joint diagnostic
read (`/api/state/full`, offline IK cross-check) first isolated `stewart_5`
as the dominant error; after the owner manually adjusted the head and
retested, a second `goto`-to-zero showed **three motors (`stewart_2`,
`stewart_4`, `stewart_5`) don't respond to position commands at all**,
while `stewart_1`/`3`/`6` track normally — a shared cause (power/bus
segment, thermal/current protection, or shared mechanical binding) looks
more likely than three independent motor failures. Motion testing was
stopped by owner decision; the daemon was stopped cleanly before ending
the session so no further command could reach the motors during physical
inspection. See
[first-motion evidence](docs/verification/phase-22b-first-motion-2026-09-23.md)
for exact figures/timestamps. **Do not resume motion testing until motors
2, 4 and 5 have been physically inspected** (wiring/linkages/any visible
error state) — this is a hardware finding, not an embodiment/software
defect (the command chain itself dispatched and reported correctly
throughout, and the current head position must not be saved as a
calibration/homing offset since it isn't a true zero).

The owner then set a pragmatic acceptance bar (not the robot's
manufacturer; if shipped behaviours look acceptable despite the known
offset, that's sufficient) and confirmed all 14 of `_DEFAULT_BEHAVIOUR_
MOVES` acceptable by direct observation — cross-checked against the
official Reachy Mini app, whose own opening animation showed the same
kind of tilt. **The owner then explicitly decided not to pursue
`stewart_5` physical inspection/repair further** — not the robot's
manufacturer, and named behaviours only need to convey action/emotion, not
reach exact commanded joint angles. Motion/fallback is accepted closed on
that basis for Phase 22b; only re-open if it produces genuinely unsafe or
unacceptable-looking motion in practice.

Daemon audio (`playbin failed to activate sinks`, no animation sound
effects) was root-caused and fixed: a stale `~/.asoundrc` referenced a
USB audio card index that no longer existed after re-enumeration, plus an
autospawned PulseAudio instance holding the device. Fixed by regenerating
`~/.asoundrc` via the package's own detection, disabling PulseAudio
autospawn, and raising the mixer — owner confirmed audio audible.
`scripts/start-reachy.sh` now re-runs that detection and resets the mixer
on every real daemon start (not just install), so a future re-enumeration
can't silently regress it again. Microphone capture was separately
confirmed working (owner's voice recognizable on a recorded/played-back
sample) — this tests only the physical mic/ALSA path, not our own voice
feature: there is still no code routing the robot's mic into the
homelab's `/voice/turn` STT pipeline, unscoped future work.

Added remote standby/resume (Phase 22b, owner-requested): a deterministic
phrase match in `companion_core.robot_power_intent` (e.g. "turn off
reachy"/"wake up reachy", any channel) calls a new authenticated
`POST /robots/standby`/`resume` on reachy-hub, which wraps the real
daemon's own `POST /api/daemon/stop?goto_sleep=true`/`start?wake_up=true`
(found via its `/openapi.json` — parks at its canonical rest pose and
de-torques motors, safe to physically handle; no systemd/sudo access
needed anywhere). Bypasses the LLM entirely, same precedence as every
other deterministic intent. Resume replays the daemon's wake-up motion
unattended from an owner-authenticated channel — a further owner-approved
exception alongside the boot-autostart one, recorded in AGENTS.md/
deployment.md. Full companion-core → reachy-hub → reachy-embodiment chain
covered by new tests (387 passed total, up from 371); **UNVERIFIED against
real hardware** — the daemon's stop/start endpoints have not been called
live yet, only confirmed present via its OpenAPI/source.
**Known issue, closed 2026-09-24:** `robot_power_intent`'s substring match
had no negation/question/hypothetical awareness, so conversational text
like "How do I turn off Reachy?" or "Don't wake up Reachy" actuated the
real standby/resume path on an owner-authenticated channel, the same as an
actual command. Left unfixed in place at the time pending a structured
redesign rather than patched piecemeal — owner's explicit call, 2026-09-24
— and closed later the same day by [Phase 24b](docs/phase-24b.md) (see
above): `robot_power_intent` is now retired entirely, and only the
explicit `/reachy standby`/`wake` command (or its Telegram alias) reaches
this path.
[Phase 27](docs/phase-27.md) was refocused 2026-09-23 from a generic virtual
meeting bot to an embodied secretary: owner-present meeting companion (27a);
a bounded temporary-absence catch-up mode for short owner step-outs within an
already-running 27a meeting (27a.2), which tracks decisions/questions/
deadlines during the absence via an explicit `AbsenceWindow` and delivers a
private, interval-bounded delta on return; physical secretary attendance
while the owner is absent for most/all of a meeting (27b); then bounded
delegation of pre-approved questions/statements or the owner's own verbatim
reply (27c). Virtual/cloud bot joining is now deferred, not a prerequisite.
Owner-directed questions must be forwarded privately via Telegram or another
bound channel from 27a onward; the platform must never answer for the owner.
Next planning gate: 27a needs no ADR amendment (owner present throughout);
27a.2 needs a *narrow* Phase 25 ADR amendment for a capped
`TEMPORARY_MEETING_ABSENCE` lease (meeting-STT-only, no tool/general-speech
authority, auto-expiry, no silent extension into unattended recording); 27b
requires the *full* owner-absent meeting-capture-mode amendment plus
supervised hardware acceptance. These are two separate amendments, not one —
continuing to record while the owner briefly steps out is still technically
owner-absent capture under Phase 25's presence-based rule, even though the
recording began while they were present.

Phase 22b continued 2026-09-24 (owner physically present, coordinated across
a homelab session and a Nano-connected session): found the daemon silently
in an error state (motors undetected, likely power) despite systemd
reporting it active; owner checked power and restarted it themselves,
after which it came up healthy. A real camera capture then succeeded
end to end, which surfaced that the existing capture_frame implementation
(release/acquire+OpenCV) interrupts the daemon's whole media pipeline per
call; `capture_frame` was refactored to reachy_mini's recommended LOCAL
media backend (code+tests done, real-device build/run still open). See
[camera evidence](docs/verification/phase-22b-camera-2026-09-24.md) above.

No production deployment was upgraded. This session did bring up and upgrade
the homelab's own disposable dev/test stack (through `004_persona`) for
interactive user testing — real owner login, OpenVINO local LLM routing with
a Together AI cloud fallback, and a bound Telegram owner chat all live there,
but it is not the production-accepted deployment Phase 23 still gates on.
Current code requires revision `005_desktop_oauth`, a separate 0600
`SECRET_KEY_FILE`, and `ACCOUNTS_SERVICE_TOKEN` in both core and hub. Stop old
writers and back up before a real cutover. See the canonical deployment guide
for migration, authentication and Telegram binding
requirements. The Caddy core data proxy is closed; Accounts requires owner
cookies/CSRF, while work APIs retain authenticated owner bearer access.
Both disposable verification stacks/volumes and their temporary key/env files
were removed; the pre-existing OVMS container was left running.

## Verification and open acceptance

- Phase 23 final fast suite: **366 passed, 2 espeak-dependent skips, 10 slow
  tests deselected**, with real Postgres checks enabled. Ruff and both Chromium
  suites passed. Built images/HTTP and real browser checks used a local Google
  fixture; encrypted restore, concurrent refresh, restart, private chat/briefing
  and proxy-log redaction passed. These are not real Google/physical acceptance.
  The existing homelab launcher waits only for hub health; independently
  check core readiness before inference acceptance.
- [Implementation history](docs/verification/history.md) records Phases 0–21,
  including the successful real Together AI / `zai-org/GLM-5.3` cloud-role
  check. It was a disposable deployment, not a production configuration change.
- [Phase 22a evidence](docs/verification/phase-22-bring-up.md) consolidates
  backend, launcher, WS, and simulator checks. The
  [inventory](docs/verification/phase-22-inventory-2026-09-22.md) preserves raw
  physical-machine findings and dependency/device/memory measurements.
- The real Nano daemon woke the robot on startup and embodiment reported
  connected/non-simulated. Named moves were subsequently exercised through
  the real daemon's **simulator**, not physical Nano motors.
- WS registration/auth/heartbeat/reconnect is implemented; semantic commands
  still use the old inbound HTTP path. TLS/network-change/media acceptance,
  clean-image provisioning, and soak/restore checks remain open. Use the
  [acceptance matrix](docs/phase-22-23.md#satisfactory-run-acceptance-matrix).
- **Phase 22c — camera LOCAL-backend acceptance, split out separately
  (2026-09-24)**: a real `GET /camera/frame` capture succeeded against
  physical hardware (1920x1080, no simulator marker) via the then-current
  release/acquire+OpenCV path, but without a deliberate scene change, so it
  doesn't yet satisfy the acceptance matrix's "fresh scene corresponds to a
  command" bar. That capture also showed the release/acquire approach tears
  down the daemon's whole media pipeline (audio+WebRTC) for ~2.5-4s per
  call, so `ReachyDaemonBackend.capture_frame` was refactored to reachy_mini
  SDK's recommended LOCAL media backend instead, then hardened further
  (explicit host/port/`connection_mode="localhost_only"` instead of relying
  on mDNS, thread-safe lazy client construction, construction/`get_frame()`
  failures wrapped as `RobotBackendError`, a `close()` shutdown hook) —
  code and unit tests are done (381 passed, up from 371), but the Docker
  image/container has not been rebuilt or run against the real daemon
  socket on the Nano: the companion board went offline mid-session before
  that could happen. **Earmarked as its own roadmap phase (22c in
  [docs/plan.md](docs/plan.md#6-implementation-roadmap)) for physical
  testing once the board is back**, rather than folded into 22b's full
  matrix. See
  [Phase 22b camera evidence](docs/verification/phase-22b-camera-2026-09-24.md)
  for exact figures and what remains unverified. Physical voice/motion
  acceptance also remains open per the matrix above.

## Machine-specific continuation notes

- The Nano is the sole embodiment host; losing it makes the robot inert.
  Recheck daemon/container state before assuming either is running.
  Starting the daemon wakes/moves the robot: owner presence and supervision
  are required. `--check` must never start hardware.
- Nano uses host-networked embodiment on 8100 and the loopback daemon on
  8000. Existing `.env` copies can retain obsolete bridge URLs after code
  defaults change. See [deployment](docs/deployment.md#robot-host-and-jetson-nano).
- The homelab's existing `ovms` container previously served
  `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` at `localhost:8000`; re-query
  `/v1/models` to confirm. Leave unrelated running services alone during tests.
- Hosted credentials were placed in gitignored `deploy/homelab/.env.local`
  (`TOGETHER_API_KEY` and `CLOUD_LLM_*`). Check presence without printing
  values. Temporary verification credentials/stacks were removed in prior
  sessions; no permanent owner account is implied by a successful test.
- Optional caches previously available: espeak at
  `/tmp/espeak-extract/usr/bin`, Playwright under
  `~/.npm/_npx/e41f203b7505f1fb/node_modules`, Chromium under
  `~/.cache/ms-playwright`. They may disappear; setup and sandbox socket
  caveats are centralized in [development](docs/development.md).

Before implementation, inspect `git status`, recent commits, and any existing
diff. The previous hardware work involved a separate Nano-side session;
verify raw device identity when accepting future remote hardware reports.
