# Shadow semantic router

Status: implemented behind a disabled-by-default flag (2026-10-05). Owner decision: shadow only, no behaviour change.
Evidence and benchmarks live outside this repo in the `inferencing/bench/router` workspace; the numbers below are copied from there and are author-written data, except MASSIVE.

## Contract

- No tool execution from this path. The existing production flow runs unchanged and finishes first.
- After the reply is final, `process_conversation_turn` snapshots plain data into a background task. The task cannot alter the response, consent state, draft state, memory, tasks or robot state; a failure or a busy extractor only increments a counter.
- Order inside the task: semantic router -> few-shot extractor -> deterministic validator -> append one record (`route`, extracted/validated args, validator status, proposed next action). The existing deterministic matchers are not replaced; the record carries the production handler beside the router's route.
- Typed `/…` commands and turns the production path answered deterministically are not special-cased except that slash input is skipped; state-bound approvals are recorded like any other turn so they can be compared.
- Robot requests stay on `command_suggestion.classify` (Qwen). The router's `robot.*` route is recorded and never extracted.
- `memory.forget` and `tasks.complete` always keep the validated resolved target in the record (not for a SENSITIVE-labelled turn).
- `needs_clarification` records the reason category only (`task:unresolved_reference`, `query:ungrounded`, …); nothing is synthesised into the live conversation. Words the model proposed are never recorded.
- Authorization stays outside the router: when this is later promoted, the router and extractor propose and the consent gate (ADR 0011) and deterministic policy authorize.

## Components

| Piece | Where | Notes |
|---|---|---|
| Router sidecar | `inferencing/router` (own compose project, port 8011) | ModernBERT-base x3, 18 fine routes, ONNX FP32 on CPU, argmax (no confidence threshold). `POST /route`; stores nothing. |
| Extractor | `companion_core/shadow_router/extractor.py` | Few-shot, schema-constrained JSON, temperature 0, **local provider only** (never the cloud role). One extraction at a time; a second concurrent one is dropped and counted (`dropped_busy`). |
| Validator | `companion_core/shadow_router/validator.py` | Deterministic. Rejects placeholders, copied schema text, pure references (it/this/that one/them/him/her), invented words, copies of the instruction, multiple targets for forget/complete; bulk scope comes from the words as well as the model and is refused. |
| Hook | `app.py` (`production_handler` labels, one background submit after `record_reply`) | Wrapped so nothing from the shadow reaches the turn. |
| Report | `tools/shadow_router_report.py` | Observable counters, production-vs-router table, and, given graded labels, `unsafe_would_execute` and `safe_but_withheld`. |

## Enabling

Off unless all of these are set (compose passes them through; defaults are off):

| Variable | Meaning |
|---|---|
| `SHADOW_ROUTER_ENABLED=true` | master switch |
| `SHADOW_ROUTER_URL` | the router sidecar, reachable from the companion-core container |
| `SHADOW_ROUTER_LOG_PATH` | JSONL file (default `/data/shadow-router/shadow.jsonl`, volume `shadow-router`), created mode 0600 |
| `SHADOW_ROUTER_LOG_TEXT=true` | also write the utterance (never for a sensitive-labelled turn); default off, records then hold a hash and length |

The sidecar is not part of the homelab compose file yet. It shares the GPU box's CPU with the 7B: measured contention (see the bench workspace) says x3 is the deployable size at a realistic rate; CPU pinning is untested.

## Counters

`would_execute`, `would_execute_write`, `withheld` (with `withheld_reason:*`), `bulk_refused`, `dropped_busy`, `router_error`, `extractor_error` are observable per process and in the records. `unsafe_would_execute` (a write the validator would let through that is not what the user justified) and `safe_but_withheld` (a legitimate request the validator would have turned into a question) need a person's grade per record; use `tools/shadow_router_report.py --labels`.

## Evidence carried forward

- Router (fine taxonomy, argmax): MASSIVE-test fine accuracy 0.919, challenge-v1 0.890, challenge-v2 0.908; 13 writes on a none/unsupported turn on MASSIVE-test, which thresholds cannot remove, hence mandatory confirmation.
- Extractor + validator on a 50-case holdout written after the validator was frozen: unsafe executable extraction 1/50 (2%) few-shot, 4/50 (8%) zero-shot; the model alone was 36% / 52%. 24/24 unresolved references and 4/4 bulk forgets were withheld/refused. The 1 miss was a comma-joined pair of targets; the rule added afterwards is not counted. The 2% is the number to quote.
- Known cost: the validator over-withholds some legitimate phrasing ("queue up call the electrician for tuesday"); in shadow this is what `safe_but_withheld` measures.
- Known limits: all non-MASSIVE data is author-written; voice transcription noise and real utterances are untested; the extractor may truncate a stored fact (grounded but lossy), which the consent echo-back is meant to catch.

## Removing

Unset `SHADOW_ROUTER_ENABLED`. Nothing else depends on this package; delete `companion_core/shadow_router/`, the `production_handler` bookkeeping and the submit block in `app.py`.
