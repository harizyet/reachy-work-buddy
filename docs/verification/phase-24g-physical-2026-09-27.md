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
