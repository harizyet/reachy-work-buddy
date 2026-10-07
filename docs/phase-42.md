# Phase 42: Three-tier model escalation

Status: **started 2026-10-07; Phase A measured, nothing else built.** Decision (proposed): [ADR 0031](adr/0031-three-tier-local-model-escalation.md). Evidence: [meeting corrections benchmark](verification/meeting-corrections-benchmark-2026-10-07.md).

## Stages

| Stage | Work | State | Gate |
|---|---|---|---|
| 42.0 Documents | Roadmap row, this page, ADR 0031 | **Done 2026-10-07** | Owner can redirect scope |
| 42A Swap benchmark | Time 7B unload, 14B load-to-ready, a representative deep job, 14B unload, 7B restore-to-ready | **Done 2026-10-07**: round trip about 3.5 min, see [results](#phase-42a-results) | Timings known before any automation |
| 42B Model manager | Stateful manager (five states) as a host process with a token-protected loopback API and CLI; stable `reachy-local` identity; manual only | **Done 2026-10-07**, see [acceptance](#phase-42b-acceptance) | Restores the 7B after every failure path |
| 42C Explicit Deep Local | Owner-triggered deep review of a meeting from the Android app and the web Meetings view, with a warning, an unavailable banner, an in-app notification and Telegram notices | **Built and deployed 2026-10-07**, see [42C](#phase-42c-deep-local-review) | Workflow validated by the owner |
| 42D Nightly batch | Queue deep jobs; one swap, process all, restore once | Not started | Queue and restore tested |
| 42E Automatic tier routing | Separate FAST/DEEP/CLOUD decision layer trained on graded outcomes | Not started; needs real quality data | Never merged with the capability router |

## Metrics to record

Swap: unload, load-to-ready, restore-to-ready, round trip. Runtime: resident model, load failures, swap count, deep jobs queued, completed and failed, time in tier 2, escalations between tiers. Quality: tier-1 success rate, tier-2 recovery after a tier-1 failure, cloud recovery after tier-2 failure, false escalations, unnecessary cloud use.

## Phase 42A results

Measured 2026-10-07 on the RTX 2000E Ada with the repo's own `scripts/start-vllm.sh` (stop, then start with `--model`), two full round trips, the 7B restored after each. Qwen3-14B-AWQ ran with `max-model-len 8192` and thinking disabled per request.

| Step | Cycle 1 | Cycle 2 |
|---|---|---|
| Unload 7B (VRAM 13.5 GB to 0) | 2.8 s | 1.3 s |
| Load Qwen3-14B-AWQ to ready | 116.6 s | 111.5 s |
| Deep job: 23-case resolver benchmark (F1 0.95, real germanite found) | 11.4 s | 11.6 s |
| Unload 14B | 3.5 s | 3.9 s |
| Restore Qwen2.5-7B to ready | 81.2 s | 81.4 s |
| **Round trip** | **about 3.6 min** | **about 3.4 min** |

What this means for the design:

- **About 3.5 minutes of fixed overhead per swap, during which no local model is available.** The deep job itself took 11 s, so a single-job swap is almost all overhead. Batching and the nightly queue are what make Tier 2 worth it; a one-off "deep review" costs the owner roughly 3.5 minutes of local-model downtime and should say so.
- **Cold and warm loads differ little** (117 s against 112 s), so the file cache is not the bottleneck: engine start and graph capture dominate.
- **The 14B load is about 40 s slower than the 7B restore**, so budget about 2 minutes to get into Tier 2 and 1.5 to get out.
- **Model names are a stability risk.** vLLM serves under the model's own id. Core's local provider is configured with the 7B's name, so a swapped-in 14B would reject core's requests. The manager has to own the tier-to-model-name mapping (or the endpoint must accept a stable alias), which supports ADR 0031 decision 4.
- **Per-model request settings differ** (Qwen3 needs thinking turned off), so they belong to the manager's model profile, not to callers.
- No failure path (forced load failure, restore failure) has been exercised yet; that belongs to 42B.

## Phase 42B acceptance

Built as `services/model-manager` ([README](../services/model-manager/README.md)): 54 automated tests (state machine with injected faults and a fake clock, Docker command assembly, readiness semantics, HTTP API), then the same behaviours on the real GPU on 2026-10-07. Both tiers are served as `reachy-local`; core's local provider now uses that name.

| Criterion | Evidence |
|---|---|
| `activate(T2)` while on T2 is idempotent | Unit test: no runtime call, lease extended only |
| One transition at a time | Unit test: same target joins, conflicting request is refused (HTTP 409) |
| Ready means health plus a real completion, not "container started" | Unit and Docker-layer tests (healthy but wedged, empty answer, exited container) |
| A deep start failure restores the 7B | Real: nonexistent model id, the start retried once, 7B restored (about 110 s) |
| A deep job failure restores the 7B | Real: a failing command (exit 3) through the CLI; also unit tests for exceptions and cancellation |
| A 7B restore failure ends in FAILED without looping | Real: injected readiness failure on every attempt gave exactly 1 + 1 attempts, FAILED, a deep switch refused, then a manual restore recovered |
| A failed first restore attempt is retried | Real: injected once, the retry restored the 7B |
| State reconciles after a manager restart from the host, not a file | Real: SIGKILL while the 14B was loaded; the new manager adopted READY_T2 and then restored |
| Every transition is recorded (model, times, duration, outcome, error) | Unit test and `GET /transitions` |
| **Automatic recovery:** a crashed deep model is retried, then the 7B is loaded | Real: `docker kill` of the loaded 14B was detected by the watchdog and restarted (about 125 s); with the restart also failing it fell back to the 7B by itself within about 70 s and stayed there; the 7B answered on `reachy-local` |
| A real deep job through the manager | Benchmark run via `model_manager run`: 14B result (F1 0.95, real "germanite" found), whole cycle 183 s, no model-specific settings passed by the caller |

Not done: the vLLM sleep-mode experiment (it needs a dev-mode server flag, and the architecture does not depend on it), and manager supervision (a systemd unit): the manager is started by hand. Timings for the retry path add up to a few minutes of local-model downtime; a slow (timed-out) deep start is deliberately not retried.

## Phase 42C: deep local review

Owner request, 2026-10-07: choose the larger local model in the model selection, get a warning that Reachy will be unavailable, a notification when Reachy is available again, and Telegram messages when the standard model has been unloaded and when processing is complete.

How it works:

1. In the Android app (Meetings, open a meeting, **Suggest**) and in the web Meetings view (**Suggest corrections**) the model choice is **Local**, **Deep local** or **Cloud**. Deep local shows a warning first: Reachy will be unavailable for about 6 minutes (load about 2, review, reload about 1.5), and a notification plus a Telegram message will say when it is back. It is disabled with a reason when the model manager is unreachable, not on the fast tier, or a review is already running.
2. Core starts a background job (`POST /meetings/{id}/corrections/deep-review`, then `GET /deep-review/{id}`), asks the model manager for the deep tier, runs the same suggestion pipeline on `reachy-local` (now the 14B), and always asks for the fast tier back. Results are available as soon as the review finishes, before the 7B has finished reloading.
3. **Telegram** (through the existing action receipts and the hub's receipt loop, so each message is sent once): a notice **when the manager reports the standard model unloaded** ("Reachy is unavailable: a deep review of ... is running ... about N minutes"), and a notice when the 7B is serving again ("The deep review of ... is complete: N suggestions ready. Reachy is back online."). A failed review says whether Reachy was briefly unavailable; if the 7B cannot be reloaded the message says Reachy is **offline** and needs manual recovery.
4. **In the apps:** a banner on every screen while Reachy is unavailable; the Android app follows the job in a foreground service so the **"Reachy is available again"** notification arrives even in the background (the web view uses a browser notification when permitted, plus an in-page notice). A review started on one device shows its banner on another.
5. Only one review runs at a time. Chat during a review is answered by the 14B or, if local fails, by the cloud under the owner's routing.

Wiring: the manager runs as a host process (`scripts/start-model-manager.sh --bridge`) listening on the Docker bridge address only, so core reaches it as `host.docker.internal:8090` and the LAN does not. Its token is `deploy/homelab/.env.model-manager`, read by compose as an optional env file for core. Without that file or token the Deep local choice reports "the model manager is not configured".

Limits: jobs are held in memory (a core restart mid-review loses the job; the manager's lease still restores the 7B, but no "online" message is sent); the manager is started by hand and is not supervised by systemd; the deep model is chosen in the manager's config, not in the app; there is no scheduled or nightly queue yet (42D).
