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
setup step in `.env` is needed for ordinary use (only set it yourself if
you deliberately want a fixed value). In the operator UI's Settings →
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
Choosing **External SearXNG** instead (a separately-run instance) or a
hosted cloud provider (e.g. Brave) is a separate, explicit opt-in via the
same card's provider field, and does need its own Base URL/API key — a
credential entered there is stored via Companion Core's SecretStore
(`secret_ref`), never alongside the bundled container's own deployment
secret; see [ADR 0022](adr/0022-web-search-grounding.md) and
[docs/phase-24a.md](phase-24a.md).

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
makes the robot inert; homelab loss must still permit local fallback. See
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
- `reachy-embodiment`'s container already restarts automatically (`docker
  run --restart unless-stopped`, confirmed live) as long as Docker's own
  service starts at boot and the container was created at least once by
  `start-reachy.sh`/`start-jetson.sh`.
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
generation fencing, and reconnect only. Commands still use HTTP; outbound
media and WS command routing are unfinished. Run one hub worker. Real TLS,
network-change, camera/audio, and physical soak acceptance remain in
[Phase 22b](phase-22-23.md#satisfactory-run-acceptance-matrix).

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
