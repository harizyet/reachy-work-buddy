# Operator guide

Open `/hub/ui/` through Caddy (direct hub: `/ui/`) after following
[deployment setup](deployment.md#owner-login). The dashboard provides
Overview and Chat; the navigation links to telepresence. Both frontends
are plain HTML/JS/CSS served by hub, with no build step or external assets.

## Overview and session controls

Load the conversational user ID, normally `TELEGRAM_DEFAULT_USER_ID`
(default `default-user`), to change mode/DND and inspect activity or queued
notifications. Login username and conversation user ID are distinct. A
session must exist to edit it; sending the first chat message creates one.

Health and usage refresh every ten seconds without overwriting edited model
fields. Core/robot failures are shown separately; a failed component does
not hide healthy ones. Telegram status measures polling freshness, not
outbound delivery or inference health: successful polls clear errors, and
60 seconds without success is stale. Long message-processing batches can
also make polling stale. DND suppresses proactive interruptions, not direct
replies. The model indicator means configured, not proven reachable.

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
authentication to that endpoint. See [ADR 0017](adr/0017-web-chat-channel.md).

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
[ADR 0018](adr/0018-hybrid-llm-routing.md) for live-test limits.


## Calls and telepresence

“Call Reachy” is at `/hub/app/` (direct hub: `/app/`). Hold the push-to-talk
button, speak, then release. Hub runs STT → conversation → TTS and returns
reply audio over WebRTC, with listening/thinking/speaking robot behaviours.
This conversational path does not play the reply through the room speaker.
The PWA's service worker is a passthrough; calls need a live connection.

Telepresence at `/hub/app/telepresence.html` shares the owner cookie and
provides remote camera/behaviour/speak controls. Speak-through-robot bypasses
companion-core and is a separate remote-control operation. API clients can
still use bearer authentication; browser credentials are not kept in
localStorage. The conversational Call Reachy endpoint retains its existing
trusted-network access contract.

Cross-machine WebRTC needs reachable UDP/ICE media candidates: Caddy proxies
signaling only. See [deployment limitations](deployment.md#network-and-access-boundaries)
and [ADR 0012](adr/0012-call-reachy-webrtc.md) /
[ADR 0013](adr/0013-remote-telepresence.md) for the transport decisions.
