# Phase 23b Desktop OAuth verification — 2026-09-24

Implementation and isolated functional verification are complete. This
record is **not real Google-account or physical acceptance**; it inherits
Phase 23's open real-account/production-audience gate rather than closing
it (see [Accounts verification](phase-23-accounts-2026-09-23.md) and
[ADR 0021's addendum](../adr/0021-google-accounts.md#addendum-phase-23b-2026-09-24-desktop-oauth-client-transport)).

## Automated checks

- `ruff check .` passed across the full repository after the change.
- `pytest services/companion-core services/reachy-hub shared` (in-memory,
  no database): **337 passed, 6 skipped** (pre-existing, espeak-dependent),
  no failures.
- `test_google_accounts.py` gained `test_desktop_oauth_connects_without_exposing_secrets_and_behaves_like_web_after`
  and a 10-case `test_desktop_oauth_failure_cases` (wrong state/binding,
  expiry, replay, cancel, unconfigured, connect-on-desktop-account,
  desktop-start-on-web-account, and both directions of desktop/web flow
  cross-matching) — all pass against the in-memory injected repository.
- Real, disposable Postgres (`pgvector/pgvector:pg16`, a standalone
  container distinct from the running homelab stack, removed afterward; no
  production or homelab volume touched): `test_database_migrations.py`,
  **15 passed**, including new `test_desktop_oauth_client_type_persists_and_isolates_flows`,
  which confirms the `client_type` column set by migration `005_desktop_oauth`
  persists through real Postgres and that a web-shaped `complete` call
  cannot match a desktop-typed flow row.
- Browser suite: Playwright/Chromium were not present in this environment;
  installed into a scratch directory (outside the repo, removed after the
  run) and executed via `NODE_PATH` per the documented external-installation
  pattern. `node --test clients/operator-ui/tests/*.test.cjs`: **3 passed**,
  including a new desktop-mode case confirming the Return-address field is
  hidden, the rendered helper command contains the client ID/state/binding/
  code-challenge but never `client_secret` or a PKCE verifier, and nothing
  is written to `localStorage`.

## Not verified this session

No real Google Cloud project, Desktop OAuth client JSON, or live consent run
was performed. `tools/google_auth_helper.py` was reviewed but not executed
against a real Google authorization endpoint or a real Reachy Hub process —
its loopback-listener/browser-open/handoff behavior is exercised only
indirectly, through the fixture-driven service/route tests above, not as a
live end-to-end run. The critical success case this ADR addendum specifies
(authorize once with the helper, remove it, restart Reachy, confirm Gmail/
Calendar still work and refresh without the helper) was not attempted; it
requires the same real-account acceptance Phase 23 itself still has open.
