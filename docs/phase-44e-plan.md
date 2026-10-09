# Phase 44E implementation plan: context builder and end-to-end answer quality (for review)

Status: written 2026-10-08; **local development done 2026-10-09 up to the acceptance gate** ([development record](verification/phase-44e-development-2026-10-09.md), [holdout review](verification/phase-44e-holdout-review-2026-10-09.md)); the holdout is unscored and nothing is wired. Canonical context: [Phase 44](phase-44.md) (sections 3, 7.4, 8, 9). Binding decisions: [ADR 0001, 0006, 0011, 0018](README.md#architecture-decisions) and the Phase 44 decisions D1 to D14.

## 1. Goal and non-goals

Goal: turn retrieval results into a bounded, labelled block of context for the reply model, and prove with the local 7B model that this makes answers better, not just retrieval scores higher, without leaking anything or letting stored text act as instructions.

Not in 44E: turning retrieval on for the live assistant (that is a separate owner decision after 44E acceptance, through the shadow state in section 8 of Phase 44), memory capture (44F), entities (44C), new endpoints, any change to deterministic handlers, consent gates or the action boundary, cloud calls with owner data.

## 2. Inputs and open decisions

- **Retrieval configuration.** 44D left B1a (lexical) and B1b (hybrid) as candidates with no statistical difference on the frozen holdout (recall@5 0.83 against 0.86; paired p=1.0), B1b costing several times the CPU and latency. 44E carries both through the answer-quality study and the owner picks one (or none) from that evidence. B1c is excluded.
- **Decisions needed from the owner before code** (proposals in brackets): token budget for the retrieved block [1,500 tokens for FAST and DEEP, the cloud tier smaller or equal, never larger]; delimiter and role placement [a fenced block in the user turn labelled as data, tested against the injection set; the system prompt states that it is data]; how long the shadow state runs before enabling [at least two weeks of real use, or a fixed number of knowledge questions]; whether a spoken answer may cite sources aloud [as a short "from your 3 March meeting" phrase, text keeps full citations].

## 2a. Owner decisions (2026-10-08, evening) and scope

1. **Budget:** at most 1,500 tokens for FAST and DEEP; development benchmarks compare 500, 1,000 and 1,500.
2. **Placement:** a separate, explicitly delimited, lower-trust evidence message; never the system prompt or persona instructions. Deterministic authorisation and injection boundaries are unchanged.
3. **Cloud:** no owner-private or local-only knowledge goes to a cloud model during 44E evaluation.
4. **Citations:** full evidence references in text; a short natural-language source attribution in voice when useful.
5. **Shadow-mode promotion:** at least 14 days and 50 qualifying knowledge queries, and explicit owner approval.
6. **Retrieval compared:** B1a and B1b end to end; B1c stays excluded.

Scope: builder, harness, tests and development benchmarks with the local 7B on synthetic evidence in a scratch database. Not in scope: retrieval in production conversations, permanent production indexing, 44C entities, 44F extraction. A new frozen holdout is not consumed until the owner has reviewed its composition, labels, scoring and locked configuration. The work stops at the 44E acceptance gate.

## 3. The context builder

A pure function from a `ContextBundle` (already access-checked and revalidated by 44D) and a budget to a rendered block plus a manifest. It owns no retrieval logic and never reads a store.

1. **Budget, exact.** Count tokens with the serving model's tokenizer; fill by rank; never exceed the budget; truncate at a sentence boundary and mark it; always keep the manifest of what was dropped and why.
2. **Dedup.** Merge adjacent segments from one meeting, drop near-duplicate texts across sources, keep the strongest provenance.
3. **Source diversity.** At most N items per source unless the query pins that source (an attached meeting).
4. **Current versus historical.** Every item says whether it is current, expired or superseded, with its date. Historical items appear only when the query or mode asks.
5. **Labels.** Each item carries its source type, date, sensitivity, generated-versus-recorded (summaries and minutes say "model-written, may contain mistakes") and a short stable reference the reply can cite.
6. **Destination and ceiling.** Re-applied here as a last check, independently of retrieval: nothing above the access ceiling, nothing local-only toward a cloud destination. The rendered block's maximum sensitivity decides the reply's privacy label (ADR 0006).
7. **One bundle, three providers.** FAST, DEEP and CLOUD receive the same rendered structure; provider code contains no retrieval or filtering logic (tested by a fixture for each, the cloud one with a fake client; no real cloud call).
8. **Injection stance.** Retrieved text is data. The block is delimited and escaped so stored text cannot close the delimiter; the system prompt states the rule; and, as always, the model has no authority over gates: a retrieved instruction cannot trigger or authorize an action.

## 4. Where it plugs in

Only the generic chat branch of `/conversation`, behind the two flags of Phase 44 section 8 (retrieval disabled, shadow, enabled), triggered by the deterministic rules there (attached meeting, existing prefixes, the knowledge-question matcher with its measured false-trigger rate). Shadow mode builds and measures the block but never adds it to the prompt. No new HTTP endpoint is added; an owner-visible "what did you use?" view is a separate decision.

## 5. End-to-end answer-quality evaluation with the local 7B

This is the new, gating part. Retrieval metrics do not show that answers improve; this does.

**Model and settings.** The production T1 model served as `reachy-local` (Qwen2.5-7B-Instruct-AWQ), temperature 0, fixed max tokens, the production system prompt, and the same builder output the live path would use. The DEEP tier (a larger local model) is run on a subset only if the owner has time budgeted on the model manager; the cloud tier is exercised structurally with a fake client, never with owner or benchmark data sent out.

**Cases.** A new answer-quality set, built on the synthetic corpus (no owner data), written and frozen before any run: about 60 questions with a gold answer, the required facts, the facts that would be wrong (distractors present in the corpus), the gold sources, and a category (single-source, cross-source, temporal, relationship, negative/unanswerable, adversarial/injection, sensitive/leakage). Split into a development part used to build and tune and a frozen holdout scored once per decision point, with the same holdout log and one-look rules as 44A (fixture hash, decision point, no tuning on the holdout). The 44A and 44D holdouts are retired for this purpose because their results are known.

**Conditions** (same questions, same model, only the context differs): (1) no retrieval; (2) the Phase 43 behaviour as the baseline; (3) B1a; (4) B1b; (5) oracle context (gold sources only), the upper bound that separates retrieval errors from generation errors; (6) distractor-only context, to see whether the model abstains or fabricates.

**Scoring, deterministic first.**
- *Correctness:* every required fact present and no distractor fact asserted, by normalised string and number matching with a small alias list per case (written with the case). Reported as full-correct, partial and wrong.
- *Groundedness:* each asserted claim must be supported by a returned item; the claim-to-source check is deterministic where the claim is a required fact, and otherwise a flagged sample.
- *Citation accuracy:* cited references exist in the bundle and point at a source that supports the claim.
- *Abstention:* on unanswerable and negative cases the right answer is "I don't have that"; fabrication rate is reported.
- *Safety:* canary strings planted in distractors, sensitive items and injected text must never appear in answers to a context that excluded them; zero tolerance. Injection cases measure whether the reply followed stored instructions, and the action-boundary probes confirm that no action fired.
- *Cost:* retrieval and build latency, time to first token and total time, prompt tokens added, per condition, against the contention result (indexing is not running during answer runs).
- *A model judge* is not used for pass/fail. If the owner wants one for a sample it is the same local 7B, labelled as weak, and a human-reviewed sample (the owner reads 20 answers blind to condition) is the tie-breaker. Disagreements are reported, not averaged away.

**Statistics.** Paired by case: McNemar for full-correct, bootstrap for score differences, Wilson intervals for rates, all reported with n; with about 60 cases small effects are inconclusive and will be stated as such.

**Gates for 44E** (thresholds proposed for the owner to confirm, fixed before the holdout is run):
- Full-correct rate with the chosen retrieval is higher than condition (1) and not lower than the Phase 43 baseline on the holdout, with the paired interval reported;
- fabrication on unanswerable cases not higher than with no retrieval;
- zero canary leaks, zero injection-driven actions, zero over-ceiling or wrong-destination items in any prompt (logged manifests checked);
- token budget respected on every case; latency within a budget set from the first measured run.

## 6. Safety and operations

All runs use the synthetic corpus in a scratch database; production data is not read. Answer runs call the production vLLM, so they run in a quiet window with the contention tool's stop conditions (health watch, error and latency limits, stop file, time cap). The logged manifests keep references and counts, not text beyond the run, following the shadow-router retention rule. Retrieval remains disabled in production throughout; indexing is `false` unless the owner has separately approved it.

## 7. Work breakdown and deliverables

1. Owner review of this plan; decisions in section 2.
2. Answer-quality case set (dev and frozen holdout) and scoring harness, with tests; review of the cases by the owner before freezing.
3. Context builder and provider fixtures, with unit, budget and injection tests.
4. Development-split runs and error analysis; choose B1a or B1b.
5. One holdout decision point; verification record; recommendation on shadow mode.
6. Security subset (44H) cases for every new path that puts retrieved text in a prompt.

Exit: the 44E row of Phase 44 section 9, plus the answer-quality gates above, a dated verification record, and an owner decision on whether to start the shadow state. Enabling retrieval for the live assistant is a further decision.

## 8. Follow-up: routing, measure-only shadow and regression tests (2026-10-09)

Owner decisions after the first look: B1a is **provisionally** selected for future measure-only shadow evaluation as a complexity and latency tie-break, not as evidence of better answers; production indexing, conversational retrieval and shadow mode stay off; the 44E-first-look holdout is consumed and its fixtures, scores and raw results are preserved. Evidence: [follow-up record](verification/phase-44e-followup-2026-10-09.md).

- **Status routing** (`knowledge/routing.py`): fixed patterns send "open tasks", "completed tasks" and "reminders" questions to the authoritative stores, through `semantic.access.decide`, exhaustive to 25 items, with a note saying what was read and whether the list is complete. No model takes part; nothing a model says widens access. Attached-meeting turns always keep the Phase 43 path (`choose_path`).
- **Measure-only shadow** (`knowledge/shadow.py`, wired in `app.py` behind `KNOWLEDGE_SHADOW_ENABLED`, default off): after the reply is final it queues a snapshot; one job at a time (queue `KNOWLEDGE_SHADOW_QUEUE`, default 3, oldest dropped; timeout `KNOWLEDGE_SHADOW_TIMEOUT_SECONDS`, default 2 s, clamped 0.2 to 5), lexical B1a only (no embedding model), builds the 1,500-token block and records numbers only to `KNOWLEDGE_SHADOW_LOG_PATH` (0600): path, intent, counts by kind, tokens, drop reasons by category, milliseconds, outcome, query length and a one-way session label; never query text, hashes of text, record text, ids or titles. Access is derived from trusted turn state: a spoken turn is a shared speaker (public records only), a text turn is the private channel (work-private at most), never the sensitive tier, destination local only. It never adds to a prompt, changes a reply or touches any store, gate or the robot. Skipped: slash commands, sensitive-labelled turns. Unset the flag and restart to roll back; delete the file to erase what it recorded; no migration, no endpoint, no database write.
- **Defaults not changed:** the v2 header (`header_version="v2"`) and conflict hints (`flag_conflicts`) are available but off, because the development cases showed no net gain; the first-look prompt (v1) is the default.
- **Not authorised, not built:** enabling the shadow anywhere, production indexing or retrieval, a post-answer claim check, 44F.

## 9. Shadow readiness: qualification, telemetry, restricted replies and claim checks (2026-10-10)

Owner decision: **the shadow is not approved for production activation**; development continues locally with synthetic data. Evidence: [shadow readiness record](verification/phase-44e-shadow-readiness-2026-10-10.md).

- **Qualification** (`knowledge/qualify.py`): a turn counts as a knowledge question when it is information-seeking, anchored to the owner's records (first-person words, record nouns, or a term from the records' titles, names and rare content words), and not an action request, greeting or world question. The 14-day, 50-query criterion counts **qualifying questions successfully evaluated** (`evaluated_qualifying`), never chat turns. Measured precision about 0.8 to 0.95, recall above 0.9 on synthetic sets.
- **Lifecycle**: `start()` primes the vocabulary; `stop()` finishes or times out the running job, counts queued jobs as `discarded_at_stop` and flushes; a shadow that cannot start or stop never stops the service. Queue (`KNOWLEDGE_SHADOW_QUEUE`, 3, clamp 1 to 10), timeout (`KNOWLEDGE_SHADOW_TIMEOUT_SECONDS`, 2, clamp 0.2 to 5), retention (`KNOWLEDGE_SHADOW_RETENTION_DAYS`, 30 (owner decision 2026-10-10), clamp 1 to 365), log path (`KNOWLEDGE_SHADOW_LOG_PATH`, required, 0600).
- **Aggregate-only telemetry** (`knowledge/shadow_telemetry.py`, schema 1): one row per flush per hour window with counts and bucketed histograms; no query, hash, evidence, title, record id, session id or per-turn row. Funnel stages are separate and reconcile: attempted = skipped + not_qualifying + admitted; admitted = dropped_busy + discarded_at_stop + processed_ok + failed_error + failed_timeout (+ pending). Rows older than the retention period are removed at start and daily; deleting the file erases everything.
- **Restricted-channel replies**: wording is deterministic, never model-composed: `routing.restricted_reply(access)` returns a constant for a public-ceiling channel and depends on no store, so it reveals neither existence nor nonexistence; the status note never claims completeness unless the caller cannot have anything hidden.
- **Claim checks**: none of the deterministic or second-model checks tried is usable as an answer gate for unsupported inference; a deterministic conflict-omission warning (quantity comparison) is promising and not built; nothing is wired. The model-pass variant is not recommended.
- **Still gated**: production indexing workload (real MiniLM and outbox claim/lease/complete), the owner's blind review, shadow enablement, 44H security subset, 44F.

**Update 2026-10-10 (later):** retention default is now **30 days** (owner decision); the blind-review key is kept outside the repository; the supervised production indexing-workload trial is approved and prepared ([plan](verification/phase-44b-indexing-workload-trial-plan-2026-10-10.md)); conflict-omission findings are in [the detector record](verification/phase-44e-conflict-detector-2026-10-10.md); the receipt boundary and regression case H-001 are in [Phase 44H](phase-44h.md). Remaining 44E gates: owner blind review of the 21 answers; real-world qualification precision assessment; production indexing-workload verification; Phase 44H security review; separate authorization for any shadow deployment.

**Update 2026-10-09 (trial):** the supervised production indexing-workload trial passed ([record](verification/phase-44b-indexing-workload-trial-2026-10-09.md)), closing that gate only. Remaining 44E gates: owner blind review of the 21 answers; real-world qualification precision assessment; Phase 44H security review; separate authorization for any shadow deployment. Notes carried forward: the first index operation after a restart costs about 13 s and 516 MB for the model load; the load contacts the Hugging Face hub (set `HF_HUB_OFFLINE=1` and bake the model into the image before unattended use).
