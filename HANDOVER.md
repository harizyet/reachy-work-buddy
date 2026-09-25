# Handover

Current session snapshot, updated 2026-09-25. Read [AGENTS.md](AGENTS.md)
before working. Durable instructions belong in the [documentation index](docs/README.md),
not repeated in this file.

## Current work

Next priority: **[Phase 24d](docs/phase-24cd.md#phase-24d--physical-end-to-end-acceptance)**,
supervised physical acceptance of the robot conversation workflow, **in
progress** since 2026-09-24. Follow the
[24d hardware procedure](docs/phase-24cd.md#phase-24d-hardware-procedure);
evidence is in the
[24d record](docs/verification/phase-24d-conversation-2026-09-24.md). Phase 25
remains gated on 24d. **24d proves the physical workflow, not answer
quality** (owner, 2026-09-25): the formal ≥10-turn run uses deterministic
context turns (code word, block count, project name) plus one or two
separate search-assisted turns whose factual accuracy is 24a scope.

To close 24d, in order:

1. **Boot race (the real blocker).** Installed on the Nano 2026-09-25
   (unit enabled, container recreated with `--mount` and no restart policy,
   live recovery passed, launcher idempotency bug fixed in `02f9538`). See
   the [record](docs/verification/phase-24d-conversation-2026-09-24.md#boot-race-fix-on-the-nano-2026-09-25).
   **Still to do, with the owner present:** a real cold reboot (socket
   `srw… reachy`, container starts after the daemon, camera and voice work
   with no sudo step), then `sudo systemctl restart reachy-mini-daemon`
   (the container restarts and the camera still works).
2. ~~Agree the search-turn latency budget~~ Done 2026-09-25: each
   search-assisted turn ≤ 20 s (non-search stays p50 ≤ 4 s, p95 ≤ 8 s).
3. **Formal run** of the matrix rows. The results table is still mostly
   OPEN/PARTIAL.

24d state so far:

- **Done on the real Nano.** Preflight, voice enable, and step 3 device
  coexistence passed. A behaviour sound, a camera frame and live voice
  capture ran together through dmix/dsnoop, with no ALSA/shm errors. The
  owner held two short live sessions (Piper TTS). Robot-side per-turn
  timings are in the record.
- **Deployed robot image.** `reachy-embodiment:local` is built from
  `1a66f01` (voice enabled, INFO timing logs). Image fixes found on the
  hardware: the GstApp/GstPbutils typelibs and ALSA plugin, and removing
  `libgstonnx.so`, which SIGILLs on the ARMv8.0 Cortex-A57.
- **Hardware watch.** `stewart_5` logged "Overheating Error" for 20+ min
  while the head held a strained pose. It cleared after a reboot and motor
  reset, but the cause is unknown. Check the daemon journal for recurrence.
- **Homelab stack (dev/test, not production-accepted).** Start it only
  through `scripts/start-homelab.sh`. Schema `008_assistant_context`;
  hub/core run `0144209` plus uncommitted work (UI no-cache headers, search
  debug log, follow-up search, owner context). Dumps before each upgrade
  are in `~/reachy-backups/` (0600): `…phase24d-20260924T213146`,
  `…007-search-providers-20260925T003652`,
  `…008-assistant-context-20260925T011257`. The hub speaks with Piper
  `en_US-lessac-medium`; each `GET /robot-voice` turn record carries
  transcription/conversation/synthesis ms.
- **Reply length.** `af27338` asks the model for 1–3 plain sentences on
  voice turns and strips `[S…]`/markdown before TTS. Utterance-end → first
  audio was 2.5–3.6 s without search in preliminary runs.
- **Search quality is 24a follow-up work, not a 24d gate.** The bundled
  SearXNG was CAPTCHA'd/suspended from this address, so search now rotates
  hosted Brave, Exa and Tavily within their free tiers (SearXNG last),
  with follow-up search and owner date/time/location context (persona set
  to Singapore), results = 5 and policy `auto`. All live-verified; see the
  [ADR 0022 addenda](docs/adr/0022-web-search-grounding.md#addendum-hosted-provider-rotation-within-free-tiers-24a-follow-up-2026-09-25)
  and the [24a record](docs/verification/phase-24a-search-assisted-2026-09-24.md#addendum--hosted-provider-rotation-and-multi-turn-check-2026-09-25).
  Search picks the right query every turn, but the local `Qwen2.5-1.5B`
  still misuses results and search turns ran 7–16.5 s. The owner kept the
  local model; GLM-5.3 (cloud) is the option if 24a quality needs it.

Phase 24c (robot microphone → conversation → speaker) is implemented
(2026-09-24). See [ADR 0023](docs/adr/0023-robot-voice-conversation.md), the
[audit table](docs/phase-24cd.md#phase-24c-audit-result-2026-09-24) and the
[verification record](docs/verification/phase-24c-conversation-2026-09-24.md).

- **Design.** The owner starts or stops it from the operator UI (Chat → Robot
  microphone), with a hub-owned lease. The hub sends `voice_start`/`voice_stop`
  over the existing WSS socket. The robot uploads each VAD-bounded utterance
  to `POST /robot-media/voice-turn` with its robot token. The hub runs STT →
  the shared conversation (`reachy`, VOICE) → ADR 0006 routing plus a
  DND/meeting veto, and synthesizes only permitted replies. Withheld replies
  go to the owner panel and Telegram. It is half-duplex, and Stop calls
  daemon `stop_sound`.
- **Opt-in.** Robot-side `VOICE_CONVERSATION_ENABLED=true`, then
  `docker rm -f reachy-embodiment` and restart via `start-reachy.sh`, which
  adds `--ipc host`, the daemon UID and the daemon user's `~/.asoundrc`. See
  [deployment](docs/deployment.md#robot-voice-conversation).
- **Verified off the robot only**: pytest (503 passed), Chromium, and a
  disposable Compose run with a simulated mic, real Whisper, real OVMS LLM
  and espeak through Caddy/WSS. Multi-turn context and a web handoff worked.
- **Bugs fixed on the way:**
  - Hub STT/TTS construction blocked the event loop and disconnected the
    robot.
  - espeak's placeholder WAV header would have stalled the robot ~13 h per
    reply.
  - `/reachy` commands were parsed from voice transcripts.
- **Since verified on the robot (24d):** mic capture and dsnoop sharing from
  the container, daemon playback, and the stop tail (about 32 ms from
  `voice_stop` to daemon `stop_sound`). Acoustic echo is still unassessed.
- **Fixed during 24d:** core's sticky conversation privacy used to keep
  later replies off the speaker after any keyword-private reply (`c65c9cd`).
  The hub's WS watchdog was raised from 5 s to 15 s after a tailnet stall
  (`3c6e49f`).

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
round-trip). A Brave Search API provider was added during 24d (`af27338`)
and is fixture-verified only; live calls wait for the owner's key.
**Not yet done:** production acceptance of the running homelab stack with
this service and a non-Off policy. See [ADR 0022](docs/adr/0022-web-search-grounding.md)
and [verification](docs/verification/phase-24a-search-assisted-2026-09-24.md).

Phase 24 cleanup (2026-09-24, same session as 24b below): removed the two
remaining manual-setup steps a review flagged, for the **supported
launcher path**. `SEARXNG_SECRET_KEY` (the bundled SearXNG container's own
internal server secret, never a user credential) is no longer something
an operator sets when starting via `scripts/start-homelab.sh` — it
generates and persists the secret itself
(`deploy/homelab/.env.searxng-secret`, `0600`, gitignored via `.env.*`),
exporting it so Compose's `${SEARXNG_SECRET_KEY:?...}` interpolation
resolves without touching `.env`; `--check` stays read-only (a throwaway
in-memory value only, nothing written). This is specific to the
launcher: an operator running `docker compose` directly still must set
`SEARXNG_SECRET_KEY` themselves — "zero-configuration" describes the
launcher path, not raw Compose, deliberately (see the phase-24a
verification addendum for why a raw-Compose fix wasn't pursued). A new
`SearchProviderKind.BUILTIN_SEARXNG` (now
`SearchConfig`'s default) needs no Base URL or API key at all —
`companion_core/websearch/provider.py` hardcodes the bundled container's
internal address (`http://searxng:8080`); the prior `SEARXNG` kind is
relabeled "External SearXNG" in the operator UI and is unchanged
otherwise (still requires and stores its Base URL/API key via
`SecretStore`). The operator UI's "Web search" card also got its first
browser test (`clients/operator-ui/tests/websearch.test.cjs`, new) —
closing the "not exercised in a real browser" gap the 24a verification
record above had flagged. See that record's 2026-09-24 addendum for exact
before/after detail and test names.
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
All of docs/phase-24b.md's negative conversational examples ("How do I
turn off Reachy?", "Don't turn off Reachy.", etc.) are covered by
parametrized tests proving no actuation and, separately, that the
classifier itself resolves them to a non-`"request"` speech act rather
than merely failing to match. Route strings `/robots`, `/robots/standby`,
`/robots/resume` are now `shared/protocols/operator_api.py` constants,
imported by both `hub_client.py` and `reachy_hub/app.py`'s route
decorators, per AGENTS.md. **Verified only against isolated fixtures**
(`pytest services shared`: 466 passed; `ruff check services shared`:
clean; all 5 operator-UI Playwright suites pass) — no live Telegram bot
run, no real robot actuation, and the `/reachy gesture <name>` syntax
`docs/phase-24b.md` uses as an illustrative example is deliberately
**not** parsed (`_KNOWN_ACTIONS` covers only the three actions actually
wired to a hub call, per AGENTS.md's "no speculative endpoints" rule).
See [verification](docs/verification/phase-24b-command-authorization-2026-09-24.md)
for the full negative-example/alias/timeout/button/Telegram-registration
test inventory.

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
and real-SearXNG-verified, and Phase 24b is implemented and isolated-
fixture/browser-verified (see above for both); Phase 24c is implemented
(above); Phases 24d and 25–27 remain open or planning only.

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
feature. At the time there was no code routing the robot's mic into the
homelab's STT pipeline; Phase 24c has since added it (unverified on hardware,
see above).

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
media backend (since run on the Nano during 24d; see the 22c note below). See
[camera evidence](docs/verification/phase-22b-camera-2026-09-24.md) above.

No production deployment was upgraded. The homelab's disposable dev/test
stack (now at `006_search_config`, see Current work) was brought up earlier for
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
  code and unit tests are done (381 passed, up from 371). **Update
  2026-09-24 (24d):** the rebuilt image now captures through the LOCAL
  backend against the real daemon socket on the Nano: repeated 200 JPEG
  1920x1080 frames, running as the daemon UID. The first frame after each
  container start takes ~9–12 s because GStreamer loads plugins in-process.
  The external plugin scanner can't spawn under Docker 20.10.7's seccomp
  (`close_range` gets EPERM), a known limitation that was deliberately left
  as is. The "fresh scene corresponds to a command" bar of
  [22c](docs/plan.md#6-implementation-roadmap) is still open. See
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
- **Nano reboot recovery (until the boot-race fix is installed and
  reboot-verified).** Symptom: after a reboot `/tmp/reachymini_camera_socket`
  is a root-owned directory, the container exits 127, and the daemon logs
  "Failed to initialize media server" (EPERM). `start-reachy.sh --check`
  now reports this. Recover in this order:
  1. The owner runs `sudo rm -rf /tmp/reachymini_camera_socket`.
  2. The owner runs `sudo systemctl restart reachy-mini-daemon`, present and
     watching the wake-up motion. Sessions on the Nano have no
     passwordless sudo.
  3. Wait for the daemon to recreate the socket (`srw… reachy`), then run
     `scripts/start-reachy.sh` (with the fix it replaces the old container).
  4. Warm the camera with one `GET /camera/frame`.
  The fix adds a new unit but leaves `reachy-mini-daemon.service`
  unchanged.
- Nano image builds need BuildKit. `start-reachy.sh --build` sets
  `DOCKER_BUILDKIT=1`. For a manual `docker build`, set it yourself.
- The Nano's Tailscale path to the homelab host switches every few minutes
  between 10.180.1.23, .54 and .254. One stall caused a WS watchdog
  disconnect at the old 5 s timeout. Network cleanup is the owner's call.
- `/tmp` is cleared on reboot. Keep captured logs under a home directory
  (24d uses `~/24d-logs/`).
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
