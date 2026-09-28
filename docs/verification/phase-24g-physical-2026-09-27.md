# Phase 24g first physical run (2026-09-27)

**Scope:** the first physical run of wake monitoring on nano-1 with the
owner at the robot, right after deployment:
- the hub, core and migration at `95cbc0a` (schema `009_wake_arm`);
- embodiment `b77ff6a` (`796d65ee`), with `WAKE_ANIMATION_ENABLED=true`.

The owner armed "Hey Reachy" from the robot microphone panel at 09:37:51Z.
The outcomes come from the embodiment and hub logs, which hold scores and
outcomes only; no transcripts were kept. This is informal usability
evidence, not the 24g acceptance matrix.

## Results

| Outcome | Count | Cause |
|---|---|---|
| Detected | 8 of 8 attempts | Scores 0.77–0.99 |
| Hub rejected `no_request` | 4 | The robot uploaded the candidate as holding a request, but STT heard only the wake phrase. The segment's length includes 0.3 s pre-roll and 0.7 s trailing silence, and the daemon's wake-up sound followed the phrase, so "Hey Reachy" alone passed the 1.6 s length rule |
| Discarded on the robot, no request | 2 | The owner waited for the wake-up animation to finish before speaking. The 3 s allowance, counted from the end of the phrase's segment, ran out first |
| Admitted and answered | 1 | Said in one breath. The reply started 2.4 s after the cut, and the session ended 10 s after the reply with "No follow-up heard" |

The owner's observation: the animation runs after "Hey Reachy", so the
speaker does not know when to begin, and the pause while it plays sends
Reachy back to sleep.

## Change made the same day

At the owner's direction, the daemon's full wake-up move was replaced by a
silent alert pose: a 0.5 s goto that lifts the head about a third of the
way from sleep towards home. It gives quick feedback, and the robot keeps
waiting for the rest of the turn. The return to sleep from it is a silent
goto. The daemon's go-to-sleep routine, which plays a sound every time,
now runs only from an unknown pose.

The candidate timings changed as well:
- speech is measured without the segment's pre-roll and trailing silence,
  with a 1.2 s threshold;
- the request may start up to 4 s after the phrase's segment ends.

This needs a rebuild of both the hub, which sends these limits, and the
robot, then the scenarios again.

## Second run on `b62a023` (alert pose)

The hub was rebuilt at `b62a023` (09:54Z), and the robot was recreated on
`ebfffcef` at about 10:01Z. The arm survived the hub restart and was sent to
the robot again when it registered.

- A conversation started by voice ran from 10:02:26Z until 10:03:52Z, and
  ended with "No follow-up heard".
- Between 09:56 and 10:00Z, while the old robot container was still running
  with the new hub limits, the hub rejected 4 candidates as
  `no_wake_phrase`. They are unattributed.

The owner's findings:
- the head should go home once a conversation is admitted;
- a false positive should return to sleep without the daemon's snore sound.

The logs traced the snore to a rest-pose tracking bug: idle presence
requests that start no move reset it, so every rest used the daemon's
`goto_sleep` routine. It was fixed in `0880b1b` (third run, below).

## Third run on `0880b1b` (silent rest poses)

The owner recreated the robot on `15ba2797` (`0880b1b`) at 10:43:42Z, with
voice on, `WAKE_ANIMATION_ENABLED=true`, 24f motion off and wake armed.
The times below are from the embodiment log and the daemon's access log.

| Time (Z) | Event | Head moves (daemon) |
|---|---|---|
| 10:44:14 | armed | 10:44:23 home, 10:44:24 sleep (first rest, pose unknown) |
| 10:44:26 | detected (0.73); discarded 10:44:31, no request | 10:44:26 alert, 10:44:31 sleep |
| 10:45:59 | detected (0.98); session, 1 turn, ended 10:46:14 | 10:45:59 alert, 10:46:14 sleep |
| 10:46:38 | detected (0.95); session, 2 turns, ended 10:47:50 | 10:46:38 alert, 10:47:50 sleep |
| ~10:48 | owner switched the 24f motion on (`PUT /settings/motion`) | — |
| 10:48:46 | detected (0.99); rejected by the hub 10:48:49 | 10:48:46 alert, 10:48:49 sleep |
| 10:48:55 | detected (0.89); session, 3 turns, ended 10:49:49 | alert, then conversation motion and wobble |
| 10:50:07 | detected (0.99); discarded 10:50:12, no request | 10:50:07 alert, 10:50:12 sleep |

Results:
- **False wakes pass.** Rejected and discarded candidates went from the
  alert pose straight to sleep in one silent goto. No daemon routine
  played. The owner confirmed it "works as intended".
- The owner saw a false wake apparently go through home. That was the
  one-time rest after the recreate (home, then down, 3 s before the
  detection), not the false wake's own return.
- **The owner reported the 24f conversational motion behaved as
  expected**, from 10:48 with those switches on. This is an owner
  observation, not a row of the deferred 24f acceptance.
- **Home on admission failed.** The two sessions with motion off have no
  home goto. The hub opens an admitted candidate's session, and sends
  `voice_start`, before it answers the upload. The robot then suspended the
  monitor mid-upload, so the move after the upload never ran; the tests'
  fake uploader answered first. Fixed in `c579cc8`: a suspend during a
  pending candidate is the admission. That fix is built (`a9baf002`) and
  not yet run on the robot.

## Admission fix and calibration follow-up

The following observations were consolidated from HANDOVER on 2026-09-28;
no physical checks were rerun during that documentation pass.

**Home on admission: confirmed on the robot, `c579cc8` running since
10:57:45Z.** The daemon's access log shows a goto right after each
`wake candidate admitted` (11:05:12.9Z and 11:06:28.7Z), before the later
sleep return. No further action needed on this item.

**Session 1 (calibration) done, 2026-09-27 13:43-14:46Z — clean, no
issues found.** 26 wake detections, 24 rejected `no_wake_phrase`, 1
discarded (no speech followed), 1 admitted. The owner confirms only 1
deliberate "Hey Reachy" attempt was made and it succeeded first try; the
other 25 were the scripted false-trigger scenarios, all correctly
rejected. Isolation checks (no TTS/tools/search/durable transcript,
robot returns to sleep) pass for all 25. Raw logs in
`/tmp/.../scratchpad/24g-acceptance/` (session-scoped, not durable).

Added a log line (`bab441e`) so admission latency (upload -> voice_start)
can actually be measured — the existing logs only gave detected-to-
admitted, which conflates the caller's own speech duration. Deployed and
confirmed running (`reachy-embodiment:local`, re-registered as `nano-1`,
re-armed automatically).

**Session 2 (first held-out attempt), 2026-09-27 15:08-15:16Z — found a
real bug, not scored as final.** 8 detections: 4 rejected
`no_wake_phrase`, 1 discarded ("no request followed"), 3 admitted (each a
clean multi-turn conversation). Isolation checks pass; no stray tool/
search activity. The discard was a genuine attempt: the owner said "Hey
Reachy," waited to see the alert-pose cue, then started speaking — by
then most of the 4 s `speech_start_seconds` budget was gone (the alert
goto itself dispatches within ~1s of detection, so the shortfall is
human reaction time to the cue, not code latency). 3/4 genuine acceptance
(75%) misses the 90% target.

**Fixed (`4b6893b`): `speech_start_seconds` raised 4.0 -> 6.0s** in
`shared/models/robot_voice.py` (only the hub needs
rebuilding for this one — the robot always runs whatever `WakeLimits` the
hub sends at arm time, no Nano image change needed). ADR 0023 and the
fixture-timing tests updated. Homelab hub/core rebuilt and restarted;
robot reconnected and re-armed automatically, wake counters reset to
0/0/{}.

The fresh held-out run was deferred by the owner on 2026-09-28. These
results do not close the [acceptance gate](../phase-24g.md#verification-and-exit-criteria).
