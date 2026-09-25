# Operator guide

Open `/hub/ui/` through Caddy (direct hub: `/ui/`) after following
[deployment setup](deployment.md#owner-login). The dashboard provides
Overview, Chat, and Settings · Accounts; the navigation links to telepresence. Both frontends
are plain HTML/JS/CSS served by hub, with no build step or external assets.

## Overview and session controls

Overview loads your session automatically so you can change mode/DND and
inspect activity or queued notifications. A session must exist to edit it;
sending the first chat message creates one. The installation binds your login
to its configured owner identity.

Health and usage refresh every ten seconds without overwriting edited model
fields. Core/robot failures are shown separately; a failed component does
not hide healthy ones. Telegram status measures polling freshness, not
outbound delivery or inference health: successful polls clear errors, and
60 seconds without success is stale. Long message-processing batches can
also make polling stale. DND suppresses proactive interruptions, not direct
replies. The model indicator means configured, not proven reachable.

## Chat (Phase 20)

Open Chat after login. Chat uses your owner session automatically, sharing
conversation context with your authorized Telegram/Reachy channels.
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

Work-data and conversation APIs require owner authentication. Accounts
settings specifically require the browser owner session. See
[ADR 0021](adr/0021-google-accounts.md).

## Talk through Reachy's microphone (Phase 24c)

The Chat view has a **Robot microphone** panel. It works only when the
robot's deployment has enabled it
([deployment](deployment.md#robot-voice-conversation)). Otherwise the robot is
listed as "voice not enabled" or "offline". Physical acceptance is in
progress ([Phase 24d](phase-24cd.md#phase-24d--physical-end-to-end-acceptance)).
Search and weather usage appear on the Web search and Search API usage
cards; set your location and time zone on the Assistant persona card.

- Choose the robot and select **Start listening**. When the status shows
  "Listening — speak now", say one thing and pause. Reachy then shows
  "Thinking…", replies aloud ("Speaking"), and listens again.
- Reachy does not listen while it thinks or speaks. Wait for "Listening"
  before your next turn; interrupting it is not supported.
- Your words and Reachy's reply appear in the chat transcript, marked as
  spoken. The conversation is the same one as typed chat and Telegram. You can
  switch to typing and back without losing context.
- If a reply shouldn't be said aloud, Reachy doesn't say it. The reply appears
  here instead, marked "not spoken" with the reason. Reasons include Office,
  Remote or Silent mode, private calendar/work content, Do not disturb, or a
  meeting. In Office or Remote mode, the reply is also sent to your bound
  Telegram chat if one is set up.
- After a private reply (for example, about your calendar), later replies in
  the same conversation also stay off the speaker, because a reply might
  repeat the earlier private details.
- Spoken requests can't confirm actions or run `/reachy` commands. Type those.
- **Stop** ends listening immediately, including a reply already playing.
  Logging out, closing the page, going 2 minutes without speaking, or reaching
  10 minutes also ends it. It never restarts by itself; select Start again.

Reachy does not recognise who is speaking. While listening is on, anyone near
the robot can talk to it and hear its public replies. Use it only in a private
room until owner recognition ([Phase 25](phase-25.md)) exists.

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
localStorage. Conversational calls require owner login (or the owner bearer for API
clients) and use the configured owner identity.

Cross-machine WebRTC needs reachable UDP/ICE media candidates: Caddy proxies
signaling only. See [deployment limitations](deployment.md#network-and-access-boundaries)
and [ADR 0012](adr/0012-call-reachy-webrtc.md) /
[ADR 0013](adr/0013-remote-telepresence.md) for the transport decisions.

## Connect Gmail and Google Calendar

Open **Settings · Accounts** in the operator dashboard.

1. Select **Connect** on Gmail or Google Calendar.
2. If this installation uses a Desktop OAuth client (the recommended setup
   for a self-hosted install with no public domain), Reachy shows a one-line
   command instead of redirecting your browser. Run it on the computer whose
   browser you use to reach Reachy — see
   [`tools/google_auth_helper.py`](../tools/google_auth_helper.py) and the
   [deployment guide](deployment.md#google-application-setup). It opens
   Google sign-in itself; the page keeps waiting and updates automatically
   once it finishes. For a Web application client, Connect redirects your
   browser directly instead — skip to step 3.
3. Sign in on **Google's website** with your Google username/password, or
   choose an account already signed in there. Reachy never asks for or stores
   that Google password.
4. Review Google's permission screen and approve the read-only permissions for
   the feature you selected. Cancelling is safe; Connect can be tried again.
5. After returning to Reachy, check the displayed Google email and connection
   result. For Calendar, select the calendars you want Reachy to read and save
   those choices. Use the same Google account for both cards.

You can **Test connection**, **Reconnect**, or **Disconnect** from either card.
Disconnect removes both capabilities because Google may share their grant.
If Google cannot be reached to revoke the grant, the page explains how to
remove access in your Google account too. Local drafts are kept. Pending owner
notifications and core conversation context are cleared; already delivered
messages and a browser's displayed conversation are not remotely erased.

Use **Show messages** to browse up to 60 Gmail messages, search to narrow
results, and select a message for a literal text preview. Attachments are not
downloaded and message text is capped at 20,000 characters. Calendar previews
cover the next seven days. You can also ask in Chat:

- `check gmail`
- `search gmail from:person@example.com`
- `read gmail google:MESSAGE_ID` using an ID from the list
- `what's next?`

Gmail and selected Google calendars also feed the existing private briefing and
reminder flows. Local calendar entries/drafts remain local. This connection
cannot send, delete or mark Gmail messages as read, or change Google events.
Provider text cannot authorize actions.

Cloud inference, if enabled in Language model settings, can receive earlier
account replies as conversation context. The Accounts page explains this;
work-private delivery prevents room playback but does not prevent transfer to
your configured cloud provider.

If the page says Google sign-in is not ready, the person setting up this Reachy
installation needs to finish the **one-time connection setup**. Ordinary users
do not need client IDs, secret values, code, or command-line tools to connect.
The optional setup panel accepts the connection file downloaded during
[installation setup](deployment.md#google-application-setup).
