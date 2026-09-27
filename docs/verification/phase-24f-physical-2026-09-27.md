# Phase 24f physical run (2026-09-27)

**Scope:** rerun of step C (listening and thinking gestures on, wobble
off) from the [2026-09-26 run](phase-24f-physical-2026-09-26.md), on
nano-1 with the owner present. The owner stopped it after four turns on
the gesture design, not on a fault. Nano logs are in
`~/24f-logs/boot-20260927-no-motors.log` and the embodiment container log.

## Versions

| Component | Version |
|---|---|
| Hub and core | `7a597e6` (homelab, unchanged; `637fcad`/`c2db3d2` not deployed) |
| Nano checkout | `1473674` |
| Nano embodiment | Image `c314d4fa` (`reachy-embodiment:b36736d`, retagged `:local`); the previous `eb1e92e9` is kept as `reachy-embodiment:eb1e92e9` for rollback |
| Daemon | `reachy-mini` 1.8.4 |

## Boot with motor power off: first real automatic recovery

The Nano booted at 06:13 WIB with the motor supply off. The daemon found
the USB serial controller (`/dev/ttyACM0`) but none of motors 10–18 and
reported `state: error`, "No motors detected". `reachy-daemon-recovery`
restarted it once (06:13:48), found the error again after that restart
(06:30:54), logged "Owner action needed" and exited with status 1, with no
further restart. This is the first real error-triggered run of the
once-per-boot recovery; both the restart and the second-error stop behaved
as designed. `reachy-embodiment` kept retrying its start (41 attempts)
because the daemon never created its camera socket; this was noisy but harmless.

The owner restored power and rebooted the Nano and robot. After that the
daemon was `running` with every motor found, 0 control-loop errors at about
49 Hz, and the recovery unit armed and idle.

## Image swap

The container was recreated from `reachy-embodiment:local` (now
`b36736d`) by `sudo systemctl stop reachy-embodiment`, `docker rm` and
`scripts/start-reachy.sh`. The daemon was already running, so this did not
trigger its wake-up. The embodiment started healthy, registered as nano-1
and reported `conversation_motion: false`, `speech_wobble: false`. The
owner switched gestures on in the portal. The embodiment logged the hub's
`PUT /settings/motion` 200 and then reported `conversation_motion: true`.

## Step C rerun (00:56–00:59Z): stopped by the owner

| Measure | Result |
|---|---|
| Gesture delivery | **4 turns, 0 `play_behaviour` or home failures, 0 connection resets, 0 daemon `move/stop` 500s.** The 2026-09-26 run failed on almost every transition, so this is physical evidence for `b36736d`, but too few turns to accept the row |
| False speech | Turns 2 and 4 were `no_speech` cuts of 1.15 s and 1.28 s. Each started 1.8 s and 3.3 s after the previous reply finished, while `attentive1` and its sound were playing. The microphone captured the gesture's own sound |
| Timing | Turns 1 and 3: 3.43 s and 3.38 s from the end of speech to the first audio. That is too few turns for the timing row |
| Other | The daemon logged two IK "collision detected or head pose not achievable" warnings at 00:57:15Z, before the voice session started. No embodiment log line matches them, so the cause is unexplained |

**Owner feedback that ended the run:** the gestures are repetitive,
especially listening, which plays the same sound every time. The sequence
is also too long to tell whether to speak before or after it finishes.

## Why the recorded mapping cannot be tuned

The emotion moves were measured from the dataset on the Nano. Every
emotion move except `waiting` (10.0 s) has a sound. `attentive1` runs
4.3 s and `thoughtful1` 5.9 s. The shortest move is 2.1 s (`inquiring1`),
also with sound. The daemon endpoint
`POST /move/play/recorded-move-dataset/{dataset}/{move}` always plays a
move's sound and has no option to mute it. Rotating between recorded
moves would reduce the repetition, but not the sound, the length or the
self-capture. The mapping also misses the plan's own listening row,
[quiet attentive posture, avoid noise during capture](../phase-24f.md#3-local-conversational-motion-policy).

**Next:** replace the listening and thinking gestures with short, silent,
bounded goto poses. Rerun step C once, in full, with the new poses.

## Silent poses against the 1.8.4 mockup (not physical)

`MotionController` with `ReachyDaemonBackend` was run against a local
`reachy-mini-daemon --mockup-sim --no-media` on port 18000 through listening,
thinking, a held segment, speaking, a second turn, and a Stop during
thinking. Every pose was reached and held with nothing left running. The held
segment returned to the same turn's listening pose, and speaking returned
to home. A thinking goto preempted by speaking ended cleanly. The Stop left
the head where it was, with no move running. The daemon logged no 500s or
`KeyError`s. Mockup-sim has no motor dynamics, so this checks the command
path, not how the poses look. Embodiment tests: 133 passed and 5 skipped. The
poses validate against the daemon's own `GotoModelRequest`.

## Pose tuning on the robot (owner watching)

The daemon had been put into standby from the hub at 01:09Z. The owner
resumed it (wake-up watched), and it reported `running` with 0 errors
before any pose was sent. Bounded REST gotos, each from home, with the
owner judging:

| Pose sent | Reached | Owner |
|---|---|---|
| Listening: roll 0.12, antennas [0, 0], 0.5 s | roll 0.113, antennas [−0.006, −0.002] | Perked up, but too small |
| Listening: roll 0.22, antennas [0.12, −0.12] | roll 0.228 | Bigger still |
| Listening: roll 0.32, antennas [0.25, −0.25] | roll 0.345, yaw −0.060 (coupling) | Happy |
| Thinking: roll −0.08, pitch −0.15, yaw 0.30, antennas [−0.50, −0.25], 0.8 s | roll −0.061, pitch −0.142, yaw 0.271 | Looks **up** (negative pitch is up); antennas fine; exaggerate more |
| Thinking: roll −0.10, pitch −0.22, yaw 0.40, same antennas | roll −0.097, pitch −0.225, yaw 0.380 | Better |
| Thinking mirrored: roll 0.10, pitch −0.22, yaw −0.40, antennas [0.25, 0.50] | roll 0.091, pitch −0.262, yaw −0.385 | Good, a proper mirror |

No IK warnings, and the daemon stayed `running` throughout. The head was
returned home with nothing left running. These values are the constants
in `motion.py`.

## Question script for the step C rerun

The step B questions from 2026-09-26 were not saved (the database keeps no
transcripts), so the rerun uses this fixed script: short, public,
non-search general-knowledge questions, asked one at a time.

1. What's the capital of France?
2. How many legs does a spider have?
3. What colour do you get when you mix blue and yellow?
4. Who wrote Romeo and Juliet?
5. What's the largest planet in our solar system?
6. How many days are there in a leap year?
7. What gas do plants take in from the air?
8. What's the boiling point of water in Celsius?
9. Which ocean is the largest?
10. How many sides does a hexagon have?
11. What's the chemical symbol for gold?
12. Who painted the Mona Lisa?
13. What's the tallest animal in the world?
14. How many continents are there?
15. What's the freezing point of water in Fahrenheit?
16. Which planet is known as the Red Planet?
17. What's the main ingredient in guacamole?
18. How many minutes are in an hour?
19. What language is spoken in Brazil?
20. What's the square root of sixty-four?
21. Which bird is a symbol of peace?
22. What do bees make?
