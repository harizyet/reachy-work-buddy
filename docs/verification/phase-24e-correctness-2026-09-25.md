# Phase 24e correctness set: local model (2026-09-25)

**Result: PASS.** 82 of 87 scored turn runs passed (94.3%), and every
category reached at least 87.5%. The owner-agreed threshold is at least
90% overall and at least 80% per category. Voice turns stay on the local
model, and the cloud model was not run.

This is an in-process measurement: companion-core with the real local model
and fixture search results. It is not a robot or physical check, and core
time here is not the voice latency budget.

## Order of events

1. The search-rule fixes, the case set, the
   [scoring rules](../phase-24e.md#correctness-set-scoring-rules) and the
   threshold were written first. The owner agreed the threshold and the
   plain-statement search fix before any run. Both were committed and
   pushed in `73763c8`.
2. The set was run once on `73763c8`. The result below is that first and
   only run; no case, rule or threshold changed afterwards.

## Setup

| Item | Value |
|---|---|
| Commit | `73763c8` |
| Case file | `correctness-v1.json` (version 1), 20 conversations, 29 scored turns, 3 repeats |
| Model | `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` on OVMS (`openvino/model_server:latest-gpu`), `http://localhost:8000/v1` |
| Routing | `local_only` for the run. The homelab core uses the same OVMS model as `local` with `local_with_cloud_fallback`, checked read-only from its settings (no keys shown) |
| Host | Homelab, Intel Core i9-13900H |
| Run | 2026-09-25, finished 06:57:37Z; `run_correctness.py --base-url http://localhost:8000/v1 --model OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` |
| Output | `~/24e-correctness/local-20260925T0656Z/` (`summary.json`, `transcript.jsonl`); fixture content only, no personal data |

## Scores

| Category | Passed | Rate | Floor |
|---|---|---|---|
| Context | 12 / 12 | 100% | 80% |
| Statement | 21 / 24 | 87.5% | 80% |
| Social (closings, greetings) | 18 / 18 | 100% | 80% |
| Self-identity | 9 / 9 | 100% | 80% |
| Search-grounded | 22 / 24 | 91.7% | 80% |
| **Overall** | **82 / 87** | **94.3%** | 90% |

Core time per turn, including the command-suggestion and reply model calls:
p50 713 ms, p95 1717 ms, max 2119 ms.

## Failures

- **Search results misused (2 of 3 repeats).** The weather follow-up "What
  about tomorrow?" searched correctly: the merged topic, localized to
  Singapore. The model still gave figures that were not in the fixture:
  "27°C to 34°C" and "highs around 32°C" instead of 33°C, and it added
  light rain. This is the 24d "search results misused" failure, and the
  set still reproduces it on number details.
- **Statements answered at length (3 runs).** "I'm feeling a bit tired
  today." got 32 and 48 words of unrequested suggestions. "The printer on
  my floor is out of paper again." got 38 words of troubleshooting
  questions. Neither searched.

Every closing, greeting and self-identity turn stayed within limits and
did not search. That includes "Who are you?" and "Goodbye for now." after
a weather search, the two 24d misfires. The provider-failure and
irrelevant-results cases said the answer was not available rather than
inventing a Zig version.

## Not covered

The run used fixture search results, not live providers, and text from the
case file, not STT output. The voice latency budget and the turn-path rows
still need the physical run in
[Phase 24e](../phase-24e.md#3-deferred-24d-acceptance-rows). The failures
above pass the agreed threshold. Whether to tighten the reply prompt for
statements, or for grounded numbers, is a separate owner decision, and any
change needs a new measurement.
