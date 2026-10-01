# ADR 0017: Web chat and Telegram polling health

- Status: Accepted
- Date: 2026-09-22

## Saved web records amendment (2026-10-01)

The owner's UI reorganization request adds durable web chat records and a
history sidebar, superseding the tab-only transcript decision below. Hub owns
`web_chats` and `web_chat_turns`, migrated by the shared Alembic history
(`012_web_chats`). Owner-cookie/CSRF and bearer authentication protect archive
reads and writes; production user IDs remain bound to `OWNER_USER_ID`. Nothing
is persisted in localStorage or sessionStorage.

A record groups typed web turns for display. New records and record selection
do not replace the shared AgentSession, reset its context, or replay archived
text into core. This preserves ADR 0002's cross-channel session and ADR 0006's
privacy carry-forward. Core's reasoning context remains bounded and in memory.
Only web messages explicitly associated with a record are archived; legacy
clients, Telegram and live robot voice keep their existing behavior. Historical
messages from before this feature cannot be backfilled.

Persist each user turn before invoking core, then store its reply and search
evidence. Pending/uncertain turns are never automatically retried, including
after a restart. Archive reads are side-effect free. Logout clears the browser
view and rejects late results while retaining the authenticated server archive.
The UI's “Hide messages” action affects presentation only.

Settings are consolidated into feature tabs; Overview contains monitoring,
Chat contains conversation/history, and Meetings contains a record sidebar and
a main upload/detail area. See the [operator guide](../operator-guide.md).

## Phase 21 amendment

[ADR 0018](0018-hybrid-llm-routing.md) enables the cloud role and role-based
routing, adds the one-message frontier override and escalation accounting,
and supersedes the earlier timeout limits: provider 60 seconds total,
hub 130 seconds, browser chat 135 seconds. Phase-specific statements below
record the original implementation.

## Context

The operator needs a normal browser conversation channel that also works
when Telegram is unavailable. `Channel.WEB`, shared sessions, and the
hub's `POST /messages` already support this. The missing pieces were a
chat view and an honest Telegram-health indicator.

## Decision

### Existing conversational path

Add a Chat tab to `clients/operator-ui/`, alongside Overview, within the
existing owner-login shell. `chat.js` sends typed input to the existing
`POST /messages` with `channel: web` and `input_modality: text`. No new
conversation endpoint, core reasoning branch, or transport service is added.

The hub returns `MessageResponse.reply` directly to the caller. Render it
regardless of `delivery_channel`, following [ADR 0006](0006-response-routing.md):
that metadata does not suppress a direct reply to a direct message. Session
mode, privacy classification, consent checks, and audit recording continue
through the same backend path other channels use. DND controls proactive
interruptions, not replies to the operator's own messages.

The authenticated `/status` response adds `default_user_id`, using hub's
existing `TELEGRAM_DEFAULT_USER_ID` setting (default `default-user`). This
avoids silently creating a different session when a configured Telegram
user moves to the browser. The operator can explicitly select another user
ID; this is a single-owner companion, not a multi-tenant identity system.
Chat and Overview share the selected ID. The first message can create a
new session; a prior Telegram message is not required.

`GET /sessions/{user_id}` supplies the mode, DND, and active-channel
indicator. Refresh it after a reply, when opening Chat, and with the normal
10-second dashboard refresh. Changing channels preserves the session and
conversation IDs per [ADR 0002](0002-agent-session.md). Viewing a session
alone does not change its active channel; sending does.

### Transcript and failure behavior

Visible messages exist only in the current tab's DOM. Refresh, logout, or
switching the selected user clears that view. “Clear view” removes displayed
messages without resetting the companion session or forgetting work memory.
There is no history endpoint, localStorage transcript, durable server-side
chat archive, cross-tab transcript sync, or replay of other channels' text.
Core's existing in-memory conversation context still supplies model history;
it is separate from the browser view and disappears on core restart.

Render user and assistant text with `textContent`, preserving newlines and
never interpreting HTML. A pending send disables additional sends and user
switching; the user may prepare the next draft. Enter sends, Shift+Enter
inserts a newline. Failed replies stay visibly marked; preserve the draft
and explain that an ambiguous failure may already have been processed.
Do not retry automatically: resending a task capture or confirmation can
repeat an action. The browser's wait is bounded at 75 seconds, above the
hub's 70-second core request timeout.

Logout/session expiry clears the visible conversation and aborts pending
browser fetches. Late results are discarded using a view-generation check.
Aborting a fetch cannot undo work already accepted by the server.

### Authentication scope

Chat is shown only after owner login and checks `/auth/me` immediately
before sending. This is a browser access/UX check, **not** an authentication
retrofit of `/messages`. That existing API remains open within the trusted
homelab/VPN boundary, just as it was before Phase 20. It remains possible
for another HTTP client to invoke it without a cookie. Static HTML/JS assets
also remain public. Do not describe this as end-to-end authenticated chat.
The protected operator APIs keep [ADR 0016](0016-operator-ui.md)'s cookie,
bearer, CSRF, and Caddy rules.

### Telegram health

`telegram_health.py` owns a process-local `TelegramPollHealth` and the
single polling step `poll_updates`. Hub's existing loop calls that step
with the same 25-second long poll and existing two-second failure backoff.
Each successful `getUpdates`, including an empty batch, records a UTC time
and clears the last error. HTTP/network failures and malformed success
bodies record a sanitized error and are retried. Never put exception
strings, response bodies, or Telegram request URLs into status or warning
logs; Telegram URLs include the bot token.

`/status` now includes:

```json
{
  "default_user_id": "default-user",
  "telegram": {
    "configured": true,
    "last_poll_at": null,
    "last_poll_error": null,
    "healthy": false
  }
}
```

`healthy` requires configuration, a successful poll less than 60 seconds
old, and no error since that poll. Disabled, starting, failed, and stale
polling are unhealthy; the UI distinguishes those states rather than
calling a configured token healthy. Recovery clears the error on the next
success. State resets on hub restart; the first idle long poll can take
25 seconds before becoming healthy.

This is **poll freshness**, not a guarantee of Telegram message delivery or
model availability. A stopped/stalled loop or long batch-processing delay
becomes stale even without a new exception. Outbound send failures are not
part of `last_poll_error`. No heartbeat worker, database table, or
third-party monitoring service is introduced. Web chat does not depend on
Telegram health; an outage produces an informational fallback message.

## Verification

See the [Phase 20 record](../verification/history.md) for Python, Chromium,
Docker/Postgres/OVMS, and Telegram failure evidence. Simulated channel calls
are distinguished there from real Telegram-account messages.

## Consequences

No new database schema, dependency lockfile change, or core runtime change.
The view is a regular browser channel and an outage fallback, with explicit
limits on history and authentication. Hybrid local/cloud routing remains
Phase 21. See the [UI guide](../operator-guide.md) and
[deployment instructions](../operator-guide.md#chat-phase-20).
