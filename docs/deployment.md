# Deployment

This guide owns installation, configuration, startup, and operational
troubleshooting. For using the running application, see the
[operator guide](operator-guide.md). Environment templates remain beside
the deployment files: [homelab](../deploy/homelab/.env.example) and
[robot host](../deploy/reachy/.env.example).

## Homelab

Requires Docker, Compose v2, and BuildKit/buildx; see
[development setup](development.md#docker-toolchain) if a plugin is missing.
Run from the repository root:

```bash
cp deploy/homelab/.env.example deploy/homelab/.env
chmod 600 deploy/homelab/.env
# Edit .env: set POSTGRES_PASSWORD, owner login, ACCOUNTS_SERVICE_TOKEN,
# and SECRET_KEY_FILE using the procedures below.
scripts/start-homelab.sh --check
scripts/start-homelab.sh --build
```

The launcher validates configuration, starts Postgres/pgvector, core, hub,
and Caddy, waits for hub health, then opens or prints the GUI URL.
`--no-browser` suppresses browser launch; `--env-file PATH` selects another
environment file. Re-running uses Compose's existing containers. Check both
`http://localhost:8080/hub/health` and `/core/health` before integration tests;
Compose returning does not mean FastAPI has finished starting.

The equivalent manual start is `docker compose up -d --build` from
`deploy/homelab/`. Production mode does **not** start the simulated robot
or Mailpit. All deployment credentials are local files, not committed
configuration; `.env.*` is ignored while `.env.example` is tracked.

## Simulation

```bash
scripts/start-homelab.sh --simulation --build
```

The `simulation` Compose profile adds `reachy-embodiment` with its simulated
backend and Mailpit (`http://localhost:8025`). Manual equivalent:
`docker compose --profile simulation up -d --build` from `deploy/homelab/`.
Register the simulated robot before robot-control checks:

```bash
curl -X POST http://localhost:8080/hub/robots \
  -H 'Content-Type: application/json' \
  -d '{"robot_id":"desk-1","base_url":"http://reachy-embodiment:8000"}'
```

Use [workflow examples](reference/workflow-examples.md) for conversation,
calendar, task, memory, document, and email smoke checks. Those examples
mutate test data and are intended for a disposable simulation stack.

## Owner login

Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and an independent random
`SESSION_SECRET_KEY` before startup. Open `http://localhost:8080/hub/ui/`.
The owner is created only when the users table is empty: changing the
bootstrap password later does not reset that account. Keep the signing key
stable across restarts; rotating it invalidates existing sessions.
Set `SESSION_COOKIE_SECURE=true` when using HTTPS; local HTTP defaults false.

Cookie mutations and login/logout require `X-Reachy-CSRF: 1`. The browser
supplies it. `REMOTE_UI_TOKEN` still enables bearer access for machine
clients; core's `/debug/robots/...` proxy needs that same token in both
services because it does not use browser cookies. Protected routes return
503 if neither owner-session nor bearer access is configured, otherwise
401 for missing/invalid credentials. Logout clears the browser cookie;
there is no server-side session revocation list.

## Model endpoints

Configure model URLs, names, keys, and routing in the operator UI; see
[hybrid inference](operator-guide.md#hybrid-inference-phase-21) for behavior.
Settings persist in Postgres and apply to the next turn without a restart.
Use an endpoint that supports `{base_url}/chat/completions`; a native vendor
API may need a compatible gateway. Discover an OVMS model by querying
`GET /v1/models` rather than guessing its name.

Inside core's container, `localhost` refers to that container. For an OVMS
server on the Linux Docker host, save this as a Compose override and pass
both files to Compose, or use the standard `compose.override.yaml` in the
homelab directory:

```yaml
services:
  companion-core:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

Use `http://host.docker.internal:8000/v1` as the provider URL, or a reachable
LAN URL for a remote server. Keys are masked in responses and stored
encrypted through core's SecretStore after the Phase 23 upgrade. Protect
the separate key file and historical plaintext backups; see
[upgrade and recovery](#schema-upgrades-and-credential-keys).

For assisted live verification, put `CLOUD_LLM_BASE_URL`, `CLOUD_LLM_MODEL`,
and `CLOUD_LLM_API_KEY` in gitignored `deploy/homelab/.env.local`, never chat.
These are verification inputs, not automatically loaded runtime settings.
The hosted-provider evidence and reasoning-model token-budget caveat are in
[verification history](verification/history.md).

## Web search

Phase 24a's search-assisted assistant is off by default (`search_config`'s
policy starts `off`, no outbound calls). `docker-compose.yml` ships a
self-hosted `searxng` container (internal-only — never published to the
host, same as mailpit's SMTP port) so enabling it needs no separate
install. Phase 24 cleanup: `scripts/start-homelab.sh` generates and
persists this container's internal server secret itself
(`deploy/homelab/.env.searxng-secret`, `0600`) — no `SEARXNG_SECRET_KEY`
setup step in `.env` is needed when starting the stack through this
launcher (only set it yourself if you deliberately want a fixed value).
This zero-configuration behaviour is specific to the launcher path: an
operator who invokes `docker compose` directly instead still must set
`SEARXNG_SECRET_KEY` themselves, since Compose's own `${...:?...}`
requirement in `docker-compose.yml` has no way to run the launcher's
generation step. In the operator UI's Settings →
Web search card, choosing **Built-in SearXNG** and Auto or Always is then
the entire setup — no Base URL or API key entry, since Companion Core
already knows this container's internal address. `deploy/homelab/
searxng/settings.yml` enables the JSON API and disables the
public-instance rate limiter — both appropriate only because this
instance is reachable solely from other containers on the compose network,
never the public Internet. A self-hosted SearXNG instance keeps Reachy's
own query confined to this container, but SearXNG itself still forwards
each query to whichever upstream engines its own configuration uses — this
isn't full network confinement, and the operator UI states that plainly.
Choosing **External SearXNG** as the fallback instead (a separately-run
instance) is a separate, explicit opt-in via the same card, and does need
its own Base URL (API key optional). A credential entered there is stored
via Companion Core's SecretStore (`secret_ref`), never alongside the
bundled container's own deployment secret; see
[ADR 0022](adr/0022-web-search-grounding.md) and
[docs/phase-24a.md](phase-24a.md).

The bundled SearXNG keeps only Google, Bing and Brave, with a 1.5 s
per-engine timeout (the image disables Google and Bing, so the config
enables them). These are scraped engines. During Phase 24d, the homelab's
address was CAPTCHA'd and suspended by Google and Brave, and Bing returned
unrelated pages, so SearXNG is now only the **last-resort fallback**.

For dependable results, enable one or more hosted providers in the same
card (**Brave Search API**, **Exa**, **Tavily**) and enter each one's API
key. Their endpoints are fixed, so no Base URL is needed. Keys are stored
through SecretStore (`websearch:brave`, `websearch:exa`,
`websearch:tavily`) and shown only masked, and queries go directly to
that company. Each turn still makes one search. It goes to the enabled
provider that has used the smallest share of its **monthly search limit**
(calendar month, UTC), and moves to the next provider on an error. SearXNG
runs only after every hosted provider failed or reached its limit. Calls are
counted in `search_usage` before they are sent, so restarts and concurrent
turns can't exceed a limit. A provider that answers with a plan-limit status
(402, or Tavily's 432/433) is skipped for the rest of the month. The
**Search API usage** card shows this month's count for each provider. Its
**Open search debug log** button lists the last 50 searches: query, which
provider served it, each attempt's outcome and time, and the results. Core
keeps that log in memory only (`GET /websearch/log`, owner-authenticated
through the hub). It is never written to the database, and a restart clears
it.

Set **Location** and **Time zone** on the Assistant persona card. Each
conversation turn gives the model the local date, time and location, and a
weather question that names no place is searched for that location, so the
search provider receives it. Under Auto, a follow-up to a searched turn
("When was it released?", "What about tomorrow?") searches too, using the
earlier query as its topic.

The default limit is 900 per provider, below each free allowance as of
2026-09. Brave gives $5 of monthly credit (about 1,000 queries) and **bills
the card on file after that**. Exa's free balance is $10 a month, about
1,250 searches with highlights. Tavily gives 1,000 basic-search credits a
month. Reachy counts only its own calls, so lower a limit if the same key is
used elsewhere, or if the provider's billing month doesn't start on the
1st. Check the providers' current terms before raising a limit.
Migration `007_search_providers` turns an existing Brave selection into an
enabled Brave entry, keeping its key.

## Telegram and SMTP

`TELEGRAM_BOT_TOKEN` enables text polling; unset means no bot. Set
`TELEGRAM_DEFAULT_USER_ID` to the same conversational ID used in web/robot
channels. The user must message the bot first so it can learn a reply chat
ID. Telegram voice notes are not wired into STT.

Simulation email goes to Mailpit. Production `SMTP_HOST`, `SMTP_PORT`, and
`SMTP_FROM` select a relay; the current sender has no SMTP authentication
support. Email approval and send requests require text, then enter an undo
window before dispatch. Production defaults to roughly ten minutes. For a
disposable test only, `EMAIL_SEND_DELAY_SECONDS=10` and
`EMAIL_DISPATCH_INTERVAL_SECONDS=2` shorten that wait. See
[ADR 0011](adr/0011-destructive-action-consent.md) for consent semantics.

## Robot host and Jetson Nano

The confirmed deployment is a USB-attached Reachy Mini with an original
Jetson Nano as its sole embodiment host. The homelab is separate. Nano loss
makes the robot inert; homelab loss must still permit local fallback.
Keep diagnostic captures under a persistent home-directory path: `/tmp` is
cleared on reboot. Before interpreting boot logs, check NTP synchronization;
the Nano RTC has lost time across power-offs, making pre-NTP timestamps stale.
Recheck daemon and container state before relying on a previous session report. See
[ADR 0004](adr/0004-offline-fallback.md#phase-22-topology-amendment-2026-09-22).

The Nano's Ubuntu 18.04/glibc 2.27 cannot install the repo's native ML wheel
set. Run embodiment in the verified newer-glibc container; run
`reachy-mini-daemon` separately in its Python 3.10 environment. The
[installer](../deploy/reachy/install-reachy-venv.sh) and
[systemd unit](../deploy/reachy/reachy-mini-daemon.service) reconstruct the
working setup, but the installer has **not** been validated from a clean SD
card; its PyGObject/GStreamer caveats remain. Inspect those files before
installation. The [inventory report](verification/phase-22-inventory-2026-09-22.md)
records device groups, memory measurements, and dependency checks.

`install-reachy-venv.sh` does not install the systemd unit itself — found
live when a unit-file change (the `ExecStartPre=` above) silently had no
effect because `/etc/systemd/system/reachy-mini-daemon.service` is a
separate root-owned copy, not a symlink to the repo file. After any change
to `deploy/reachy/reachy-mini-daemon.service`, reinstall it explicitly:
`sudo cp deploy/reachy/reachy-mini-daemon.service /etc/systemd/system/ &&
sudo systemctl daemon-reload`. Verify what's actually active with
`systemctl show reachy-mini-daemon -p ExecStartPre` (no sudo needed) rather
than assuming a repo change took effect.

Starting the daemon wakes/moves the robot by default. Only start it while
the owner is physically present and supervising. `--check` must remain
read-only and never start the daemon. This applies to every dev/test host;
a designated production Nano is a deliberate, owner-accepted exception
(below), not a relaxation of the general rule.

Named-behaviour playback (`POST /behaviour/{name}`, the mapped, bounded,
pre-recorded moves) does not require the owner watching each call —
owner's explicit decision, 2026-09-23: the robot is small with no
meaningful bystander risk, and this class of motion is bounded and
pre-recorded. Daemon start/restart and raw/diagnostic joint commands
(`POST /api/move/goto`, or investigating a problem live) still need the
owner present — see [AGENTS.md](../AGENTS.md) for the exact boundary.

Remote standby/resume (`POST /robots/standby`/`resume` on reachy-hub,
triggered only by the explicit `/reachy standby`/`/reachy wake` command —
or a registered channel alias — parsed by `companion_core.commands.
parser`, over Telegram or any other bound channel; Phase 24b retired the
prior free-form phrase match, see [phase-24b.md](phase-24b.md)) is a
further exception, also
owner-approved 2026-09-23: standby parks the real daemon at its own rest
pose and de-torques motors (`POST /api/daemon/stop?goto_sleep=true`,
safe to physically handle afterwards); resume replays the daemon's normal
wake-up motion (`POST /api/daemon/start?wake_up=true`) without the owner
physically present, on this same designated production host — gated by
`require_remote_auth`'s owner-bound credential, not by presence. See
[first-motion evidence](verification/phase-22b-first-motion-2026-09-23.md)
for where `/api/daemon/stop`/`start` were found (via the daemon's own
`/openapi.json`) and their UNVERIFIED-against-real-hardware status as of
this writing.

### Camera socket directory recovery

The boot-order/socket race was fixed and cold-reboot verified during 24d
([evidence](verification/phase-24d-conversation-2026-09-24.md#boot-race-fix-on-the-nano-2026-09-25)).
This is incident recovery if `/tmp/reachymini_camera_socket` is ever found
as a directory again, not an expected boot step:

1. Run `scripts/start-reachy.sh --check` and confirm the path is a directory,
   not the daemon's live socket. Check for a legacy container with a Docker
   restart policy or `-v` bind.
2. The owner removes the empty directory with
   `sudo rmdir /tmp/reachymini_camera_socket`. If it is not empty, inspect
   the contents before taking further action.
3. With the owner present and supervising wake-up motion, run
   `sudo systemctl restart reachy-mini-daemon`.
4. Wait for the daemon to recreate the socket (`srw… reachy`), then run
   `scripts/start-reachy.sh` to replace any legacy container. Confirm the
   embodiment unit is enabled, the container has no Docker restart policy,
   and the socket bind uses `--mount`.
5. Warm the camera with one authenticated `GET /camera/frame`.

### Production: unattended boot start (owner-accepted risk, 2026-09-23)

For a Nano the owner has explicitly designated production, `reachy-mini-
daemon` may be systemd-enabled to start automatically at boot, including
its own wake-up motion, without a human physically watching every boot —
the owner accepted this risk after Phase 22b's live testing. This is
per-host and explicit, not a default: `sudo systemctl enable
reachy-mini-daemon` (it is `WantedBy=multi-user.target` already, just
disabled by default). A dev/test host, or any host not explicitly
designated this way, keeps the owner-present rule above.

Enabling the daemon unit alone is not the whole unattended-boot story:
- `reachy-embodiment` starts at boot only through
  `reachy-embodiment.service`, never through a Docker restart policy.
  The earlier `--restart unless-stopped` container came up before the
  daemon after a reboot, and its `-v` bind created
  `/tmp/reachymini_camera_socket` as a root-owned directory, which blocked
  the daemon's media server (24d). The unit is `WantedBy`, `After` and
  `BindsTo` the daemon: it waits for the daemon's socket
  (`deploy/reachy/wait-media-socket.sh`), then runs the container that
  `start-reachy.sh` created, and restarts it whenever the daemon restarts,
  because the container's bind is fixed to the socket file that existed
  when it started. The launcher now creates the container with `--mount`,
  which refuses to start rather than create a missing path, and with no
  restart policy. It replaces a container created the old way. Install
  once, from the repository on the Nano:
  `sudo cp deploy/reachy/reachy-embodiment.service /etc/systemd/system/ &&
  sudo systemctl daemon-reload && sudo systemctl enable reachy-embodiment`,
  then run `scripts/start-reachy.sh` to recreate the container. Enabling
  the unit never starts the daemon. `start-reachy.sh --check` reports the
  socket, container and unit state without changing anything. Verified on
  the Nano on 2026-09-25 by a real cold reboot and a daemon restart
  ([record](verification/phase-24d-conversation-2026-09-24.md#boot-race-fix-on-the-nano-2026-09-25)).
- **Automatic restart after a daemon error (owner decision, 2026-09-25).**
  The daemon's start-up wake-up can fail (24d: `time value is out of range
  [0,1]` at boot). The process then stays up in `state: error`, holding the
  head wherever the failed goto stopped, so systemd's `Restart=` never sees
  it. On the designated production Nano only, `reachy-daemon-recovery.service`
  (`deploy/reachy/daemon-error-recovery.sh`, root) polls
  `/api/daemon/status` every 5 s. On `state: error` it restarts the daemon
  **once per boot** (marker in `/run`), which replays the wake-up motion
  unattended. If the daemon reports `error` again during the same boot, it
  logs at `crit` (`journalctl -t reachy-daemon-recovery`), leaves the daemon
  alone and exits failed, so the unit shows in `systemctl --failed`. It
  ignores an unreachable daemon and `stopped` (standby). It never reads
  `backend_status.ready`, which is always false in reachy_mini 1.8.4.
  Install:
  `sudo cp deploy/reachy/reachy-daemon-recovery.service /etc/systemd/system/
  && sudo systemctl daemon-reload && sudo systemctl enable --now
  reachy-daemon-recovery`. There is no Telegram alert yet: robots have no
  route to the hub's owner notifications.
- The ADR 0019 outbound WSS connection self-reconnects with backoff once
  embodiment is up — no manual step needed.
- The old HTTP command-routing registration (`POST /robots` with
  `ROBOT_HTTP_BASE_URL`, step 3 below) only runs inside `start-reachy.sh`
  itself, but this is **not** a gap in production: the hub's registry is
  Postgres-backed with an upsert
  (`reachy_hub.postgres_registry.PostgresRobotRegistry`, wired by default
  whenever `DATABASE_URL` is set, as it is in `deploy/homelab`), so a prior
  registration survives both a Nano reboot and a hub restart on its own.
  It only goes stale if the Nano's registered address (its stable
  Tailscale IP) or port actually changes, or the hub's Postgres volume is
  reset — neither is a boot-time concern.
- USB audio enumeration order isn't stable across boots/replugs, so a
  stale `~/.asoundrc` card index can silently break daemon audio (no
  animation sound effects, no mic capture) with no error visible anywhere
  — found live during
  [Phase 22b](phase-22-23.md#satisfactory-run-acceptance-matrix) and
  detailed in [that session's evidence](verification/phase-22b-first-motion-2026-09-23.md).
  `deploy/reachy/audio-setup.sh` re-detects the card (validated against
  `/proc/asound/cards`, not just a non-error return — the detection
  helper's own "not found" fallback is a numeric card index, not `None`)
  and regenerates `~/.asoundrc` and resets PCM volume; every step is
  best-effort/non-fatal, and it always exits 0 so it can never block a
  daemon start. Both `start-reachy.sh` (the manual-launcher path) and
  `reachy-mini-daemon.service`'s own `ExecStartPre=` (the systemd-boot
  path, needed once the owner accepted unattended boot start above) call
  this same script, so a card-index drift is caught however the daemon
  gets started, not just through the manual launcher. `install-reachy-
  venv.sh` sets `autospawn = no` in `~/.config/pulse/client.conf` for the
  `reachy` user at install time, so a desktop session's own PulseAudio
  doesn't auto-spawn and hold the robot's audio device.

1. Prepare `deploy/reachy/.env` from its example, permission-restricted to
   the owner. Match `ROBOT_ID`/`ROBOT_TOKEN` with an entry in homelab
   `ROBOT_TOKENS` (JSON mapping robot IDs to tokens).
2. Set `HUB_WS_URL` to the stable reachable hub URL, including `/hub` when
   using Caddy; use HTTPS/WSS for production. Set `ROBOT_HTTP_BASE_URL` to
   an address reachable **from hub** for the current HTTP command path.
3. Run `scripts/check-platform.sh` and `scripts/start-jetson.sh --check`
   on Nano (`scripts/start-reachy.sh --check` on another embodiment host).
4. With the owner supervising and daemon installation reviewed, use
   `scripts/start-jetson.sh --build --no-browser`. It delegates to the
   Reachy launcher, checks real/non-simulated daemon status, starts the
   embodiment container, and registers the current HTTP command address.

The robot container uses host networking because the daemon binds only
`127.0.0.1:8000`; bridge `host.docker.internal` cannot reach that socket.
Set `REACHY_DAEMON_URL=http://127.0.0.1:8000` without `/api`; the backend
appends that prefix. Embodiment listens on 8100 by default, not the daemon's
8000. Port precedence is `--port` > `REACHY_EMBODIMENT_PORT` > 8100.
Device access uses explicit devices and numeric groups independently of
host networking. Check existing personal `.env` files after updating defaults.

Phase 22b: camera capture (`ReachyDaemonBackend.capture_frame`) uses the
`reachy_mini` SDK's LOCAL media backend, which reads frames from the
daemon's `/tmp/reachymini_camera_socket` — bind-mounted into the container
by `start-reachy.sh` (`-v` alongside the device args above) only if that
socket already exists when the script runs, which requires the daemon to
already be up and healthy (its media server creates the socket on
successful start, not on install). Because `docker run`'s mounts are set
at container creation, changing this requires removing and recreating an
existing container (`docker rm -f reachy-embodiment` before the next
`--build` run), not just `docker start`. UNVERIFIED against real
hardware — confirmed only that the image's PyGObject/GStreamer/`unixfdsrc`
build succeeds (see the Dockerfile's comment), not an actual live capture
through this path.

Current WS connectivity provides authentication, registration, heartbeat,
generation fencing, and reconnect. Behaviour, camera and speak commands still
use HTTP. The only other traffic on the socket is conversation control from
[robot voice conversation](#robot-voice-conversation). Run one hub worker. Real
TLS, network-change, camera/audio, and physical soak acceptance remain in
[Phase 22b](phase-22-23.md#satisfactory-run-acceptance-matrix).

## Robot voice conversation

Phase 24c lets the owner talk to Reachy through its own microphone and
speaker. See [ADR 0023](adr/0023-robot-voice-conversation.md) for the design
and the [operator guide](operator-guide.md#talk-through-reachys-microphone-phase-24c)
for use. It is **off by default**. Its physical acceptance,
[Phase 24d](phase-24cd.md#phase-24d--physical-end-to-end-acceptance), closed
on 2026-09-25 on the conversation workflow; the remaining rows are deferred
to [Phase 24e](phase-24e.md). See the
[24d record](verification/phase-24d-conversation-2026-09-24.md).

To enable it on the robot host:

1. Set `VOICE_CONVERSATION_ENABLED=true` in `deploy/reachy/.env`. The robot
   then advertises the `voice_conversation` capability when it registers.
   The hub needs no new setting; it already needs `ROBOT_TOKENS`, owner
   login or `REMOTE_UI_TOKEN`, and working STT/TTS.
2. Remove the existing container (`docker rm -f reachy-embodiment`), then
   run `scripts/start-reachy.sh`. The launcher reuses an existing container
   with its original options, so a change to this setting has no effect until
   the container is recreated.
3. The launcher adds `--ipc host`, runs the container as the daemon's user
   (from the unit's `User=`, normally `reachy`), and mounts that user's
   `~/.asoundrc` read-only. The SDK's LOCAL audio backend then opens the same
   `reachymini_audio_src` `dsnoop` device the daemon uses. `dsnoop` shares the
   hardware through SysV shared memory owned by that user; without those
   options, the container would open the raw ALSA device and fight the daemon
   for it. If the file is not readable, the launcher warns and leaves voice
   disabled.

Open-palm stop ([ADR 0023 addendum](adr/0023-robot-voice-conversation.md#addendum-open-palm-stop-2026-09-25-phase-24e))
is a further opt-in on top of voice: set `PALM_STOP_ENABLED=true` too, then
recreate the container as in step 2. The launcher passes it through only
when voice is enabled. At the first conversation start, the container
checks that MediaPipe loads on this CPU, in a child process; the log shows
`palm stop ready` or `palm stop unavailable, continuing without it`. The
model is baked into the image. It has not been built or run on the Nano
yet ([Phase 24e item 5](phase-24e.md#5-open-palm-stop)).

Conversational motion ([Phase 24f](phase-24f.md), `CONVERSATION_MOTION_ENABLED`
and `SPEECH_WOBBLE_ENABLED`) is also passed through only when voice is on.
Both stay `false` on this host: they add motion that has not been accepted,
and turning either on is a supervised check with the owner present, not an
operating setting.

Checked on nano-1 during 24d:
- dsnoop capture from the container, alongside the daemon's own playback
  (dmix);
- camera socket access as the daemon UID;
- correct transcripts with the averaged channels;
- daemon `stop_sound` about 32 ms after `voice stop received`.

Acoustic echo is not yet assessed. The image needs
`gir1.2-gst-plugins-base-1.0` and `gstreamer1.0-alsa`, and must not ship
`libgstonnx.so`, which crashes GStreamer on the Nano's ARMv8.0 CPU. The
Dockerfile handles all three. Under the Nano's Docker 20.10.7 seccomp
profile, GStreamer loads plugins in process, so the first camera or
microphone use after a container start takes about 10 s.

The boot-order/socket race was fixed and cold-reboot verified during 24d.
If the socket path becomes a directory again, use
[camera socket directory recovery](#camera-socket-directory-recovery).

Robot traffic uses the same `HUB_WS_URL` origin through Caddy. The WSS socket
carries only `voice_start`/`voice_stop`/`voice_state`. Each utterance is a
separate authenticated `POST /hub/robot-media/voice-turn` from the robot; a
turn the hub held as unfinished is answered through
`POST /hub/robot-media/voice-turn/finalize`
([adaptive end of turn](adr/0023-robot-voice-conversation.md#addendum-adaptive-end-of-turn-2026-09-25-phase-24e)). The
hub never connects inbound to the robot for voice, and no new robot port is
opened.

| Limit | Value | Enforced by |
|---|---|---|
| Owner lease (UI renews every 1.5 s) | 15 s | Hub |
| Maximum session length | 10 min | Hub and robot |
| No transcribed speech | 120 s | Hub |
| Maximum turn, including held segments | 30 s | Robot cuts; hub rejects above 31 s |
| End-of-speech silence / minimum utterance | 700 ms / 300 ms | Robot VAD |
| Continuation window after an unfinished-sounding segment | 1.5 s from the cut | Hub decides to hold; robot waits, then asks it to answer |
| Upload size | 1 MiB, 16 kHz mono 16-bit WAV | Hub |
| Turns in flight | 1 per session | Hub (409) |
| Tail guard after playback | 400 ms | Robot |

Stopping, logging out, closing the tab (lease lapse), robot disconnect or hub
restart all end the session. The robot never restarts capture on its own. A
reply the hub doesn't permit on the speaker (Office/Remote/Silent, work-private
or sensitive content, DND, or a meeting privacy context) is not synthesized.
The owner's voice panel shows it with the reason. Replies routed to phone are
also sent to the bound Telegram chat if one is available.

Raw microphone audio exists only in memory: in the robot's capture buffer and
the hub request being transcribed. Neither writes it to disk or logs it. At
INFO level the hub logs turn numbers and outcomes only, never transcripts
(the images' default level emits neither). Transcripts and replies
enter core's conversation store like typed chat. The hub also keeps the last
20 turns of the current or most recent session in memory for the owner's
panel, and loses them on restart. Spoken reply audio is uploaded to the
daemon as `/tmp/reachy_mini_sounds/reachy_embodiment_audio.wav`. Each reply
overwrites it; reboot clears it.

With an LLM configured, core carries a private label forward through a
conversation only for private data that stays in its history. That covers
calendar, email, memory and account results, and the owner's own words that
match a sensitive keyword. After such a turn, every later generated reply is
withheld from the speaker until core restarts. A keyword that appears only in
the model's own wording, such as a general answer mentioning "medical",
withholds that reply alone (Phase 24d).

The hub speaks with Piper `en_US-lessac-medium`. The voice is baked into the
image and selected by `PIPER_VOICE_MODEL`; without it, the hub falls back to
espeak-ng.
The hub downloads the Whisper model on first use, which can take about a
minute, and the download is lost when the container is recreated.

For disposable checks, the simulated embodiment reads `SIM_MIC_WAVS`: a
path-separated list of 16 kHz mono WAV files. It plays one file per listening
phase, then silence. This fixture exercises the real upload, STT, core, TTS
and routing path; it is not microphone evidence.

## Network and access boundaries

[Caddyfile](../deploy/homelab/Caddyfile) strips `/hub/` for hub. Only
`/core/health` remains exposed; the core debug proxy is closed. Core data APIs
require `X-Reachy-Service-Token` with `ACCOUNTS_SERVICE_TOKEN`. Hub/core require
that separate credential at production startup, even when Google is not yet
connected: removing it cannot reopen routes containing previously read data.

Hub work-data and conversational HTTP routes require owner login with CSRF for
cookie mutations, or the existing owner `REMOTE_UI_TOKEN` bearer. Their user ID
must match `OWNER_USER_ID` (default `default-user`). The ordinary UI selects
that identity automatically. Accounts/OAuth endpoints specifically require the
owner session; robot control retains its separate bearer/cookie contract.
Robot registration and other legacy non-work-data surfaces still assume the
trusted LAN/VPN. This is not an Internet-facing identity service.

Telegram account reads require `TELEGRAM_OWNER_CHAT_ID` to name an explicitly
trusted **private** owner chat, and `TELEGRAM_DEFAULT_USER_ID` must match
`OWNER_USER_ID`. All other chats are ignored, before recording their chat ID
or calling core. An old learned chat ID does not authorize notification
delivery either. Leave the binding unset to deny Telegram work-data access.

Caddy forwards WebRTC signaling, not UDP/RTP media. Cross-machine clients
need reachable ICE candidates; Docker bridge addresses may be unusable from
another host. The recorded live Call Reachy check used an aiortc client,
not a physical cross-machine browser acceptance test. TURN/LAN deployment
and physical media validation are still outstanding.

## Upgrades and verification cleanup

Schema upgrades now use the dedicated migration job; follow
[the cutover and key procedure below](#schema-upgrades-and-credential-keys).
Never delete production volumes to resolve schema errors.

Use a separate Compose project and temporary credentials/volumes for live
checks. Keep the same project name, env file, and override files through
startup, restart, and cleanup. `down -v` is appropriate only for that
explicitly disposable project. Leave unrelated services such as OVMS alone.

## Schema upgrades and credential keys

Core and hub require revision `005_desktop_oauth`, which follows
`004_persona` (assistant persona configuration) and adds a `client_type`
column to `google_oauth_states` for the desktop OAuth helper. The ordered
Alembic history ships
in core's image; SQL stores perform compatibility checks, not startup DDL.
Compose runs `migrate` before hub/core, including through
`scripts/start-homelab.sh`. Launcher `--check` remains read-only and does not
run migrations. Do not use `--no-deps` to bypass the migration gate.

### Key provisioning

Before first startup or upgrading, generate a separate encryption key file.
From the repository root, the following creates a new ignored file with mode
0600 and refuses to overwrite one. It does not print key material:

```bash
python3 - <<'PYKEY'
import base64, json, os
path = "deploy/homelab/.env.secret-keys.json"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as stream:
    json.dump({"active": "key-1", "keys": {
        "key-1": base64.b64encode(os.urandom(32)).decode()
    }}, stream)
PYKEY
git check-ignore deploy/homelab/.env.secret-keys.json
```

Set `SECRET_KEY_FILE` in the private Compose env file to its **absolute host
path**. Compose mounts it at `/run/secrets/credential_keys` for core and
the migration job only. Native processes use `SECRET_KEY_FILE` directly.
The reader refuses group/world-accessible files. Do not reuse
`SESSION_SECRET_KEY`. Back up the key file separately under equivalent access
restrictions; a database dump alone cannot recover credentials.

### Existing database cutover

Use your existing named project, private env file and Compose overrides for
every command. Back up the database and record the previous application
revision before changing it. For example, from `deploy/homelab`, replace the
example project/env path with the actual deployment:

```bash
umask 077
docker compose -p reachy-homelab --env-file .env exec -T postgres \
  pg_dump -U reachy -d reachy_hub -Fc > /secure/backup/reachy-before-phase23.dump
docker compose -p reachy-homelab --env-file .env stop companion-core reachy-hub
docker compose -p reachy-homelab --env-file .env build migrate companion-core reachy-hub
docker compose -p reachy-homelab --env-file .env run --rm migrate \
  /app/.venv/bin/python -m companion_core.migrations upgrade --adopt-legacy
docker compose -p reachy-homelab --env-file .env up -d
```

Adjust `pg_dump`'s role/database for custom Postgres settings. Stop all other
clients of this database too, and prevent old instances restarting during
cutover. The upgrade refuses existing client connections before changing a
revision. A database constraint also blocks old code from reintroducing
plaintext `api_key` fields. Do not roll back only the application binary.

Legacy adoption validates columns, types, nullability, defaults, constraints
and indexes. It creates tables absent in older releases and repairs only these
known missing fields:

| Table | Supported missing fields |
|---|---|
| sessions | dnd (false), last_interruption_at (null) |
| audit_log | action (null) |
| memories | forgotten_at (null) |
| email_drafts | dispatch_at (null) |
| llm_usage_log | escalation_reason (null) |

Unknown drift is refused with table/column diagnostics, never silently stamped.
Resolve it through a reviewed migration or restore a supported backup into an
isolated project. Never reset the volume. Fresh databases need no adoption
flag: the normal Compose job performs both revisions. Native development uses:

```bash
uv run --package companion-core python -m companion_core.migrations upgrade
```

Supply `DATABASE_URL` and `SECRET_KEY_FILE` through the protected environment.
The job checks keys before connecting, takes an exclusive migration advisory
lock, and bounds connection/lock/statement waits at 10/10/120 seconds.
All current revisions are transactional: failure rolls back schema,
backfill and revision markers together. A repeat upgrade is safe and verifies
that all stored credentials decrypt with the supplied keyring.
No automatic downgrade is provided. Prefer a reviewed forward fix or restore
the pre-upgrade dump with its matching application revision into an isolated
project first; only replace a production deployment after testing that restore.

### Key rotation and recovery

Stop core while rotating so every writer switches to the same active key.
Keep existing key IDs/values, append a new random 32-byte base64 key under a new
ID, and set `active` to that ID in the protected JSON file. Never overwrite a
key value under an existing ID. Back up the expanded keyring securely. Run:

```bash
docker compose -p reachy-homelab --env-file .env run --rm migrate \
  /app/.venv/bin/python -m companion_core.migrations rotate
docker compose -p reachy-homelab --env-file .env up -d --force-recreate companion-core
```

Rotation commits batches of at most 100 and serializes against migration or
another rotation. Restart the command after interruption; committed batches
are skipped. Core loads the keyring at startup, so recreate it after editing
the file, particularly when the file was replaced atomically. Retain old keys
until no active records **and no retained backups** require them. Restore
testing must include the database, all referenced keys and a compatible app.
Missing/wrong keys and tampered ciphertext deny credential use rather than
falling back to plaintext.

Migration removes active plaintext LLM fields, not historical backups, WAL or
old row versions. Restrict/expire those artifacts and rotate upstream API keys
as appropriate. Source env files remain plaintext and require their existing
permissions and ignore rules.

### SMTP credential sources

`SMTP_SECRET_REF` optionally references a core SecretStore credential bound
to owner `owner`, provider `smtp`, purpose `password`. Provision references
through the internal SecretStore interface; there is no public credential
creation/decryption endpoint or SMTP settings UI. `SMTP_USERNAME` accompanies
the reference. Without a reference, `SMTP_PASSWORD` is an explicit
environment-only bootstrap source. A configured but unavailable reference
fails closed, even when a bootstrap password exists. Authenticated delivery
requires STARTTLS; implicit-TLS-only relays are not supported by this setting.
Mailpit/unauthenticated relay behavior remains available when auth is unset.
Google linking will not configure SMTP or enable sending.

## Google application setup

This is an installation task, separate from the user's **Connect → Google
sign-in → permissions** flow. Reachy never collects a Google password.
A deployer must register the Google application once; entering an email and
password into Reachy cannot replace Google's OAuth client registration.

1. Configure owner login, `SESSION_COOKIE_SECURE=true` for production HTTPS,
   the SecretStore key file and a distinct random `ACCOUNTS_SERVICE_TOKEN`
   shared by hub/core. Keep it in the protected ignored env file. For example,
   this fills the blank template entry without printing or replacing a value:

   ```bash
   python3 - <<'PYTOKEN'
   from pathlib import Path
   import secrets
   path = Path("deploy/homelab/.env")
   text = path.read_text()
   marker = "ACCOUNTS_SERVICE_TOKEN=\n"
   if text.count(marker) != 1:
       raise SystemExit("Expected one blank service-token entry; existing values were not changed")
   path.chmod(0o600)
   path.write_text(text.replace(marker, "ACCOUNTS_SERVICE_TOKEN=" + secrets.token_urlsafe(32) + "\n"))
   PYTOKEN
   ```

2. In a Google Cloud project enable Gmail API and Google Calendar API, and set
   the consent audience. For a single-owner, self-hosted install with no
   public domain or HTTPS endpoint (the common case for this project), create
   a **Desktop app** OAuth client — Google accepts any loopback
   (`http://127.0.0.1:<port>`) redirect for this client type without
   pre-registration, so no HTTPS callback or DNS is required. Download its
   JSON connection file and keep it permission-restricted outside source
   control. In the owner GUI open **Settings · Accounts → One-time Google
   connection setup**, select the file, and save. The secret is encrypted in
   core immediately, never in browser storage.

   If this Reachy already operates a stable, trusted HTTPS hostname (a
   hosted or organizational deployment), you may instead create a **Web
   application** client with an authorized redirect URI of
   `https://YOUR-HOST/hub/settings/accounts/google/callback` (direct hub
   mounting uses `/settings/accounts/google/callback`); see
   [the Web application path](#web-application-oauth-hosted-installs) below.
3. Choose the deployment audience deliberately. Gmail read-only is a restricted
   scope. Google documents exceptions including qualifying personal/internal
   use, but public distribution can require verification and security
   assessment. “In production” by itself is not proof of approval. External
   Testing grants for these scopes normally expire after seven days. Record
   the applicable audience/exception/verification outcome before rollout.
4. The owner selects Connect. For a Desktop client, this shows a one-line
   command; run it on the computer whose browser you use to reach Reachy —
   [`tools/google_auth_helper.py`](../tools/google_auth_helper.py), a
   stdlib-only Python 3 script with no install step beyond Python itself. It
   opens Google sign-in in your browser, receives the single redirect on a
   local loopback port, hands the result to Reachy, and exits; it never
   holds your Google client secret or long-lived tokens. For a Web
   application client, Connect redirects the browser directly, as before. No
   Google access is granted by importing the client file. Calendar and Gmail
   cards enable independently, with one Google identity shared by both.

### Web application OAuth (hosted installs)

Only needed if you chose a Web application client in step 2 above. Serve the
existing `/hub/` mount through a stable, trusted HTTPS endpoint on your
LAN/VPN. The shipped Caddy listener remains HTTP `:8080`; terminate HTTPS
with your installation's existing trusted proxy/tunnel and preserve the
`/hub/` path. Do not expose internal ports for OAuth. The callback is
`https://YOUR-HOST/hub/settings/accounts/google/callback`; direct hub
mounting uses `/settings/accounts/google/callback`. Only HTTP loopback
addresses are accepted for local development. The return address shown in
the connection setup form is derived from the GUI's actual mount.

See Google's [web-server authorization guide](https://developers.google.com/identity/protocols/oauth2/web-server),
[restricted-scope requirements and exceptions](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification),
[token expiration rules](https://developers.google.com/identity/protocols/oauth2),
[Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes) and
[Calendar scopes](https://developers.google.com/workspace/calendar/api/auth).

The application requests identity scopes plus `gmail.readonly` for Gmail,
or `calendar.events.readonly` and `calendar.calendarlist.readonly` for Calendar.
Free/busy is derived from readable non-transparent events; it is not a query
for another person's inaccessible calendar. New enabled capabilities request
the union of the owner's enabled read scopes. Unexpected partial consent does
not enable the requested feature. Changing client identity/return address
requires explicit disconnection of an existing grant.

### Account operations and recovery

Migration `003_accounts` adds core-owned `google_accounts`,
`google_oauth_states` and `google_reminder_delivery`. Migration
`005_desktop_oauth` adds a `client_type` column to `google_oauth_states`
(default `'web'`, backward compatible with existing rows) so a desktop
helper's handoff can never complete against a web flow's state or vice
versa. Upgrading follows the same stop-writers, backup, migration-job
procedure; `--adopt-legacy` is only needed for unversioned databases. Keep
one core and one hub worker: their existing conversations, robot sockets and
short-lived read caches are process-local. Refresh/credential updates
themselves serialize through the database owner row.

Reads are on demand: a 30-second bounded cache, at most five Calendar pages
per selected calendar, 31-day query windows and 20 selected calendars.
An incomplete Calendar range is reported as an error, not as complete
free/busy. Gmail reads at most three pages of 20 messages; refine search for
more. Transient 429/5xx responses get two bounded backoff retries. A stale
connection check is labelled after five minutes.

Google reminders use a durable claim keyed by provider event/start time,
preventing repeated emissions across restart and concurrent polls. This is
**at-most-once** emission to a hub request: a failed hub delivery after claiming
can lose that notification. It is not a guaranteed-delivery queue. Rescheduled
occurrences can produce new reminders. Local reminders retain their previous
semantics.

Disconnect commits local credential removal before attempting upstream
revocation. It clears provider caches, pending OAuth handoffs, core conversation
context and queued owner notifications; local drafts remain. Already delivered
copies remain on their channels. Revocation failure is reported explicitly.
Authorization state/codes/PKCE values expire after ten minutes and are
encrypted or hashed; expired handoffs are removed on the next account request.

The shipped Uvicorn commands disable access logs. Caddy's global log filter
removes code/state/error/search query parameters and request/response headers,
including from proxy error logs. Retain those controls in external proxies;
do not add full callback URLs, tokens or content to debug logs.

Restore the database and the matching SecretStore keyring into an isolated
deployment before recovery. Do not run production and restored copies against
the same live grant concurrently. Real Google refresh/revocation/reconnection
and production audience approval remain acceptance requirements even when
fixture tests pass; see [verification](verification/phase-23-accounts-2026-09-23.md).
