# AGENTS.md

Instructions for coding agents working in this repository.

**Before starting any work, read [HANDOVER.md](HANDOVER.md).** It's the
living snapshot of exactly where the project stands right now — what's
done, what's next, environment setup gotchas specific to this sandbox, and
known unfixed issues — written so a session with no memory of prior ones
can pick up correctly. Update it before you finish your session too (new
phases done, new gotchas found, what's next), so the next session isn't
starting blind either.

## What this is

Office work companion built on Reachy Mini: a homelab reasoning/session
control plane (`companion-core`, `reachy-hub`) plus a Reachy-side embodiment
service (`reachy-embodiment`), deliberately decoupled so the robot stays
animated and responsive even when the homelab is unreachable. Read
[docs/plan.md](docs/plan.md) for the full plan and [docs/adr/](docs/adr/) for
the binding architecture decisions before making structural changes —
service boundaries (who owns what) are decided there, not up for
case-by-case reinterpretation.

Development proceeds phase-by-phase per [docs/plan.md §6](docs/plan.md#6-implementation-roadmap).
Check the "Status" section of the root [README.md](README.md) for which
phase is current before starting work; don't jump ahead and build a later
phase's functionality "while you're in there."

## Repo layout

```
services/companion-core/     reasoning/tools/memory + LLM config/inference/usage — FastAPI, uv workspace member
services/reachy-hub/         sessions/channels/auth/operator UI + robot proxy — FastAPI, uv workspace member
services/reachy-embodiment/  semantic behaviour API + presence loop — FastAPI, uv workspace member
clients/web-pwa/             Call Reachy + telepresence WebRTC PWA
clients/operator-ui/         owner dashboard + web chat — static HTML/JS/CSS, served by reachy-hub
shared/models/               Pydantic data contracts shared across services (AgentSession, AgentResponse, MemoryRecord, EmbodimentCommand)
shared/protocols/            HTTP route constants shared across services (import these, don't hardcode path strings)
deploy/homelab/              Docker Compose: companion-core, reachy-hub, postgres, caddy
deploy/reachy/               Reachy-side deployment (unimplemented)
docs/adr/                    binding architecture decisions
docs/plan.md                 full technical plan and roadmap
docs/jarvis-baseline.md      reference notes from the upstream Jarvis project (vendor/jarvis, gitignored, not committed)
```

Each service under `services/` is its own `uv` workspace member with its
own `pyproject.toml` and `src/<package>/` layout, importing shared code from
the root `shared` package (`reachy-work-companion`). Services talk to each
other over HTTP only — never import one service's package from another's
runtime code. Test code importing a sibling service's package for
in-process `httpx.ASGITransport` chaining is the one sanctioned exception
(see Testing below); it works only because `uv sync --all-packages`
installs every workspace member into one shared dev venv, and it does not
reflect what ships in each service's Docker image.

## Dev setup

```
uv sync --all-packages
uv run --group dev pytest services shared
uv run --group dev ruff check services shared
```

Run the whole stack for real via [deploy/homelab](deploy/homelab/):

```
cd deploy/homelab
cp .env.example .env   # set a real POSTGRES_PASSWORD
docker compose up -d --build
```

`docker compose` (the v2 plugin) may not be preinstalled in a sandboxed dev
environment — `docker` alone is not enough. If missing:

```
mkdir -p ~/.docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
  -o ~/.docker/cli-plugins/docker-compose
chmod +x ~/.docker/cli-plugins/docker-compose
```

Every service `Dockerfile` starts with `# syntax=docker/dockerfile:1` and
uses `RUN --mount=type=cache,...` (see Docker conventions below) — both
need BuildKit, which needs the `docker buildx` CLI plugin. Without it,
`docker build`/`docker compose build` silently fall back to the legacy
builder, which doesn't understand `--mount` and fails outright. Same
symptom as `docker compose` itself: may not be preinstalled in a sandboxed
dev environment. If `docker buildx version` errors, install it the same
way as the compose plugin above:

```
mkdir -p ~/.docker/cli-plugins
BUILDX_TAG=$(curl -fsSL https://api.github.com/repos/docker/buildx/releases/latest | grep -o '"tag_name": "[^"]*"' | cut -d'"' -f4)
BUILDX_ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
curl -fsSL "https://github.com/docker/buildx/releases/download/${BUILDX_TAG}/buildx-${BUILDX_TAG}.linux-${BUILDX_ARCH}" \
  -o ~/.docker/cli-plugins/docker-buildx
chmod +x ~/.docker/cli-plugins/docker-buildx
```

Once installed, plain `docker build`/`docker compose build` pick it up
automatically — no `DOCKER_BUILDKIT=1` or other flag needed.

## Testing conventions

- Every service's tests live in `services/<name>/tests/`, and every test
  file is named `test_app.py` (or similarly generic) across services. This
  is intentional but means default pytest import mode collides across
  services. The fix already in place: `--import-mode=importlib` is set in
  root `pyproject.toml`'s `[tool.pytest.ini_options]`, **and** service
  `tests/` directories must **not** have an `__init__.py` — adding one back
  reintroduces the module-name collision (see git history around Phase 4
  for what that failure looks like: tests silently run under the wrong
  file's name).
- Prefer real in-process integration over mocks: chain a caller's `httpx`
  client through `httpx.ASGITransport(app=callee_app)` to exercise actual
  request/response validation across a service boundary, rather than
  stubbing the HTTP call. See `services/reachy-hub/tests/test_app.py` and
  `services/companion-core/tests/test_app.py` for the pattern (the latter
  chains three apps deep: companion-core -> reachy-hub -> reachy-embodiment).
- A service whose FastAPI app assigns `app.state.*` only inside `lifespan`
  cannot be driven by a bare `ASGITransport` (no startup event fires). If a
  test needs that state without paying for a full lifespan, prefer
  restructuring the app to set injected/test-friendly state outside
  `lifespan` (see `reachy_hub/app.py`'s `owns_registry` split) over adding
  lifespan-triggering ceremony to every test.
- Background threads/asyncio tasks (presence loop, heartbeat loop): unit
  test the underlying step function directly with controlled time inputs
  (deterministic, fast), and keep exactly one real-thread/real-task test
  with short intervals as an end-to-end sanity check. Don't make every test
  wait on real sleeps.
- After adding/moving test files, delete stray `__pycache__` dirs before
  re-running the suite if you see confusing collection errors —
  `find . -path ./.venv -prune -o -name __pycache__ -type d -print -exec rm -rf {} +`.

## Operator UI and inference conventions (Phase 19)

Binding details are in [ADR 0016](docs/adr/0016-operator-ui.md). Phase 19 is
complete, and [ADR 0017](docs/adr/0017-web-chat-channel.md) adds Phase 20
web chat. Hybrid inference routing remains separate Phase 21 work. Preserve these boundaries when extending the implementation:

- Hub owns login, browser assets, component monitoring, and authenticated
  proxies. Core owns provider settings, inference, and usage stores.
  Import LLM contracts from `shared/models/llm.py` and route constants from
  `shared/protocols/operator_api.py`; never import core runtime code into hub.
- Both `/ui/` on the direct hub and `/hub/ui/` through Caddy must work.
  Keep frontend API paths relative to the mount. Include static assets in
  the hub Docker image and check desktop/mobile layouts in a real browser.
- Browser access uses the owner session cookie; API bearer access must
  continue working. Extend `require_remote_auth` for new operator routes.
  Cookie mutations and login/logout require `X-Reachy-CSRF: 1`. Do not
  reintroduce credentials in localStorage or expose core's settings/usage
  through Caddy's `/core/` debug proxy.
- Bootstrap creates the owner only when the users table is empty. Changing
  `ADMIN_PASSWORD` later does not reset it. Keep `SESSION_SECRET_KEY` stable
  across restarts; set `SESSION_COOKIE_SECURE=true` for HTTPS deployments.
- Phase 19 supports only `local` with `routing.mode=local_only`;
  `cloud` is reserved and must remain null until Phase 21. The local slot
  may target any compatible endpoint; provider vendor does not define role.
- Partial settings updates preserve omitted fields. Explicit `api_key: null`
  removes a key; `local: null` disables inference. Responses mask credentials;
  validation errors and usage logs must not echo keys or raw provider errors.
  Keys are plaintext in Postgres, as explicitly documented in ADR 0016.
- Only the generic conversation branch calls the model. Keep deterministic
  intent/consent handlers authoritative, same-session turns serialized, and
  private-context labels preserved in generated follow-ups. Transcript
  context remains in memory, separate from durable work memory.
- Utilization is actual attempted calls, tokens, errors, and latency, not
  GPU load or inferred costs. Missing token counts remain null. Telegram's
  Phase 20 status measures poll freshness, not outbound delivery or LLM health.

When adding core stores, update every test factory: core's `make_chain`
and bare-app factory, plus hub's `test_app.py`, `test_telegram.py`,
`test_voice.py`, `test_webrtc_call_live.py`, and `test_operator.py` factories.
Explicitly inject `InMemoryLLMSettingsStore` and `InMemoryLLMUsageStore`;
production defaults connect to Postgres during lifespan. Owner-auth tests
should inject a seeded `InMemoryUserStore` with a test signing key; bearer
route tests should use a fixed test token. See `test_llm.py` and
`test_operator.py` for success, failure, masking, and authentication coverage.

## Web chat and channel-health conventions (Phase 20)

- Chat reuses `Channel.WEB` and `POST /messages`; do not add a second
  conversation pipeline. Always render the direct reply regardless of
  `delivery_channel`. DND affects proactive notifications, not direct replies.
- The browser defaults to `/status.default_user_id`, which comes from
  `TELEGRAM_DEFAULT_USER_ID`. Preserve the shared user/session across
  channels, and make explicit user switches clear the visible transcript.
- Chat requires owner login in the UI, but `/messages` retains its existing
  trusted-network access contract. Do not claim the page authenticates all
  API callers. Render text literally, never as HTML. Do not persist chat
  transcripts in localStorage or add history endpoints without a new scope.
- Preserve drafts on failed sends, prevent duplicate pending submissions,
  discard late results after logout/user changes, and never auto-retry an
  ambiguous message failure that might already have performed an action.
- `telegram_health.py` separates one polling step from the loop. Test
  freshness at controlled times, including the 60-second stale boundary,
  successful empty polls, failures, and recovery. Errors/status/logs must
  not include Telegram URLs, raw exception bodies, or bot tokens.
- Browser regression: `node --test clients/operator-ui/tests/chat.test.cjs`
  with Playwright available to Node (an external install or `NODE_PATH`).
  It uses a local HTTP fixture; complement it with a real Compose/OVMS run
  before claiming end-to-end model verification. No frontend build step is
  required. Report simulated Telegram-channel calls separately from real
  Telegram-account messages.

## uv dependency conventions

- Pinning a package to a non-default index via `[tool.uv.sources]` +
  `[[tool.uv.index]]` only takes effect for **direct** dependencies of a
  `pyproject.toml`. If the package (e.g. `torch`) is only pulled in
  transitively (e.g. via `silero-vad`), the source override is silently
  ignored and uv resolves it from the default index instead — no warning,
  no error, it just quietly pulls the wrong build. Confirmed by isolated
  reproduction while adding Phase 8's speech stack (see
  `services/reachy-embodiment/pyproject.toml`'s comment on `torch`/
  `torchaudio`): identical `[tool.uv.sources]` config resolved `torch` from
  PyPI (pulling ~4GB of unwanted CUDA/cuDNN packages) when only
  `silero-vad` was declared, and correctly from the CPU-only index once
  `torch`/`torchaudio` were *also* declared as explicit direct dependencies
  — even though nothing imports them directly. If you need a source
  override on some other project's transitive dependency, declare that
  dependency directly too, purely to anchor the override.
- Workspace-level `[tool.uv.sources]` / `[[tool.uv.index]]` entries must
  live in the **root** `pyproject.toml`, not a member's — the same keys
  declared in `services/*/pyproject.toml` are silently ignored for index
  routing (also confirmed by reproduction, same episode).
- After changing `[tool.uv.sources]`/`[[tool.uv.index]]`, `uv sync` alone
  may not pick it up if `uv.lock` already has a locked resolution for that
  package — you likely need `uv lock --upgrade-package <name>` or, if that
  still doesn't take (as happened here), delete `uv.lock` and run
  `uv lock` fresh. Always confirm by grepping the regenerated `uv.lock` for
  `source = {...}` on the package in question before trusting `uv sync`'s
  output — don't just trust that reconfiguring the TOML worked.
- Before adding a heavy dependency (torch, CUDA-adjacent packages, large
  models), check whether it's actually pulling GPU wheels: `python -c
  "import torch; print(torch.__version__)"` — a version suffixed `+cu128`
  (or similar) means CUDA wheels were pulled onto a machine (or Reachy
  Mini) that very likely has no GPU. Check `du -sh .venv` before and after
  too; several GB is a strong signal something pulled unwanted CUDA
  packages.

## Docker conventions

- Each service's `Dockerfile` builds with `uv sync --frozen --no-dev --package <name>`
  and its `CMD` invokes the venv's binary directly
  (`/app/.venv/bin/uvicorn ...`), **not** `uv run uvicorn ...`. `uv run` at
  container start re-checks/syncs the project — including dev dependencies —
  requiring network access on every boot for no reason. This was found by
  actually running a built image, not by reading the Dockerfile; verify
  Docker changes by building and running the container, not just by eyeballing
  the file.
- `reachy-embodiment` is included in `deploy/homelab/docker-compose.yml`
  purely so the full chain can be smoke-tested locally with one
  `docker compose up`. In a real deployment it runs on the Reachy Mini
  itself (`deploy/reachy/`), not in the homelab stack — don't let that
  convenience inclusion leak into ADR 0001's service-boundary reasoning.
- Cross-service background loops (e.g. reachy-hub's heartbeat sender vs.
  reachy-embodiment's watchdog timeout) have timing relationships that
  matter: a hub ping interval too close to the embodiment's disconnect
  timeout causes spurious `DISCONNECTED` flips under real container startup
  jitter, even though every unit test passes. When touching either
  interval, retest with a real `docker compose up`, not just pytest.
- The root `.dockerignore` is load-bearing, not cosmetic: every service
  `Dockerfile` builds with context `../..` (repo root — see
  `docker-compose.yml`), so with no `.dockerignore` at all, every build
  shipped the *entire* repo (including `.venv`, ~1.6GB) to the Docker
  daemon as build context before a single `COPY` ran. Found while
  optimizing build time — this dominated over apt/uv download time, not
  the other way around. When adding a new large/generated directory
  anywhere in the repo, add it here too, the same reflex as adding it to
  `.gitignore`.
- Every `Dockerfile` uses `RUN --mount=type=cache,target=/root/.cache/uv`
  around its `uv sync` step (and `/var/cache/apt` + `/var/lib/apt/lists`
  in reachy-hub's, around `apt-get`) so repeated builds reuse previously
  downloaded wheels/packages instead of re-fetching them from the network
  every time — this needs BuildKit (see Dev setup's `docker buildx` note
  above); without it these Dockerfiles fail outright, they don't silently
  degrade to slow-but-working.

### Isolated live verification and schema changes

Use a separate Compose project (`-p <test-project>`) and temporary
credentials for integration checks. Inspect existing containers first,
wait for `/hub/health` after startup, and remove only that test project's
containers and disposable volumes afterward. Never use `down -v` against
an existing user deployment as routine cleanup. Leave unrelated services
(such as the local `ovms` inference container) running.

Phase 19 adds new tables (`users`, `llm_config`, `llm_usage_log`), so an
up-to-date Phase 18 volume needs no reset. `CREATE TABLE IF NOT EXISTS`
does not add columns to older tables: older-version upgrades need explicit
schema changes that preserve existing data, not automatic volume deletion.

For OVMS, discover the model with `GET /v1/models`; do not guess its name.
A container's `localhost` is not the host. Use the documented host-gateway
override or a reachable LAN URL. Exercise a real completion and inspect
usage; an HTTP stub verifies only the protocol, not real model inference.

## Verifying claims

Tests passing is necessary but was repeatedly not sufficient during this
project's early phases — several real bugs (a body/path validation
mismatch, a Dockerfile that phones home on every boot, a heartbeat timing
race, a routing-policy gate that would have silently dropped a channel
integration's very first reply) only surfaced when actually running live
processes, real Docker builds, a real `docker compose up` against real
Postgres, or (Phase 7) a real external API with a real account on the other
end. Before reporting a phase or feature done, prefer demonstrating it
end-to-end (curl against a running server, an actual container build/run,
an actual compose stack, a real third-party API call) over trusting the
test suite alone — and when the two disagree, the live run is the one to
believe.

### Secrets needed for a live check

When a live verification needs a credential (an API token, etc.), don't ask
the user to paste it into chat — ask them to write it to a local file
first. This repo's convention: `deploy/homelab/.env.local` (or any
`.env.*` file — the whole pattern is gitignored, unlike the bare `.env`
entry alone, which does *not* cover `.env.local`; check `.gitignore`
actually matches before trusting it, the way this repo's own `.env.local`
entry had to be added when Phase 7 needed a Telegram bot token). Source it
into a single Bash call's environment rather than printing it:
`set -a && source deploy/homelab/.env.local && set +a`. Shell state doesn't
persist between Bash tool calls, so this needs redoing in whichever command
actually uses the token.

## Style

Follow the general engineering conventions already established: no
premature abstraction, no speculative endpoints for future phases (see
`reachy-embodiment`'s deliberately-unimplemented `/gaze` and `/pose`;
`/audio/play` was implemented in Phase 16). Comments explain *why* (a
constraint, a bug that was fixed, a non-obvious ordering requirement), not *what*. `ruff check` must pass
clean before considering a change finished.
