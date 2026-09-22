# ADR 0017: Web chat and Telegram polling health

- Status: Accepted
- Date: 2026-09-22

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

- 287 Python tests passed, including existing speech/WebRTC tests, real
  in-process cross-channel session/routing tests, and deterministic polling
  success/failure/recovery/staleness tests with controlled timestamps.
- A committed Chromium regression (`clients/operator-ui/tests/chat.test.cjs`)
  uses a local HTTP fixture to cover browser behavior: pending sends,
  literal HTML text, drafts after errors, user changes, login expiry,
  late replies after logout, empty transcript on refresh, responsive layout,
  and both direct and Caddy-style URL prefixes.
- A separate live run built the real Docker images and used isolated
  `phase20verify` Postgres/Caddy containers and the existing OVMS Qwen model.
  Chromium sent a web message, a subsequent `channel: telegram` HTTP call
  recorded a favorite color, and the next browser reply recalled “Teal.”
  Session/conversation IDs matched throughout. Office/DND state and a
  private calendar reply were visible in chat.
- An intentionally invalid test Telegram token produced a real Bot API
  HTTP 401 and `healthy: false` while web chat continued working. The
  cross-channel call used the hub API, not a real Telegram-account message;
  successful-poll recovery was verified deterministically, not claimed as
  a live Telegram-account recovery test.
- The disposable stack was removed afterward; the existing `ovms`
  container and user deployment settings were left unchanged.

## Consequences

No new database schema, dependency lockfile change, or core runtime change.
The view is a regular browser channel and an outage fallback, with explicit
limits on history and authentication. Hybrid local/cloud routing remains
Phase 21. See the [UI guide](../../clients/operator-ui/README.md) and
[deployment instructions](../../deploy/homelab/README.md#web-chat-phase-20).
