# Operator guide

Open `/hub/ui/` through Caddy (direct hub: `/ui/`) after following
[deployment setup](deployment.md#owner-login). The dashboard provides
Overview, Chat, Meetings, To-do, Reminders, Notes, Coding agents, and Settings; the navigation links to telepresence. Both frontends
are plain HTML/JS/CSS served by hub, with no build step or external assets.

## Overview and session controls

Overview shows component health, search usage and its debug log, recent activity,
queued notifications, and model utilization. It loads your session automatically
for activity reads. Configuration lives in Settings. The installation binds
your login to its configured owner identity.

Health and usage refresh every ten seconds without overwriting edited model
fields. Core/robot failures are shown separately; a failed component does
not hide healthy ones. Telegram status measures polling freshness, not
outbound delivery or inference health: successful polls clear errors, and
60 seconds without success is stale. Long message-processing batches can
also make polling stale. DND suppresses proactive interruptions, not direct
replies. The model indicator means configured, not proven reachable.

## Settings

All persistent configuration and robot listening controls are grouped by feature:

- **Assistant:** session mode/DND, assistant persona (including a reply **Tone** preset: cheery, serious, formal, casual, playful or calm; style only, it never changes what the assistant may do), location and time zone.
- **Models:** local/cloud endpoints, credentials and routing.
- **Web search:** policy, providers, quotas and fallback.
- **Voice & motion:** robot microphone, “Hey Reachy” and conversational animations.
- **Accounts:** Google connections and coding agent credentials.
- **Owner recognition:** benchmark collection and sample management.

Use the tab buttons, or arrow keys/Home/End while a tab has focus. Switching
between Assistant, Models and Web search preserves unsaved form edits. A session must exist to edit mode/DND;
sending the first chat message creates one. The cloud override in Chat remains
a per-message choice rather than a persistent setting.

## Coding agents

Open **Coding agents** to set up and watch coding sessions Reachy manages. It
shows your Claude 5-hour and weekly allowance (live once an account usage
credential is saved in Settings · Accounts), lists projects, and lets you add a
project (a repository path on the robot host plus a provider) and start a
session on it with a task description. Starting a session asks for
confirmation because it spends Claude usage; sessions started with a
subscription login are read-only, while an API key can change files. Each
session shows its status and last event, with Events and Usage details, and
Refresh status and Stop while it is active. The list refreshes every 15 seconds
while the tab is open. **Terminal sessions** lists Claude Code sessions you ran yourself (title, folder,
branch, last prompt, and an Active marker when touched in the last two
minutes). This is read-only monitoring; Reachy cannot control them. It needs
`CLAUDE_PROJECTS_DIR` in `deploy/homelab/.env` pointing at the host's
`~/.claude/projects`, which is mounted read-only into coding-agent-service.

## To-do, reminders and notes

The **To-do**, **Reminders** and **Notes** tabs keep three lists on your homelab. *To-do*: add, tick off,
reopen, edit and delete items (the same tasks the assistant manages by chat).
*Reminders*: text plus a date and time in your browser's time zone; when one
comes due the hub sends `Reminder: <text>` to your Telegram once, and the tab
shows it as due until you mark it **Done**. A reminder is pushed only when
Telegram is configured and the owner chat is known; there is no retry if the
push fails. *Notes*: a title and free text, searchable by title and body.
Telling the assistant (Telegram, web chat or voice) "remind me to X at 4pm"
adds the to-do as before **and** a reminder when it ends in an unambiguous time
(`at 4pm`, `at 16:00`, `tomorrow at 10:30am`, `in 20 minutes`, or `tomorrow`,
which means 9:00); the time zone is the persona's. Anything else, including a
bare `at 4`, stays a to-do only. This is deterministic phrase matching
(`reminder_time.py`), to be replaced by real language understanding.
All text is shown literally. Requests go through owner-authenticated
`/planner/*` hub routes to companion-core's `/tasks`, `/notes` and `/reminders`.

## Alarms

The **Alarms** tab lists every alarm with its status and how it was delivered.
Add one with a label and a date and time in your browser's time zone, optionally
choosing a saved radio station. Search TuneIn by name, save a station (only its
guide id is stored) and remove it again. **Cancel** drops a scheduled alarm;
**Stop** silences an alarm that is playing now. The **Volume** slider (10-400%, default 100%) sets the loudness of each new alarm; above 100% boosts the audio and can distort. Playback follows privacy mode and
room presence (ADR 0027); otherwise the alarm goes to Telegram. Requests use
owner-authenticated `/planner/alarms*` and `/planner/stations*` hub routes.

The **Activity** tab lists recent action receipts: what the assistant actually
changed (alarms, tasks, reminders, memory) and whether an alarm was delivered,
independent of how a reply was worded. It is read-only.

## Meeting recordings

Open **Meetings** to record or upload audio with **Add meeting**. The left
sidebar lists saved meetings with title search, status and refresh. **View details**
opens a record beside that list, showing the transcript and separate speaker
timings. On narrow screens the list sits above the detail. Selecting a record
stops any active browser recording and keeps the clip available under Add meeting. **Ready** means
transcription, speaker detection and their alignment finished. The transcript
shows a speaker chip where the speaker changes; click it to give that speaker a
name, which is applied to the whole meeting (the raw speaker timings stay listed
separately).

**Recording gaps.** When the phone stops capturing sound mid-recording (for
example when it locks or another app takes the microphone), Android supplies
exact silence while the clock keeps running, and the transcript can then bridge
the gap with a line that covers seconds holding no audio. After a meeting
completes, the server checks the recording for runs of exact silence of five
seconds or more. A meeting with any shows a yellow ⚠ in the list, a banner in
its detail saying how much of the recording has no audio, and a ⚠ on each
transcript line that lies mostly inside a gap. Ordinary pauses and quiet rooms
are not flagged. The check runs once per meeting (earlier meetings are checked
after the upgrade) and never changes the transcript or the meeting's status.

**Playing the recording.** The meeting detail has an audio player (the app has a
play bar above the transcript). Selecting a transcript line plays from that line's
start, and the line being spoken is highlighted, so you can check what was really
said. **Edit** on a line (in the app, also selectable) replaces its text by hand;
**Restore original** brings back the transcript's wording. Manual edits are stored
the same way as accepted suggestions and feed summaries, minutes and meeting
context. The recording stays until the meeting is deleted. Summaries, minutes and use as context are described below.
**Cancel processing** stops a pending job; it does not
delete the recording. Failed jobs keep their diagnostic message under
**Technical error** in the detail view. An old failed job remains failed
even after its underlying service problem has been fixed.

### Deleting meetings, summaries, minutes and meeting context

Each meeting has a delete button (a confirmation first) and, when several have
failed or been cancelled, **Delete failed and cancelled**. A meeting still being
processed shows **Cancel** instead; cancel it, then delete it. Deleting removes
the recording, transcript, names, corrections, summary and minutes.

Open a processed meeting and choose **Summary**, **Minutes**, **Transcript** or
**Use as context**. Summary and minutes are written by the local model and show
which model wrote them; **Rerun with another model** offers Local, Deep local
(warns that Reachy is unavailable) and Cloud, for when the first result is not
accurate enough. **Use as context** opens the chat with the meeting attached:
ask "what is ClickHouse?" or "is ClickHouse free?" and the answer draws on the
meeting. Questions about the outside world are also checked against the web
(your question only is sent, never the transcript) and the answer shows its
sources as clickable links; questions about what was said stay on the meeting.
Answers use the local model; tick **Use frontier model** (web) or **Ask the
cloud model** (Android) to send the meeting text to your cloud provider for a
stronger answer.

### Suggested corrections and Deep local review

In an open meeting, **Suggest corrections** (web) or **Suggest** (Android) asks
for likely transcript mistakes and lets you apply them with **Change all**.
Matching uses your key terms and glossary. Choose the model each time:

- **Local**: your homelab model, private and quick.
- **Deep local**: a larger model on your homelab, still private and more
  accurate. **Reachy is unavailable while it runs** (about 6 minutes: the larger
  model loads, reviews, then Reachy's standard model reloads). You are warned
  first. A banner shows on every screen while Reachy is unavailable; you get
  **"Reachy is available again"** as an app notification, and Telegram messages
  when the standard model is unloaded and again when Reachy is back online. It is
  disabled with a reason when the model manager is not running, not on the
  standard model, or a review is already in progress.
- **Cloud**: sends the transcript text to your cloud provider.

## Conversational animations

Open **Settings → Voice & motion**, select the robot,
and use the two independent toggles:

- **Listening and thinking gestures** holds a short, silent pose while
  Reachy listens (a head tilt with both antennas raised) and while it
  thinks (a glance up to one side). The head returns home when it speaks
  and when the conversation ends; a Stop leaves it where it is.
- **Head movement while speaking** enables speech-reactive head motion.

Stop listening before changing settings, then use **Apply animation
settings**. Applying sends no motion command; the next conversation uses
the new values. **Refresh animation settings** reads the robot's current
values. Offline or older robots show an error with the controls disabled.
These are runtime settings: restarting embodiment restores its startup
defaults (both off unless configured otherwise). They do not control idle
presence or manually requested behaviours. While a conversation owns
motion, a manually requested behaviour is refused (409). Both features
passed physical acceptance on 2026-09-27; a 30-minute run with motion on is
still owed ([record](verification/phase-24f-physical-2026-09-27.md)).
Motion rules for development sessions are in the
[deployment rules](deployment.md#robot-host-and-jetson-nano).

## Owner recognition benchmark dataset

Settings → Owner recognition captures raw voice clips and face
photos for benchmark/calibration work. This is not operational enrollment:
samples do not identify the owner or authorize requests. The backend has
been deployed and checked; the browser capture/export flow still needs
[acceptance](project-state.md#implemented-but-not-fully-accepted).

Log in as the owner and confirm your password for changes (reauthentication
lasts five minutes). Explicitly enable **Benchmark dataset** before recording
voice or capturing a face photo; allow the browser's microphone/camera prompt.
The card lists samples, counts and total sizes, with delete and zip-export
controls. Export also requires fresh password confirmation. Disabling
benchmark mode stops new capture but retains existing samples; delete them
explicitly when no longer needed.

For persistence and encryption configuration, see
[benchmark storage](deployment.md#owner-recognition-benchmark-storage).
Future enrollment/calibration requirements are in
[Phase 25](phase-25.md#web-portal-calibration-and-accuracy-testing).

## Telegram query commands

Use the bot's command menu or type `/help` for quick answers from the existing
data handlers, without a conversational LLM query. These typed commands also
work in web chat; `/reachy <action>` is the canonical form (for example,
`/reachy coding_usage`). Telegram's `/command@bot_username` form is accepted.

| Command | Answer |
|---|---|
| `/coding_sessions` | Last recorded status of Reachy-managed coding sessions |
| `/coding_usage` | Recorded coding usage, including finished sessions |
| `/coding_reply <answer>` | Answer the one coding session waiting on you; your text is relayed verbatim and resumes the same Claude session |
| `/today` | Today's calendar (the calendar handler currently uses UTC day boundaries) |
| `/next_event` | Next calendar event |
| `/tasks` | Open tasks |
| `/find_tasks <words>` | Tasks matching the supplied words |
| `/inbox` | Received email list |
| `/recall <topic>` | Saved memories matching the topic |
| `/alarm <when>` | Set an alarm, e.g. `/alarm 7am` or `/alarm thursday 2pm`; add a tag with "called ..." or "with the tag ..." ("set an alarm at 5.30pm with the tag call Lisa") |
| `/alarms` | List scheduled alarms |
| `/docs <topic>` | Matching stored document content with its source |
| `/time`, `/date` | Time or date in the configured owner timezone |
| `/help` | All commands and argument hints |

Existing `/standby`, `/wake`, and `/reachy_status` controls remain available.

**Ending a conversation aloud.** Saying only "thank you", "thanks", "that's all",
"goodbye" or a close variant (the hub's deterministic matcher, whole utterance
only) makes Reachy answer "You're welcome. Goodbye." and end the session, so it
returns to the sleep pose while wake listening stays armed. "Thank you, what's
the weather?" is still a question.

**Calling Reachy mid-conversation.** Saying only "Hey Reachy" while it waits for
your next turn gets a short random affirmation ("Hmm?", "Hey!", "Hello!", "Yes?",
"I'm here.") and the conversation stays open; nothing is sent to the assistant.
"Hey Reachy, what time is it?" is still a normal question.

**Privacy mode** stops Reachy listening for "Hey Reachy". Say "turn on privacy
mode" in a live conversation (the robot confirms aloud, ends the session,
disarms wake listening and, with wake animation on, settles into its sleep pose), or send `/privacy on`. Turn it off only with
`/privacy off` in Telegram or the Voice tab button ("Turn off privacy mode");
it is never switched off by voice, because the robot is not listening. It is
the existing persisted wake arm, applied to every registered robot from
Telegram and to the selected robot from the UI.
Missing search arguments or extra arguments on fixed queries return a usage
hint. Unknown commands return help guidance instead of going to the model.
Work-data answers retain private routing; these shortcuts do not send emails,
modify tasks, or confirm destructive actions.

Coding status reads list sessions recorded by Reachy, plus a read-only
"Terminal sessions" section (title, folder, active/idle) for Claude Code
sessions you ran yourself when `CLAUDE_PROJECTS_DIR` is mounted; Reachy cannot
control those. Each list shows only the newest three, with no "older" count or scope footnote. Usage reads cover only Reachy-recorded
sessions. Session history is stored in Postgres and
survives a coding-agent-service restart (once migration `013_coding_agent` is
deployed). `/coding_usage` also lists Claude's 5-hour and weekly allowance when
Claude Code has reported it during a recorded session, with the reset time in
your persona timezone; these are the last reported figures, not a live account
reading, and Claude only reports them as you approach a limit. Hub registers
the command menu at startup when Telegram polling is enabled.

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

Replies that performed a web search show a Reachy search icon with a result
count. Click it (or focus it and press Enter) to expand the query, source
links and snippets. Source labels such as `[S1]` match the search result
order. Empty results and failed searches are labeled explicitly. This also
applies to robot microphone replies displayed in Chat; ordinary turns have
no search indicator. Search details clear with the visible transcript.

The left sidebar lists saved typed web chats, newest first, with title search.
**New chat record** begins a separate saved transcript; its first message becomes
the title. Select a record to read it and append another message. Records share
the existing companion session and recent context across channels; selecting one
does not replay its old messages into the model or restore old model context.
Core's recent reasoning context still resets on core restart.

Typed web turns, replies and search evidence are stored in homelab Postgres and
survive refresh, logout and service restart. **Hide messages** only clears the
visible transcript; select the record to show it again. Logout clears browser
memory, and no transcripts or keys are written to browser storage. Older chats
from before this archive existed cannot be recovered. Live robot voice turns
still appear in the current view but are not saved in these web records.

A turn without a recorded reply remains visibly uncertain, including after a
refresh; check its outcome before sending again. There is no automatic replay
or retry. Telegram failures do not disable chat. Poll health is not a guarantee
that outbound Telegram messages or inference work.

Work-data and conversation APIs require owner authentication. Accounts
settings specifically require the browser owner session. See
[ADR 0021](adr/0021-google-accounts.md).

## Talk through Reachy's microphone (Phase 24c)

**Settings → Voice & motion** has a **Robot microphone** panel. It works only when the
robot's deployment has enabled it
([deployment](deployment.md#robot-voice-conversation)). Otherwise the robot is
listed as "voice not enabled" or "offline". The conversation workflow passed
physical acceptance
([Phase 24d](phase-24cd.md#phase-24d--physical-end-to-end-acceptance)).
Spoken replies are kept short, a few sentences at most. Ask in the web
chat for a longer answer.
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

Settings → Models configures separate local/cloud endpoints and
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

Open **Settings → Accounts** in the operator dashboard.

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
