# Development and testing

For service ownership and API navigation, see the
[service reference](reference/services.md). For a running stack or real robot,
use [deployment](deployment.md). Agent workflow rules are in
[AGENTS.md](../AGENTS.md).

## Local setup

Use Python 3.13+ and `uv`. From the repository root:

```bash
uv sync --all-packages
uv run --group dev pytest services shared
uv run --group dev ruff check services shared
```

The uv workspace installs all three services plus the shared package into
one dev venv. Unit/in-process tests use injected stores and do not require
Postgres. Real speech/embedding tests may need model downloads and
`espeak-ng` on PATH. Docker images install their own runtime dependencies.

For local speech, install `espeak-ng` with the system package manager. In a
sandbox without root, if the required libraries/data are already present:

```bash
apt-get download espeak-ng
dpkg-deb -x espeak-ng*.deb /tmp/espeak-extract
PATH="/tmp/espeak-extract/usr/bin:$PATH" uv run --group dev pytest services shared
```

Temporary files and cached models may disappear between sessions. Check
actual availability rather than assuming a previous session's cache exists.
FastAPI TestClient, Docker, local HTTP, and Chromium may need approved socket
access in restricted sandboxes; socket restrictions have caused test hangs.

## Running services separately

Use a reachable Postgres with pgvector for core; hub also requires Postgres.
Set `DATABASE_URL` to that database in the hub/core shells. Provision the
[credential key and run migrations](deployment.md#schema-upgrades-and-credential-keys)
before launching either service; core also needs `SECRET_KEY_FILE`. Set the
same `ACCOUNTS_SERVICE_TOKEN` in core and hub. Production work-data routes
now require owner authentication; see the deployment guide. Unlike an earlier
README example, core is not stateless and needs this connection too.
Run these in separate terminals after workspace sync:

```bash
uv run uvicorn reachy_embodiment.app:app --app-dir services/reachy-embodiment/src --port 8001 --reload
```

```bash
COMPANION_CORE_URL=http://localhost:8003 \
  uv run uvicorn reachy_hub.main:app --app-dir services/reachy-hub/src --port 8002 --reload
```

```bash
REACHY_HUB_URL=http://localhost:8002 \
  uv run uvicorn companion_core.main:app --app-dir services/companion-core/src --port 8003 --reload
```

Embodiment defaults to simulation. Register it with hub if exercising robot
commands. Owner login and integrations need the same variables as deployment.
Use the simulation Compose profile for a ready-made database and service chain.

## Testing conventions

- Keep pytest's root `--import-mode=importlib` and **no `__init__.py` in
  service test directories**. Generic repeated names such as `test_app.py`
  otherwise collide. Remove stray test `__pycache__` directories if collection
  appears to attribute tests to the wrong file after moves.
- Prefer actual in-process FastAPI chains through `httpx.ASGITransport` over
  mocking service-boundary request validation. Sibling service imports are
  permitted in tests only, because the shared dev venv installs all members.
- ASGITransport does not run lifespan. Put injected/test-friendly state outside
  lifespan where feasible; production-owned connections can stay inside it.
- Test loop step functions using controlled time. Keep one short real-thread
  or task check for wiring instead of making every test wait on sleeps.
- New core stores need injection in every app factory: core `test_app.py` and
  `test_llm.py`, plus hub `test_app.py`, `test_telegram.py`, `test_voice.py`,
  `test_webrtc_call_live.py`, and `test_operator.py`. Use in-memory LLM stores,
  a seeded user store/test signing key for owner auth, and fixed test bearers.
- Verify isolated `--package <service>` installs too: workspace dependencies
  can mask a missing direct runtime dependency. This happened with
  `silero-vad`'s undeclared onnxruntime requirement; use its `onnx-cpu` extra.

Speech tests marked `slow` exercise real STT/TTS; run `pytest ... -m 'not slow'`
for a fast loop and `-m slow` for model/subprocess checks. A skipped real-speech
check is not evidence of successful speech verification. Core's embedding
checks also use real models separately from deterministic injected embeddings.

## Browser checks

With Playwright and Chromium available externally:

```bash
node --test clients/operator-ui/tests/chat.test.cjs
node --test clients/operator-ui/tests/voice.test.cjs
node --check clients/operator-ui/app.js
node --check clients/operator-ui/chat.js
```

Set `NODE_PATH` to the external installation's `node_modules` if necessary.
No frontend build dependency is required. The committed browser regression
uses a local HTTP fixture: direct/proxied mounts, literal text, duplicate
send prevention, failed drafts, user switches, expired login, late replies,
fresh tabs, frontier override/reset, and mobile layout. Complement it with
real Compose/model checks before claiming live inference worked.

## Dependency management

- Put workspace `[tool.uv.sources]` and `[[tool.uv.index]]` in the root
  `pyproject.toml`; member-level index routing is ignored.
- Index overrides only apply to direct dependencies. Declare torch and
  torchaudio explicitly when anchoring their CPU index even if another
  dependency is their only consumer.
- After changing an index, re-resolve the affected package with
  `uv lock --upgrade-package <name>` and inspect `uv.lock`'s actual source.
  Plain sync may retain the old resolution. Regenerating the entire lockfile
  is a last resort; review the resulting dependency changes.
- Before adding large ML dependencies, inspect resolved wheel variants and
  venv size. A torch version ending in `+cu...` means CUDA; multi-GB growth
  can reveal unwanted GPU dependencies on CPU-only hosts.

## Docker toolchain

Check `docker compose version` and `docker buildx version` independently.
Both plugins are needed; Docker alone is insufficient. If absent, install
matching binaries into `~/.docker/cli-plugins/` and make them executable:

```bash
mkdir -p ~/.docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
  -o ~/.docker/cli-plugins/docker-compose
chmod +x ~/.docker/cli-plugins/docker-compose
```

```bash
BUILDX_TAG=$(curl -fsSL https://api.github.com/repos/docker/buildx/releases/latest | sed -n 's/.*"tag_name": "\([^"]*\)".*/\1/p')
BUILDX_ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
curl -fsSL "https://github.com/docker/buildx/releases/download/${BUILDX_TAG}/buildx-${BUILDX_TAG}.linux-${BUILDX_ARCH}" \
  -o ~/.docker/cli-plugins/docker-buildx
chmod +x ~/.docker/cli-plugins/docker-buildx
```

Docker Engine 23+ defaults to BuildKit. On Nano's Engine 20.10.7, use
`DOCKER_BUILDKIT=1` for builds; `COMPOSE_DOCKER_CLI_BUILD=1` may also be
needed with older Compose tooling. An installed buildx plugin alone does
not change the old engine's default. Use `pipefail` when piping build output;
`docker build ... | tail` otherwise masks build failure with tail's exit code.
Confirm the built image exists, then run it.

Each image uses `uv sync --frozen --no-dev --package <name>` and directly
executes the venv binary at startup. Do not change CMD to `uv run`: that can
resync dev dependencies and require network on every boot. Cache mounts for
uv/apt require BuildKit. The root `.dockerignore` is essential because every
build uses repository-root context; add large/generated directories there as
well as to `.gitignore`. The homelab simulation profile is testing convenience,
not a change in physical service placement.

## Live verification discipline

Passing tests is necessary but does not prove deployment behavior. Exercise
real processes/images/Postgres or external APIs for the claim being made.
Retest real timing when changing hub heartbeat or embodiment disconnect
intervals; startup jitter previously exposed a race hidden by unit tests.
Distinguish simulated HTTP channel calls from real Telegram-account messages,
and local servers assigned a cloud role from hosted-provider verification.

Use the [isolated-stack cleanup rules](deployment.md#upgrades-and-verification-cleanup).
Credentials belong in permission-restricted gitignored local files. Never
print or paste tokens; check ignore rules before creating a secret file.
If loading verification credentials in Bash, source them only in the command
that needs them (shell state does not persist between tool calls):

```bash
set -a && source deploy/homelab/.env.local && set +a
```

On the Nano's old systemd, `list-unit-files` can return success with zero
matches; inspect rows. `timedatectl show` is unavailable; parse guarded
`status` output. Under `set -e`, a failed bare `VAR="$(command)"` assignment
can abort a diagnostic script before its fallback. Preserve the launchers'
read-only `--check` guard before any daemon start. Validate launcher changes
on the target platform, with supervised permission for motion; syntax checks
alone missed those historical failures.

## Migration and SecretStore tests

`test_database_migrations.py` is opt-in and creates/drops uniquely named
databases on the supplied **disposable** Postgres server. Never point it at
production. The image needs pgvector and the test role needs CREATE DATABASE.
Set `DATABASE_MIGRATION_TEST_URL` to that server's fixture database. To include
real pg_dump/pg_restore checks, set `DATABASE_MIGRATION_TEST_CONTAINER` to its
disposable container (the fixture role is `fixture`, as used by this test).
Without that second setting only the backup test skips.

```bash
uv run pytest services/companion-core/tests/test_database_migrations.py \
  services/companion-core/tests/test_secrets.py -q
```

The database tests cover fresh/repeat installs, supported legacy repairs,
unknown drift, writer exclusion, rollback/retry, plaintext rejection, masked
settings, serialized patches, owner login, context binding, tampering, wrong
keys, resumable rotation, backup recovery and SMTP resolution without sending.
The ordinary in-memory application tests require neither a key file nor a DB.


Account fixtures live in `services/companion-core/tests/test_google_accounts.py`.
They exercise actual hub/core ASGI validation and the real HTTP adapter against
an injected Google transport; they do not access a Google account. The optional
database suite additionally checks encrypted OAuth handoffs, grant persistence,
refresh serialization across separate service instances, and account backup
restore. Run both browser fixtures with:

```bash
node --test clients/operator-ui/tests/*.test.cjs
node --check clients/operator-ui/accounts.js
```

Keep production Google origins fixed. Test transports are constructor-injected;
do not add runtime endpoint overrides that could send credentials elsewhere.
