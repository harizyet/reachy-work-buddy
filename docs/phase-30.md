# Phase 30 — Platform stabilization and acceptance

Status: **started 2026-10-02**. Scope and exit criterion are owned by the
[forward roadmap](plan.md#forward-roadmap-phases-30); this page owns the
working sequence, the new metric definition and the closure triage. It adds no
runtime feature beyond what is listed under [Code changes](#code-changes).

Absorbs the open rows of [22b/22c](phase-22-23.md#satisfactory-run-acceptance-matrix),
[24e](phase-24e.md), [24f](phase-24f.md) and [24g](phase-24g.md). Motion rules
for each step are in the [deployment guide](deployment.md#robot-host-and-jetson-nano):
a development session may send bounded gotos unattended, but recorded
emotions/dances (including mapped `/behaviour` moves) and any daemon
start/restart/resume need the owner present.

## Sequence

| Step | Work | Needs the owner |
|---|---|---|
| 30.1 | Recreate `reachy-embodiment` on the Nano with image `:2bf82e4` and verify: a raw wake hit causes no motion; hub admission lifts the head to home; measure the admission-to-lift delay | Yes: sudo/container recreate on the Nano |
| 30.2 | Define and record `visible_false_activations_per_hour` ([below](#visible_false_activations_per_hour)) in the [24g acceptance](phase-24g.md#acceptance-requirements) | No |
| 30.3 | Calibration session, then cold held-out run to the [agreed targets](phase-24g.md#agreed-numeric-targets-owner-2026-09-27), covering immediate-request and pause-before-request; occupied-room exposure | Yes: speaking and scoring |
| 30.4 | Decide whether detector threshold/model tuning is needed, from calibration data only (never from the held-out run) | Decision |
| 30.5 | Selective closure of the [triage list](#closure-triage) | Per row |

30.1 gates 30.3: the held-out run must use the deployed behaviour, not the
alert-pose build the earlier evidence was gathered on.

## visible_false_activations_per_hour

A **visible false activation** is any robot reaction an observer in the room
can see or hear that was not caused by a genuine, intended "Hey Reachy". With
the alert pose removed, a raw detector hit by itself is invisible, so the count
is, per scored exposure period:

- every false conversation admitted (head lifts to home, session opens), plus
- any other visible or audible cue on a non-genuine hit: unprompted motion, a
  sound, a spoken reply, or a head position that fails to return to rest.

It is reported beside, not instead of, wake candidates/hour and false
conversations admitted/hour. Because admission is the only visible cue, it
equals the false-conversation rate unless an extra cue is observed; a
difference between the two is itself a finding.

Method: the owner or observer logs each visible reaction with a timestamp
during the exposure window; embodiment log lines (`wake phrase detected`,
`wake candidate admitted`, `wake candidate rejected by the hub`, `wake
candidate discarded on the robot`) give the candidate/admission timeline to
match against. Exposure hours, scenario counts and the observer's definition
are recorded in the dated verification record; no per-hour target is set until
the owner agrees one before the scored run, per the 24g rule against tuning on
final trials.

## Closure triage

Rows below are proposals. Waiving or passing one needs an owner decision, and
each decision is recorded in the dated record, not here.

| Row | Source | Proposed handling |
|---|---|---|
| LOCAL-camera fresh scene | 22c | Run: one deliberate capture of a changed scene |
| Outage/reconnect | 22b | Run: stop/restore hub link, confirm re-arm without owner action |
| Backup/restore | 22b | Run against a disposable Compose project, never user volumes |
| Stop while homing | 24f | Run as bounded diagnostic motion |
| Mid-reply motion switch-off | 24f | Run as bounded diagnostic motion |
| 30-minute conversation | 24e/24f | Owner decides: run or keep waived |
| Remaining Nano diagnostics | 24e | Owner decides per diagnostic |
| Privacy/consent, channels matrix | 22b | Owner decides; overlaps Phase 33 |

## Code changes

None committed yet for 30.1–30.5. The image for 30.1 already exists on the
Nano. Any harness for 30.2 should consume the existing embodiment log lines
rather than add runtime endpoints.

## Exit

As in the [roadmap](plan.md#forward-roadmap-phases-30): Reachy can stay armed
in a normally occupied room without visibly reacting to routine false wake
detections and without opening false conversations at an unacceptable rate.
Evidence goes in `docs/verification/phase-30-<date>.md`.
