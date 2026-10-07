# ADR 0027: Alarms with presence-gated, privacy-aware delivery

- Status: **Accepted 2026-10-05** for [Phase 38](../phase-38.md).
- Date: 2026-10-05

## Context

Reminders are claim-once Telegram pushes. The owner asked for an alarm clock: at a set time the robot plays a TuneIn stream chosen in the web UI, alarms can be set from Telegram or conversation and are listed in the web UI, and a reminder can offer or carry an alarm ("remind me about the cake on Thursday" -> "want an alarm for Thursday?" -> "2pm" -> "alarm set for 2pm"). It must obey privacy mode and must not play to an empty room.

Nothing existed to build on for two inputs: there is no room-occupancy signal (embodiment `presence.py` is robot heartbeat and idle animation, and `interruption_policy.is_occupied` means DND/meeting/event, not a person being there), and the robot can only play WAV bytes (`/audio/play`), not a stream.

## Decision

1. **Alarms are a core domain.** An alarm has a time, an optional link to a reminder, a station (or the default chat sound), a status and a claim marker. Core owns storage, validation and the due claim, with the same InMemory/Postgres store pair and claim-once poll as reminders. Alarms never execute anything beyond notification and playback; the LLM has no authority over them. Setting one from conversation goes through a deterministic handler and a state-bound offer, not free-form model output.
2. **The hub decides delivery; the robot only plays or reports.** When an alarm is due the hub applies the delivery policy below. Embodiment exposes occupancy and stream playback as hardware-facing operations and holds no schedule, privacy or consent logic (ADR 0006).
3. **Delivery policy, in order.**
   - Privacy mode (wake arm disarmed, spoken or remote): never play audio; send the Telegram reminder.
   - Robot unavailable: Telegram.
   - Do-not-disturb or meeting: no audio; Telegram.
   - Occupancy check says nobody is present, or cannot say: no audio; Telegram fallback, marked as "not played, nobody detected" so the owner knows. Unknown is treated as absent, because playing to nobody costs nothing but a missed alarm is covered by Telegram, whereas playing when privacy was intended is the failure to avoid.
   - Otherwise play the stream, with a bounded duration and a stop path (button in the UI, `/reachy alarm stop`, palm stop where it exists).
   Telegram is always sent when audio is not played, and also as a short text when it is.
4. **Occupancy is a room sweep, not one forward frame (owner direction 2026-10-05).** The check turns the head/body through a small fixed set of bounded stops covering the room, captures one frame at each, runs person/face detection on the hub (MediaPipe BlazeFace short range, pinned in the hub image, so faces turned toward the camera within a few metres; a person seen from behind is missed and covered by the Telegram fallback), and returns the robot to where it started. Result: a boolean, a timestamp, the stops covered and the method; it stops at the first person found, and stopping the sweep early is always safe. No frame is stored or logged. It runs only when an alarm is due or the owner asks, never continuously, and never in privacy mode (already ordered first). Motion goes through a new bounded embodiment operation (`/sweep`: five fixed body-yaw stops about -57 to +57 degrees with the head level, requested by index so the hub never sends an angle, refused during a conversation or remote control, preempted by `stop()`); `/gaze` and `/pose` stay reserved, so this is a dedicated sweep operation, not an arbitrary pose API. A sweep before an alarm is a new class of unattended motion beyond the exceptions in AGENTS.md, so it shipped disabled; the owner then decided on 2026-10-05 that it is intended design and it is on by default (`PRESENCE_SWEEP_ENABLED=false` in the robot env file turns it off, and the check then uses the single forward frame, which cannot see the room from the sleep pose). Development tests may send bounded gotos per the 2026-09-25 waiver.
5. **Stations are curated by the owner.** The web UI searches TuneIn's public OPML directory and the owner saves a station. The stream URL is resolved server-side with an SSRF guard (http/https only, public addresses only, no redirects to private ranges) and never accepted from Telegram or conversation. The robot never fetches the URL; the hub decodes the stream and sends bounded WAV chunks.
6. **Reminder tie-in is state-bound.** A reminder created with a date/time may produce a single pending offer scoped to the conversation; only an affirmative reply that carries or follows a time creates the alarm. An alarm linked to a reminder completes the reminder's delivery, so the same moment does not notify twice.

## Consequences

- Core gets one new store, migration 015, and routes; hub gets a scheduler loop, a delivery policy module and an operator proxy; embodiment gets a presence-detect operation and stream-chunk playback. No sibling imports.
- A false "nobody there" costs a Telegram message instead of audio. A false "someone there" plays audio to an empty room, which is harmless.
- A sweep costs a few seconds of motion before each audible alarm and runs unattended: the owner decided on 2026-10-05 that the sweep is intended design and needs no supervision or approval.
- Camera detection on the Nano is not assumed; detection runs on the hub from a fetched frame.
- Live playback and physical acceptance need the owner; automated tests use simulated backends and say so.

## Addendum 2026-10-07: repeat and the on/off switch

At the owner's request the alarm screens follow the phone Clock app, so an alarm can repeat on chosen weekdays and be switched off without deleting it. This changes what an alarm record is, not how it is delivered: every rule above (privacy, availability, do-not-disturb, occupancy, Telegram fallback, the sweep) applies unchanged to each ring.

- An alarm keeps one row. `repeat` lists weekdays and an empty list means once; `enabled` is the switch. The row's `due_at` is always the next ring.
- A due alarm is claimed once as before and, when it repeats, the same request re-arms it for its next matching day in the owner's time zone, so the hub's delivery sees the alarm that rang and a crash cannot leave a daily alarm silent for good.
- A disabled alarm is never claimed. Switching one on, or giving it a new time or days, schedules its next occurrence.
- Deleting removes an alarm from the clock (history stays in action receipts), including one that has already rung.
- Snooze is not part of this change.

## Addendum 2026-10-07: phone backup when Reachy cannot play it

When Reachy is offline, finds nobody in the room during the sweep, or cannot play the alarm, the owner wants the alarm to
sound on their Android phone, not only arrive as a Telegram message. The hub's delivery order and fallbacks above are unchanged and
there is no push channel from the hub to the phone. Instead the app keeps its own exact clock alarm for each of the owner's
alarms and, when one fires, asks the hub what happened to that ring:

- The hub records the outcome in the alarm's `delivery` and now clears it when it picks a ring up, so a repeating alarm's
  earlier outcome is never mistaken for this ring's.
- The phone rings for "robot unavailable", "not played, nobody detected" and "failed: …", and when the hub cannot be reached
  or does not answer within three minutes. It stays silent for "played", "stopped by owner", privacy mode and do-not-disturb or
  meeting, so those owner choices still hold on the phone.
- An alarm that was switched off, moved or deleted elsewhere is dropped when the phone asks, so a stale phone copy does not ring.
- The phone's copy is refreshed when the app opens, when an alarm rings, after a restart and by a 15-minute background job; an
  alarm created shortly before it is due elsewhere may therefore have no phone backup.
