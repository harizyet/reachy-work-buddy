# Operator UI

Plain HTML/JS/CSS, served by reachy-hub at `/ui/` or through Caddy at
`/hub/ui/`. Login, component status, LLM usage/settings, session mode/DND,
audit activity, queued notifications, and a web chat tab. No build step or external assets.

See [deployment setup](../../deploy/homelab/README.md#operator-dashboard-phase-19)
and [ADR 0016](../../docs/adr/0016-operator-ui.md) for configuration and API
semantics. The UI works at both direct and proxy paths. It refreshes health
and usage every 10 seconds without overwriting edited form values.

Phase 20 web chat and Phase 21 hybrid routing are implemented.

Workflow: log in with the bootstrapped owner, load the conversational user
ID (not necessarily the login username), then save mode/DND or model
settings. That user must already have a session from Telegram or another
channel. A blank key field preserves the stored key; “Remove saved key”
clears it; “Disable all models” restores core's unconfigured reply behavior.
Changes take effect on the next conversation turn without restarting.

The page shell is public, but dashboard data and controls require login.
No password/key is stored in localStorage. All cookie mutations include
the CSRF header. Telepresence shares the same cookie; the Chat tab uses the
existing conversation API. Telegram shows actual
poll freshness/errors; model utilization shows API calls/tokens/latency
rather than hardware load. On core outage, its status and usage become
unavailable while the remaining component probes stay visible.

Verified during Phase 19 in Chromium at desktop and 390px mobile widths,
including a real OVMS completion, settings persistence, logout, and a core
outage. Python API tests live in `services/reachy-hub/tests/test_operator.py`;
the browser regression below is separate from the Python API tests. There
is no frontend build dependency.


## Chat (Phase 20)

Open Chat after login. The user ID defaults to the hub's configured
`TELEGRAM_DEFAULT_USER_ID`; use the same ID to continue an existing
Telegram/Reachy conversation. An owner login name is not automatically a
conversation user ID. Select a different ID with “Use this user”; this
also updates Overview's session selector and clears the visible messages.
A first send creates a session if needed. Chat shows mode, DND, and active
channel, refreshed after replies and every 10 seconds.

Enter sends; Shift+Enter adds a newline. The Send button works on mobile.
A pending turn prevents another send or user switch. Replies are always
shown here, even if routing metadata names another channel. Failed sends
preserve the draft and warn that processing may already have happened;
there is no automatic retry. User/assistant text is rendered literally,
including any HTML-looking content.

The transcript is only the current tab's view: refresh, logout, user
switch, or “Clear view” removes displayed messages. This does not erase
work memory or reset the companion session. There is no chat-history API
or localStorage archive. Telegram failures do not disable chat. Poll health
is not a guarantee that outbound Telegram messages or inference work.

The UI checks owner login before sending, but `POST /messages` still has
its original trusted-network access contract. This page does not add API
authentication to that endpoint. See [ADR 0017](../../docs/adr/0017-web-chat-channel.md).

## Browser regression

With Playwright and its Chromium browser installed outside this frontend,
run from the repository root:

```bash
node --test clients/operator-ui/tests/chat.test.cjs
```

If Playwright is installed in another directory, set `NODE_PATH` to that
installation's `node_modules`. This test starts a local HTTP fixture and
checks direct/proxied mounts, literal rendering, pending sends, error drafts,
user switches, expired login, late replies after logout, and fresh-tab
behavior at mobile width. It needs local socket/browser permissions in
restricted sandboxes. It does not call a real model or Telegram service;
real Compose/OVMS verification is documented in ADR 0017.


## Hybrid inference (Phase 21)

Overview → Language model configures separate local/cloud endpoints and
selects Local only, Cloud only, or Local then cloud on failure. Both must
speak the compatible chat-completion HTTP protocol. First cloud setup
suggests fallback when local is configured; an explicit selection wins.
Both roles send the bounded conversation context to their configured
endpoint. Keys are masked after saving; blank key inputs retain them,
Remove saved key clears them. Blank URL and model remove a role; select a
policy that does not require that removed role. Disable all models clears
both providers.

Chat's “Use frontier model for this message” skips local for the next sent
generic turn, regardless of standing policy. It resets after submission,
logout, and user changes. It does not bypass task/consent handlers or retry
a previous message. No cloud configuration produces an unavailable reply.
The browser allows 135 seconds; ambiguous failures still never auto-retry.

Utilization shows calls/errors/tokens separately for each role and the
latest `manual request` or `local error` escalation in the last 24 hours.
A normal cloud-only policy call is not an escalation. Regression tests also
check the override flag and reset. See
[ADR 0018](../../docs/adr/0018-hybrid-llm-routing.md) for live-test limits.
