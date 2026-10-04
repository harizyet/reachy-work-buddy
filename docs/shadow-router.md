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
| Router sidecar | `deploy/homelab/semantic-router/` (compose profile `shadow-router`, internal port 8012, CPU cap `SEMANTIC_ROUTER_CPUS`=3) | ModernBERT-base x3, 18 fine routes, ONNX FP32 on CPU, argmax (no confidence threshold). `POST /route`; stores nothing. Models are mounted, not in git (see its README). |
| Extractor | `companion_core/shadow_router/extractor.py` | Few-shot, schema-constrained JSON, temperature 0, **local provider only** (never the cloud role). Shadow jobs run one at a time from a bounded queue (`SHADOW_ROUTER_QUEUE_SIZE`, default 3); when it is full the oldest job is dropped and counted (`dropped_busy`), so shadow work never backs up behind production. A dropped turn has no record. |
| Validator | `companion_core/shadow_router/validator.py` | Deterministic. Rejects placeholders, copied schema text, pure references (it/this/that one/them/him/her), invented words, copies of the instruction, multiple targets for forget/complete; bulk scope comes from the words as well as the model and is refused. |
| Hook | `app.py` (`production_handler` labels, one background submit after `record_reply`) | Wrapped so nothing from the shadow reaches the turn. |
| Report and grading | `tools/shadow_router_report.py`, `tools/shadow_router_grade.py` | Observable counters, production-vs-router table; blind sheet, labelled-results counters `unsafe_would_execute` and `safe_but_withheld`, and a purge step. |

## Enabling

The sidecar is started with `scripts/start-homelab.sh --shadow-router` and does nothing by itself. companion-core stays off unless all of these are set (compose defaults are off):

| Variable | Meaning |
|---|---|
| `SHADOW_ROUTER_ENABLED=true` | master switch |
| `SHADOW_ROUTER_URL` | default `http://semantic-router:8012` |
| `SHADOW_ROUTER_LOG_PATH` | JSONL file (default `/data/shadow-router/shadow.jsonl`, volume `shadow-router`), created mode 0600 |
| `SHADOW_ROUTER_LOG_TEXT=true` | also write the utterance and the validated arguments (never for a sensitive-labelled turn). Only for the grading window |
| `SHADOW_ROUTER_MAX_TURNS` | stop recording after this many accepted turns (0 = unlimited) |
| `SHADOW_ROUTER_QUEUE_SIZE` | pending shadow jobs before the oldest is dropped (default 3) |

It shares the host CPU with the production services; the sidecar is capped at 3 CPUs and 3 GB. Measured contention says x3 is deployable at a realistic rate; CPU pinning is untested.

## Trial procedure

Fixed-size, then removed. Nothing here changes a live reply, so rollback is unsetting the flag.

1. Put `SHADOW_ROUTER_ENABLED=true`, `SHADOW_ROUTER_LOG_TEXT=true`, `SHADOW_ROUTER_MAX_TURNS=400` in `deploy/homelab/.env`; `scripts/start-homelab.sh --shadow-router --build`. This rebuilds and recreates companion-core (a brief restart) and starts the sidecar.
2. Use the assistant normally until the cap is reached (`trial_complete_skipped` starts counting).
3. Immediately set `SHADOW_ROUTER_LOG_TEXT=false` (or `SHADOW_ROUTER_ENABLED=false`) and recreate companion-core; copy the log out of the volume to a local 0600 file.
4. `uv run python tools/shadow_router_grade.py sheet shadow.jsonl --out sheet.jsonl`: every disagreement plus a random sample of agreements, shuffled, utterance only.
5. Label the sheet blind (before looking at any router, validator or production output): `gold_route`, `executable`, `gold_args`.
6. `uv run python tools/shadow_router_report.py shadow.jsonl --labels labels.jsonl`: reports `unsafe_would_execute` and `safe_but_withheld` per stratum (disagreements are all graded; the agreement sample is random, so do not pool the strata), beside `dropped_busy`, `withheld`, `would_execute`, `bulk_refused`.
7. `uv run python tools/shadow_router_grade.py purge shadow.jsonl --labels labels.jsonl --aggregates aggregates.json --delete sheet.jsonl labels.jsonl`: removes the utterance, its hash, the validated arguments and resolved targets from the log and keeps only aggregates. Remove the volume copy of the raw log as well.
8. Do not change a live handler from the trial's examples until enough real traffic has accumulated to judge them.

## Counters

`would_execute`, `would_execute_write`, `withheld` (with `withheld_reason:*`), `bulk_refused`, `dropped_busy` (jobs dropped from the bounded queue), `trial_complete_skipped` (turns refused after the cap), `shadow_error` (an unexpected exception inside the shadow task), `router_error`, `extractor_error` are observable per process, and mean different things when judging coverage; the turn cap counts accepted inputs, not completed records, so contention cannot stretch the trial; the report recomputes the outcome counts from the records. `unsafe_would_execute` (a write the validator would let through that is not what the user justified) and `safe_but_withheld` (a legitimate request the validator would have turned into a question) need a person's grade per record; use `tools/shadow_router_report.py --labels`.

## Evidence carried forward

- Router (fine taxonomy, argmax): MASSIVE-test fine accuracy 0.919, challenge-v1 0.890, challenge-v2 0.908; 13 writes on a none/unsupported turn on MASSIVE-test, which thresholds cannot remove, hence mandatory confirmation.
- Extractor + validator on a 50-case holdout written after the validator was frozen: unsafe executable extraction 1/50 (2%) few-shot, 4/50 (8%) zero-shot; the model alone was 36% / 52%. 24/24 unresolved references and 4/4 bulk forgets were withheld/refused. The 1 miss was a comma-joined pair of targets; the rule added afterwards is not counted. The 2% is the number to quote.
- Known cost: the validator over-withholds some legitimate phrasing ("queue up call the electrician for tuesday"); in shadow this is what `safe_but_withheld` measures.
- Known limits: all non-MASSIVE data is author-written; voice transcription noise and real utterances are untested; the extractor may truncate a stored fact (grounded but lossy), which the consent echo-back is meant to catch.

## Removing

Unset `SHADOW_ROUTER_ENABLED`. Nothing else depends on this package; delete `companion_core/shadow_router/`, the `production_handler` bookkeeping and the submit block in `app.py`.
