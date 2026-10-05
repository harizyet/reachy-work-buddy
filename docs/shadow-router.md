# Shadow semantic router

Status: implemented behind a disabled-by-default flag (2026-10-05). Owner decision: shadow only, no behaviour change.
Evidence and benchmarks live outside this repo in the `inferencing/bench/router` workspace; the numbers below are copied from there and are author-written data, except MASSIVE.

## Contract

- No tool execution from this path. The existing production flow runs unchanged and finishes first.
- After the reply is final, `process_conversation_turn` snapshots plain data into a background task. The task cannot alter the response, consent state, draft state, memory, tasks or robot state; a failure or a busy extractor only increments a counter.
- Order inside the task: semantic router -> (live mode only) few-shot extractor -> deterministic validator -> append one record. In the default `offline` extract mode the live path calls only the router sidecar and records `extraction: pending`; the frozen extractor and validator then run later, offline, over the captured records (`tools/shadow_router_extract.py`). The shadow is therefore causally invisible to the production 7B during the trial. The existing deterministic matchers are not replaced; the record carries the production handler beside the router's route.
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
| `SHADOW_EXTRACT_MODE` | `offline` (default): live path calls only the router; extraction is run later by `tools/shadow_router_extract.py`. `live`: also run the extractor inside the turn (a later integration test) |
| `SHADOW_ROUTER_QUEUE_SIZE` | pending shadow jobs before the oldest is dropped (0 = 16 offline, 3 live) |

It shares the host CPU with the production services; the sidecar is capped at 6 CPUs (`SEMANTIC_ROUTER_CPUS`) and 3 GB with 2 ONNX threads per model (`SEMANTIC_ROUTER_ORT_THREADS`). The first default, 3 threads per model under a 3-CPU cap, was CPU-throttled and missed the router p95 gate; CPU pinning is untested.

## Deployment regression (2026-10-05, after the queue change)

Compose sidecar + Qwen 7B stream + diarization running together, 45 s windows, host otherwise quiet (an unrelated InfluxDB benchmark on the same host had polluted two earlier runs; a run is only valid with load average under 3).

| Phase | Router p50 / p95 (HTTP, ms) | 7B decode tok/s (TTFT p95 ms) | Diarization p95 (s) | Shadow queue |
| --- | --- | --- | --- | --- |
| B: no shadow | - | 41.3 (57) | 0.42 | - |
| D1: realistic cadence, 1 request / 3 s | 45 / 60 | 38.3 (62) | 0.44 | - |
| D2: 0.5 s paced (about 6x realistic) | 51 / 75 | 36.7 (65) | 0.51 | - |
| D3: bursts of 12 turns every 15 s | - | 37.2 (82) | 0.46 | 36 submitted, 9 recorded, 27 `dropped_busy`, 0 errors |
| D4: one turn every 5 s | - | 37.2 (79) | 0.46 | 9 submitted, 9 recorded, 0 dropped, 0 errors |

Router p95 and diarization gates pass and the queue accounts exactly (recorded + dropped = submitted, three jobs kept per burst). The 7B result does not meet every pre-registered gate: decode was 89% to 93% of baseline (D2 at 6x cadence is 89%) and TTFT p95 rose 22 to 25 ms during extraction (gate: 20 ms). That cost comes from the shadow extractor calling the same 7B as production, not from the sidecar. Baseline-to-baseline noise on this host is about 5% to 10%, so treat the 7B figures as an upper bound on a roughly 10% decode and 20 ms TTFT cost while shadow extraction is active.

## Trial procedure

Fixed-size, then removed. Nothing here changes a live reply, so rollback is unsetting the flag.

1. Put `SHADOW_ROUTER_ENABLED=true`, `SHADOW_ROUTER_LOG_TEXT=true`, `SHADOW_ROUTER_MAX_TURNS=500` in `deploy/homelab/.env` (extract mode stays `offline`); `scripts/start-homelab.sh --shadow-router --build`. This rebuilds and recreates companion-core (a brief restart) and starts the sidecar. The 7B is not called by the shadow.
2. Use the assistant normally until the cap is reached (`trial_complete_skipped` starts counting).
3. Immediately set `SHADOW_ROUTER_LOG_TEXT=false` (or `SHADOW_ROUTER_ENABLED=false`) and recreate companion-core; copy the log out of the volume to a local 0600 file.
4. When the 7B is idle: `uv run --package companion-core python tools/shadow_router_extract.py shadow.jsonl --out extractions.jsonl --base-url <local vLLM /v1> --model <model>`. It runs the same frozen extractor and validator one record at a time, never modifies the raw log, and is resumable.
5. `uv run python tools/shadow_router_grade.py sheet shadow.jsonl --out sheet.jsonl`: every disagreement plus a random sample of agreements, shuffled, utterance only.
6. Label the sheet blind (before looking at any router, validator or production output): `gold_route`, `executable`, `gold_args`.
7. `uv run python tools/shadow_router_report.py shadow.jsonl --extractions extractions.jsonl --labels labels.jsonl`: reports `unsafe_would_execute` and `safe_but_withheld` per stratum (disagreements are all graded; the agreement sample is random, so do not pool the strata), beside `dropped_busy`, `withheld`, `would_execute`, `bulk_refused`.
8. Save the results, then destroy every recorded file (owner policy, 2026-10-05: recorded files are destroyed once evaluation and testing are complete):
   1. `uv run python tools/shadow_router_report.py ... > report.txt`, then `uv run python tools/shadow_router_grade.py purge shadow.jsonl --labels labels.jsonl --aggregates aggregates.json --extractions extractions.jsonl` (scrubs text, hashes, arguments and targets; writes de-identified aggregates).
   2. `uv run python tools/shadow_router_grade.py destroy shadow.jsonl extractions.jsonl sheet.jsonl labels.jsonl --aggregates aggregates.json`: overwrites each file with zeros, deletes it and verifies it is gone. It refuses to run until the aggregates exist.
   3. Destroy the original in the volume: `docker exec reachy-homelab-companion-core-1 shred -u -z /data/shadow-router/shadow.jsonl`, and confirm with `docker exec reachy-homelab-companion-core-1 ls /data/shadow-router`.
   4. Remove the `SHADOW_*` lines from `deploy/homelab/.env` and recreate companion-core.
9. Do not change a live handler from the trial's examples until enough real traffic has accumulated to judge them.

## Production impact in offline mode (2026-10-05)

Same setup as above (sidecar, 7B stream, diarization), run against the homelab vLLM; extraction offline, so the shadow's only live effect is the router call. TTFT p95 returns to baseline (59 to 62 ms against 54 and 61 ms for the two bracketing baselines, gate +20 ms). 7B decode in the shadow phases (37.5 to 40.4 tok/s) sits between the two baselines (42.7 before, 38.1 after); the host drifts about 10% over a run, so effects under that size cannot be resolved. Router p95 over larger samples: 67 and 83 ms at realistic cadence, 90 ms at 0.5 s paced (n=120); one earlier 136 ms reading came from a 15-request window with a single slow outlier. Diarization p95 0.43 to 0.52 s (baseline 0.42 to 0.43). Burst accounting stayed exact (36 submitted, 9 recorded, 27 dropped).

## Retention

Recorded turns exist only for the evaluation window. Raw log, extraction results, blind sheet and labels are all destroyed when grading is finished (procedure step 8). What survives is `aggregates.json` and the saved report: counts and per-item gold route / executable flags, with no utterance text, no hashes, no arguments and no resolved targets. Limits to know: overwriting a file does not reach filesystem snapshots, backups, or copy-on-write/SSD remapping, so no copy of these files should be placed in any backed-up location, and any extra copy you make (for example when copying the log out of the volume) must be listed and destroyed too. The log lives only in the `shadow-router` volume and in the working copies you make from it.

## Counters

`would_execute`, `would_execute_write`, `withheld` (with `withheld_reason:*`), `bulk_refused`, `dropped_busy` (jobs dropped from the bounded queue), `trial_complete_skipped` (turns refused after the cap), `shadow_error` (an unexpected exception inside the shadow task), `router_error`, `extractor_error` are observable per process, and mean different things when judging coverage; the turn cap counts accepted inputs, not completed records, so contention cannot stretch the trial; the report recomputes the outcome counts from the records. `unsafe_would_execute` (a write the validator would let through that is not what the user justified) and `safe_but_withheld` (a legitimate request the validator would have turned into a question) need a person's grade per record; use `tools/shadow_router_report.py --labels`.

## Evidence carried forward

- Router (fine taxonomy, argmax): MASSIVE-test fine accuracy 0.919, challenge-v1 0.890, challenge-v2 0.908; 13 writes on a none/unsupported turn on MASSIVE-test, which thresholds cannot remove, hence mandatory confirmation.
- Extractor + validator on a 50-case holdout written after the validator was frozen: unsafe executable extraction 1/50 (2%) few-shot, 4/50 (8%) zero-shot; the model alone was 36% / 52%. 24/24 unresolved references and 4/4 bulk forgets were withheld/refused. The 1 miss was a comma-joined pair of targets; the rule added afterwards is not counted. The 2% is the number to quote.
- Known cost: the validator over-withholds some legitimate phrasing ("queue up call the electrician for tuesday"); in shadow this is what `safe_but_withheld` measures.
- Known limits: all non-MASSIVE data is author-written; voice transcription noise and real utterances are untested; the extractor may truncate a stored fact (grounded but lossy), which the consent echo-back is meant to catch.

## Removing

Unset `SHADOW_ROUTER_ENABLED`. Nothing else depends on this package; delete `companion_core/shadow_router/`, the `production_handler` bookkeeping and the submit block in `app.py`.
