# Phase 24a search-assisted assistant verification — 2026-09-24

Implementation and functional verification are complete, including a real
self-hosted SearXNG instance (below) — this is not a full self-hosted
*deployment* acceptance (the running homelab stack itself was not upgraded
this session) and not a live hosted-provider (e.g. Brave) run. See
[docs/phase-24a.md](../phase-24a.md) and
[ADR 0022](../adr/0022-web-search-grounding.md).

## Real self-hosted SearXNG instance

`deploy/homelab/docker-compose.yml` now ships a `searxng` service
(`searxng/searxng:latest`, internal-only, never published to the host) with
`deploy/homelab/searxng/settings.yml` enabling its JSON API and disabling
its public-instance rate limiter. This was verified live, not just written:

- `docker compose --env-file <dummy> -f docker-compose.yml config` validated
  the checked-in compose file's syntax and variable wiring.
- A standalone container from the exact checked-in `settings.yml`, given a
  real secret via `SEARXNG_SECRET` (the env var name the application itself
  reads — `searx/settings_defaults.py`'s `environ_name`; an earlier draft
  had guessed `SEARXNG_SECRET_KEY` and failed until corrected against the
  image's own source), served a real `GET /search?q=test&format=json` with
  real internet results (Wikipedia, Ookla, etc.) via granian/uWSGI.
- `companion_core/websearch/searxng.py`'s `SearXNGSearchProvider`, run
  directly (not through a test double), queried that live instance for
  "Reachy Mini robot" and returned three real, correctly normalized
  `SearchResult`s with live titles/URLs/snippets/source domains from
  pollen-robotics.com, huggingface.co, and reachymini.net — proving the
  adapter's request/response handling against the real API, not just a
  fixture shaped to match it.
- The exact compose service definition was then brought up under a
  separate, disposable Compose project (`phase24a-searxng-verify`, its own
  network/volume, no host port published) and reached by DNS name
  (`phase24a-searxng-verify-searxng-1:8080`) from another throwaway
  container on the same network — the same reachability path
  companion-core uses in production (`http://searxng:8080`) — then torn
  down (`down -v`) afterward. The running homelab stack
  (`reachy-homelab-*`) was never stopped, restarted, or reconfigured.

## Automated checks

- `ruff check .` passed across the full repository after the change.
- `pytest services shared` (in-memory, no database): **428 passed, 23
  skipped** (pre-existing, espeak-dependent), no failures.
- `services/companion-core/tests/test_websearch.py` (new, 31 cases) covers,
  against a fixture SearXNG-shaped `httpx.MockTransport` provider and a
  deterministic stub chat-completion model:
  - `AUTO`'s heuristic matching/non-matching fixture turns, and `should_search`
    respecting `off`/`auto`/`always`.
  - Referential-inclusion (`build_query`) pulling in the prior user turn on
    a short/cue-bearing follow-up, and never pulling in an unrelated prior
    turn for a self-contained question; the fixed character cap.
  - `SearXNGSearchProvider` result normalization/count-limiting and
    transport/malformed-response error wrapping into `SearchProviderError`.
  - Untrusted-content isolation: `build_grounding_messages` keeps rules and
    retrieved data in separate messages; a fixture result whose
    title/snippet contains "ignore previous instructions" never appears in
    the rules message, and (through `/conversation`) never changes the stub
    model's fixed reply.
  - Citation instruction and failure-notice wording present in the
    constructed prompt, not asserted against real model output.
  - `SearchConfig`/`SearchConfigPatch` merge/masking, and that a non-Off
    policy is rejected without a base URL.
  - `GET`/`PUT /settings/websearch` round-trips and masks the key
    (`********`+last 4), and rejects a non-Off policy with no base URL
    (422, no field values echoed).
  - End-to-end `/conversation` wiring: `Auto` triggers exactly one search
    call and injects a grounded, citable prompt on a matching turn; `Off`
    never calls the provider regardless of content; `Always` calls it
    regardless of content; `force_frontier` turns receive the same
    treatment; deterministic intents (tested: a task-capture phrase) never
    trigger a search call even under `Always`; a forced provider failure on
    a search-warranted turn still returns 200 with the failure-notice
    system message present in the constructed LLM request.
- `services/reachy-hub/tests/test_operator.py` gained
  `test_websearch_settings_proxy_masks_key_and_redacts_validation_errors`:
  the hub proxy masks the key the same way the LLM settings proxy does and
  redacts a validation error's raw field value. Full hub suite: **125
  passed, 6 skipped**.
- Real, disposable Postgres (`pgvector/pgvector:pg16`, a standalone
  container named `phase24a-migration-test-pg` on a non-default port,
  removed afterward; the running homelab stack's own Postgres container
  was never touched): `test_database_migrations.py` +
  `test_secrets.py`, **18 passed**, including new
  `test_search_config_defaults_secret_round_trip_and_provider_switch` —
  confirms migration `006_search_config` creates a single default row
  (`policy='off'`, no base URL, no secret) on a fresh install, that
  `PostgresSearchSettingsStore.set`'s `api_key` round-trips through the
  same `secrets` table as LLM keys under a `websearch:{provider}` context,
  survives a reconnect, and is never present in `search_config`'s own
  columns as plaintext.
- `shared.database.SCHEMA_REVISION` bumped to `006_search_config`; existing
  legacy-adoption/drift/lock/rotation/backup-restore migration tests in
  `test_database_migrations.py` continued to pass unmodified with the new
  revision in the chain.

## Not verified this session

- A real SearXNG instance was verified (above); a hosted cloud provider
  (e.g. Brave) was not, and the running homelab stack itself was not
  upgraded to actually include the new `searxng` service or a non-Off
  `search_config` row — this remains a self-hosted-deployment/production
  acceptance item, not something this session closes.
- The operator UI's "Web search" card (`clients/operator-ui/`) was added
  following the existing LLM/persona card patterns exactly but was not
  exercised in a real browser this session — no Playwright/Chromium
  browser-suite case exists for it, matching the pre-existing gap for the
  LLM/persona cards (only `accounts.test.cjs`/`chat.test.cjs` exist today).
- The citation instruction's actual effect on a real model's output wording
  is untested by design (docs/phase-24a.md's exit criteria test it as
  instructed behavior against a fixture, not model wording); no live model
  was used.

## Addendum — zero-configuration cleanup via the supported launcher (2026-09-24)

A later same-day pass removed the two remaining manual-setup steps this
verification's "Not verified" section flagged, for the **supported
launcher path** (`scripts/start-homelab.sh`) — not for raw `docker
compose` invoked directly, which remains an advanced/manual path with its
own setup step, precisely to avoid overstating "zero-configuration" as
broader than it is:

- **`SEARXNG_SECRET_KEY` is no longer an operator setup step, via the
  launcher.** `scripts/start-homelab.sh` now generates and persists this
  container-only deployment secret itself (`deploy/homelab/
  .env.searxng-secret`, `0600`, gitignored) the first time the stack
  starts, exporting it so Compose's own `${SEARXNG_SECRET_KEY:?...}`
  interpolation resolves without the operator touching `.env`. `--check`
  never writes this file — it generates a throwaway in-memory value only
  to satisfy `docker compose config --quiet`'s validation, staying
  read-only. An operator who runs `docker compose` directly instead of
  through the launcher still must set `SEARXNG_SECRET_KEY` themselves
  (the compose file's `:?` still requires it, and its error message says
  so) — this is the documented boundary of "zero-configuration": it
  describes the launcher path, not raw Compose. Making raw Compose itself
  zero-config would need a different mechanism (a generated env file
  wired through `env_file:`, real Docker secret provisioning, or an init
  container/step) and wasn't judged worth the added complexity while the
  launcher is the canonical deployment path.
- **A new `BUILTIN_SEARXNG` provider kind needs no Base URL or API key at
  all.** `shared/models/websearch.py`'s `SearchConfig` now defaults to it,
  and its `validate_policy` model-validator no longer requires `base_url`
  for this provider; `companion_core/websearch/provider.py` hardcodes the
  bundled container's internal compose address (`http://searxng:8080`) for
  it. Choosing "External SearXNG" (the prior `SEARXNG` kind, unchanged
  behaviour) still requires and uses an operator-supplied Base URL/API key
  through the existing `SecretStore` path.
- **The operator UI's "Web search" card got its first browser test.**
  `clients/operator-ui/tests/websearch.test.cjs` (new, Chromium/Playwright,
  fixture HTTP server, no mocks of the UI's own code) confirms: the
  zero-config default renders with the Base URL/API key fields hidden;
  saving with the built-in provider selected sends `base_url: null`;
  selecting "External SearXNG" reveals those fields and a filled-in Base
  URL round-trips through the PUT.
- Automated checks after this addendum: `ruff check services shared`
  clean; `pytest services shared` **466 passed, 16 skipped**, including
  new/updated cases in `test_websearch.py` for the builtin-vs-external
  validation split and the hardcoded internal address; all 5 operator-UI
  Chromium/Playwright suites pass (`accounts`, `chat` ×2, `websearch`).
- Still not verified: an actual hosted cloud provider, the running homelab
  stack's own upgrade/acceptance, and a live browser run of `--check`'s
  generated-vs-persisted secret behavior on a real host — these were
  already open above and remain so.
