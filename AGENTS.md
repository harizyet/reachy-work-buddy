# AGENTS.md

Instructions for coding agents working in this repository.

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
services/companion-core/     reasoning/tools/memory — FastAPI, uv workspace member
services/reachy-hub/         robot registry + proxy to reachy-embodiment — FastAPI, uv workspace member
services/reachy-embodiment/  semantic behaviour API + presence loop — FastAPI, uv workspace member
clients/web-pwa/             web/PWA client (unimplemented)
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
`reachy-embodiment`'s deliberately-unimplemented `/gaze`, `/pose`,
`/audio/play`), comments explain *why* (a constraint, a bug that was fixed,
a non-obvious ordering requirement), not *what*. `ruff check` must pass
clean before considering a change finished.
