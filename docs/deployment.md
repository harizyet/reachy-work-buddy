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
# Edit .env: set a real POSTGRES_PASSWORD and the owner-login variables below.
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

Starting the daemon wakes/moves the robot by default. Only start it or run
motion tests while the owner is physically present and supervising.
`--check` must remain read-only and never start the daemon.

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

Current WS connectivity provides authentication, registration, heartbeat,
generation fencing, and reconnect only. Commands still use HTTP; outbound
media and WS command routing are unfinished. Run one hub worker. Real TLS,
network-change, camera/audio, and physical soak acceptance remain in
[Phase 22b](phase-22-23.md#satisfactory-run-acceptance-matrix).

## Network and access boundaries

[Caddyfile](../deploy/homelab/Caddyfile) strips `/hub/` and `/core/` before
proxying. Core settings/usage paths are explicitly blocked on the core debug
proxy; use authenticated hub operator endpoints. Other historical APIs,
including `/messages`, retain trusted homelab/VPN access rather than blanket
owner authentication. Do not expose this stack directly to the Internet.

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

Core and hub require revision `002_secrets`. The ordered Alembic history ships
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
Both current revisions are transactional: failure rolls back schema,
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
