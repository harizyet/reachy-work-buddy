# Phase 23 Accounts verification — 2026-09-23

Implementation and isolated functional verification are complete. This record
is **not real Google-account or physical robot acceptance**. The authoritative
release gates remain in the [phase plan](../phase-22-23.md#phase-23-acceptance-and-production-release-gate).
See [ADR 0021](../adr/0021-google-accounts.md) for ownership and security decisions,
and [deployment](../deployment.md) for setup and recovery procedures.

## Automated checks

- Final fast suite with real Postgres migration tests enabled: **366 passed,
  2 skipped, 10 deselected**. Skips require espeak; slow tests were excluded.
  Two existing Starlette/httpx deprecation warnings remain.
- Ruff passed for `services` and `shared`.
- Both committed Chromium suites passed: chat and Accounts. Accounts covers
  direct/proxied mounts, mobile layout, literal provider content, callback
  completion, busy times, logout cleanup and absence of browser token storage.
- Provider tests use httpx MockTransport, not Google. They cover PKCE/offline
  scopes, state replay/expiry/wrong binding, cancelled/partial consent, missing
  refresh tokens, mismatched identities, serialized refresh, revoked grants,
  stale checks, timeout/429 handling, pagination, all-day/timezone events,
  duplicate occurrences and bounded large-mailbox results.
- The hub/core ASGI chain covers owner/CSRF and service authentication, private
  reads, owner user-ID enforcement, retained bearer support on work routes,
  Telegram private-chat binding, briefing/DND/reminders, literal malicious
  content, and clearing conversation/notifications on disconnect or replacement.
- Real Postgres checks cover revision `003_accounts`, encrypted pending OAuth
  handoff and grant persistence across repository restart, concurrent refresh
  from separate service instances, and `pg_dump`/`pg_restore` of encrypted
  account records. Restored grants work with the matching key; a wrong key
  fails closed. Active account JSON/state rows contain references/hashes,
  not plaintext credential fixtures. Foundation migration/rotation coverage
  is retained from the [foundation record](phase-23-foundation-2026-09-23.md).

## Built images and real processes

Used separate Compose projects `reachy-phase23-accounts` and
`reachy-phase23-verify`, with disposable volumes and permission-restricted
fixture credentials. Built core, hub and migration images use their isolated
service dependency installations. Production databases were not upgraded.

The account stack ran real Postgres, core, hub and Caddy processes, plus a
local HTTP Google fixture injected through a test-only core factory. Production
provider endpoints have no runtime override. Real HTTP checks exercised owner
login, persistent account identity after service recreation, Gmail/calendar
chat, private response routing, briefing and denial of the `/core/` data proxy.

Chromium exercised the mounted operator UI against those processes, importing
a fixture setup file, connecting both capabilities, choosing a calendar and
reading literal mail. The browser intercepted Google's authorization origin
with a fixture consent page: the subsequent cross-site redirect carried the
Lax binding cookie and **did not carry the Strict owner cookie**. Completion
then succeeded through the authenticated same-origin request. This verifies
browser cookie behavior, not real Google consent or permissions.

The provider fixture issued a short-lived access token to exercise refresh.
This is fixture evidence only. Caddy configuration validated on v2.11.4.
Stopping only the disposable hub produced an actual proxy error; stack logs
contained no callback-code/state, cookie, client-secret, access-token or
refresh-token fixture sentinels. Uvicorn access logs remain disabled.

A browser run started immediately after recreation hit readiness timing and
timed out at login. Waiting for hub/core health, then repeating the full browser
flow passed. One sandboxed test attempt hung on unavailable socket execution
and was interrupted; the complete suite passed with the required local socket
and Docker permissions. Neither failed attempt is counted as acceptance.

## Outstanding acceptance

No real Google OAuth project/client, deployed HTTPS callback or owner consent
was supplied. Real reads, refresh without re-consent, upstream revocation,
reconnection and applicable publishing/audience requirements remain open.
The normal user journey uses Google's sign-in/password and permission screens;
Reachy does not collect Google passwords. Application registration is separate
one-time installation work, documented in the deployment guide.

Phase 22b and the Google-enabled physical repeat/desk soak remain deferred.
No real daemon or physical motion was started in this session. Disposable
projects, volumes and temporary key/env files were removed after verification;
the unrelated existing OVMS container was left running.
