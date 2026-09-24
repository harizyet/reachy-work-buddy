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

## Addendum (Phase 23b, 2026-09-24): Desktop OAuth client transport

A second client type, `desktop`, is supported alongside the original `web`
client this ADR was written for. Ownership is unchanged: Core still owns
configuration, code exchange, refresh and encrypted credentials; Hub still
owns owner-session authentication and the authorization handoff. What changes
is transport, for installations without a stable public HTTPS hostname.

For a `web` client, Google's redirect lands on Hub's own HTTPS callback and
travels through the existing state/PKCE/binding-cookie machinery described
above. For a `desktop` client, Google's redirect instead lands on a loopback
listener (`http://127.0.0.1:<ephemeral-port>`) bound by a small, temporary
helper process (`tools/google_auth_helper.py`) running on the owner's own
machine — because Hub itself typically runs on a separate homelab host the
browser is not on, so it cannot be that loopback listener.

The helper is bootstrap transport only, never a credential owner: it never
receives the Google client secret or the PKCE verifier (both stay
server-side, resolved through the existing SecretStore `PENDING`/`CLIENT`
contexts), and it holds no state once it exits. Its only capabilities are
opening a browser, receiving one redirect, and making one authenticated POST
of `{state, binding, code, redirect_uri}` back to Hub's
`/settings/accounts/google/desktop/complete`. That route requires no owner
session cookie — the browser cannot forward one to a separate local process
— and instead relies on the same state+binding secret-possession model the
existing unauthenticated web `ACCOUNTS_CALLBACK` route already uses, except
the binding secret is returned directly in the JSON response body to the
owner-authenticated browser (from `/settings/accounts/google/desktop/start`)
rather than set as an HttpOnly cookie, since the browser must hand it to the
helper rather than present it itself. `google_oauth_states` rows carry a
`client_type` column so a desktop handoff can never complete against a web
flow's state or vice versa.

A `desktop`-configured account has no stored `redirect_uri` — the loopback
address varies by port each authorization attempt — so `_connect`/`_callback`
/`_complete` (the `web` path) and `_desktop_start`/`_desktop_complete` (the
`desktop` path) are mutually exclusive per account based on the configured
`client_type`, sharing only the token-exchange/scope-validation/grant-storage
logic (`_finish_grant`) once a code is in hand. Production completion
requirements from the body of this ADR are unchanged and apply to both
client types.
