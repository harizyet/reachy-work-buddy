# ADR 0021: Owner-bound, read-only Google accounts

- Status: Accepted
- Date: 2026-09-23

Core owns Google configuration, OAuth exchange/refresh, provider reads and
encrypted credentials. Hub owns owner-session authentication and browser
callback transport. Shared contracts live under shared/models and protocols.
One Google subject is linked to the deployment's stable owner. Gmail and
Calendar enable independently; revocation disconnects both because Google
may share the grant. Local drafts are retained.

OAuth uses offline authorization code flow, PKCE S256, state with a ten-minute
expiry, and a random HttpOnly SameSite=Lax binding cookie scoped to the account
routes. The regular owner cookie remains Strict. Callback transport consumes
state once and stores the code encrypted, then redirects to a clean same-origin
page. Completion requires the original binding and authenticated owner session
with CSRF. Tokens are never returned to hub or the browser. State/code/PKCE
secrets are removed on completion or expiry. Client changes invalidate pending
flows and require explicit disconnection of existing grants.

All credential persistence uses ADR 0020's SecretStore. A locked owner row
serializes refresh, reads, disconnect and client changes across processes.
Provider reads are bounded, on demand, with a small expiring in-memory cache;
failed requests never serve cached content as fresh. Disconnect removes the
grant locally before bounded upstream revocation, reports revocation failure,
and clears cached provider content. Both cards require reconnect after grant
revocation. No provider content is written into local calendar/email tables.

ACCOUNTS_SERVICE_TOKEN is required for production hub/core startup, including
when Google is unconfigured. Core requires it on all data routes.
Hub requires owner cookies/CSRF or its existing owner bearer on work-data
and conversational HTTP routes and binds their user IDs to OWNER_USER_ID.
OAuth and Accounts browser routes require the owner session specifically. Telegram additionally requires an
explicit private TELEGRAM_OWNER_CHAT_ID; a learned chat ID is not authorization.
This intentionally strengthens the legacy trusted-network boundary for Phase 23 deployments. Removing the credential must fail startup, never
reopen routes containing previously retrieved private data. Caddy exposes only core health, not core debug APIs.
Account endpoints fail closed without the service credential. Robot bearer
access remains separate.

Core composes provider reads with local stores for calendar, reminders and
briefing. IDs retain Google provenance; provider records have no write path.
Mail text is returned literally by deterministic read intents. Provider content
is untrusted data, never tool authority. Work-private routing and text-only
consent remain unchanged. Configured cloud inference can receive preceding
Google replies as conversation context; the UI discloses that transfer.

Production completion requires real Google consent/refresh/revoke/reconnect,
publishing/audience review, encrypted restore and the deferred hardware repeat
in the phase plan. Isolated fixture results do not satisfy those gates.
