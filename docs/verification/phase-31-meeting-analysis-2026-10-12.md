# Phase 31: structured meeting analysis (local development, 2026-10-12)

Scope and design: [phase-31](../phase-31.md). **Nothing is deployed.** No production database, flag, image or Compose file was changed; the Phase 48 frozen files are byte-identical to `HEAD` (`git diff HEAD` over `selective_answer.py`, `selective_shadow.py`, `shadow_telemetry.py`, `retrieval.py`, `search.py`, `revalidate.py`, `qualify.py`, `routing.py`, `answerability_b1/`, `memory/` and `benchmarks/` is empty, and the freeze tests pass). Evidence classes are kept apart below: mock, real PostgreSQL (disposable), real model (local 7B), real speech sidecars. No physical, robot or owner-browser acceptance was run.

## What was built

`companion_core/meeting_analysis/` (models, extraction, store + PostgreSQL store, service, routes), migration `032_meeting_analysis` with `deploy/homelab/rollback-032.sql`, `shared/protocols/meeting_analysis_api.py`, the hub owner-only proxy `reachy_hub/meeting_analysis.py`, analysis entries in `knowledge/sources.py::MeetingAdapter` (and the optional `meeting_analysis` argument of `build_adapters` / `start_indexing`), and a web Analysis tab (`api/meetingAnalysis.ts`, `features/meetings/AnalysisPanel.tsx`). Flag `MEETING_ANALYSIS_ENABLED`, default off. Small related fixes: lower-case sidecar labels (`speaker_0`) now display as "Speaker 1" in core and web.

## Baseline inspection (read-only)

Production holds one meeting: the 758 s phone recording (78 segments, 46 diarization turns, 6 speaker labels, 511 s of exact silence in 3 spans, summary and minutes present). Only counts were read. Findings: the speaker labels are lower-case and were shown raw (fixed); diarization over-segments (6 labels for a short conversation), so speaker labels are never treated as identities; speech is about 247 s, so this recording cannot serve as the acceptance meeting. The 1,419 s test recording was run again through the live sidecars (core worker code, in-memory store): 349 STT segments, 602 diarization turns, 4 speakers, 197 s wall, status complete.

## Defect found by the real recording, and the fix

First real-model run of the first design returned **no items at all**: 15 suggestions rejected as "no evidence", 1 answer unusable. A diagnostic (counts only) showed the model's quotes were real but **spanned several STT fragments**, so a per-segment check rejected 36 of 38 evidence quotes (cited segment correct in 2). The mock tests had used whole-sentence segments and could not show this. Fix: the quote is now located across consecutive segments of the chunk (the model's segment number is a hint), the item records every covered segment id, the start of the first and end of the last, and the first segment's speaker label; more than 8 segments or a quote nowhere in the chunk is rejected. Re-analysis identity is `same_finding` (see the review below), so a different quote extent or wording on another run cannot bring back a dismissed or accepted item. Also added after reading real output: names the model puts in an action's wording that the quote does not contain are removed and noted; actions whose quote has no commitment or request wording are flagged (not dropped).

## Tests

| Evidence | Result |
|---|---|
| Mock, core in-process (`test_meeting_analysis.py`: validator, store state machine, service, adapter, routes via the real app, flag-off 404) | 34 passed |
| Real PostgreSQL 16 + pgvector, disposable container (`test_meeting_analysis_postgres.py`: migration, structure, rollback, concurrency, lease/stale takeover, full flow with the Phase 44 index and authorised retrieval) | 6 passed |
| Existing migration/rollback tests updated for head 032 (notepad, memory candidates, documents, knowledge, knowledge retrieval) | 47 passed, same container |
| Hub, owner session + CSRF + no bearer + real core app in process (`test_meeting_analysis_hub.py`) | 15 passed |
| Web unit (`meeting-analysis.test.tsx`; whole web suite) | 7 passed; 286 passed in total; `tsc --noEmit` clean |
| Full Python suite (`pytest services shared`, run before the last two validator changes; those files were re-run) | 3,281 passed, 31 skipped, 4 failed. The three known baseline failures (`test_knowledge_index` reconcile, `test_knowledge_retrieval` historical mode, `test_robot_voice` spoken command) plus `test_web_client::test_sample_responses_still_match_the_hub` (chat sample: a `document` field), which also fails with this work's tracked changes stashed and is not caused by it |
| Ruff | `ruff check services shared` clean |

## Real local model (Qwen2.5-7B-AWQ via vLLM, temperature 0), real recording

Counts only; item text is in private `0600` files in the session scratchpad for the owner and is not in the repository.

| Run | Store | Result |
|---|---|---|
| Per-segment evidence (first design) | in-memory | 0 items; 15 rejected, 1 unusable answer |
| Span evidence | in-memory | 5 chunks (19,089 characters, 349 segments), about 60 to 70 s wall, about 12,000 prompt and 2,100 to 2,500 completion tokens; 17 to 19 items (about 13 to 14 actions, 1 to 2 decisions, 2 to 4 open questions); every evidence quote verified inside its segment span with correct ids and timestamps; model output varies between runs even at temperature 0 |
| Span evidence | **real PostgreSQL stores** | 19 items; one action confirmed into one task with provenance back to the meeting; the Phase 44 index (hash embedding stand-in, not MiniLM) returned 3 analysis findings and 6 transcript segments of the meeting for an owner query, including the finding itself |

Observed limits (for the owner's review, not claims of usefulness): about half the actions are flagged as lacking commitment wording; speech-to-text errors pass into the items ("data leak" for a data lake); a model-worded item can claim more than its quote supports, which only the owner's reading of the quote beside it can catch. Whether the analysis is useful is the acceptance question and is **not answered by this record**.

## Not done / not claimed

- Real 30 to 60 minute meeting with the owner's review of decisions, actions and retrieval: **open** (the longest real input was 24 minutes, run as a development check).
- Browser (Playwright / owner) check of the Analysis tab: not run. Android: not built. Automatic analysis on completion: deliberately not built.
- Production: migration `032`, a core + hub + coding-agent redeploy, a new Phase 48 cohort boundary, and enabling `MEETING_ANALYSIS_ENABLED` each need the owner's approval; backup first. The real embedding model was not used for retrieval here.
- Concurrent STT/diarization and performance work: left alone, as instructed. Measured: analysis of 24 minutes took about a minute on the existing 7B alongside normal traffic.

## Engineering review (second pass, same day)

Findings and what changed. No new framework, model or scoring workstream; all checks are deterministic code beside Phase 49's.

1. **An exact quote is not proof that the conclusion is supported.** The validator proves the quote is in the transcript at the stated segments. It did not prove the item says what the quote says. Every item now carries `support`, either `stated` or `uncertain`, and the reasons appear in plain words in its notes. `stated` needs (a) wording of the right kind in the quote (agreement for a decision, commitment or request for an action, a question for an open question) and (b) at least 60% of the item's own content words present in the quote. Everything else is `uncertain`, shown as "Check the quote" and indexed as "Possible decision/action/open question". Nothing is dropped for this. Neither value means the item is true; the screen and the docs say so. Known hole: wording and word overlap can both be satisfied by a wrong item (the real run produced one: an action worded as "research and use X" from a quote saying the research was already done and X should be installed, labelled `stated`).
2. **Finding identity.** The first design keyed on kind plus first segment, which merged two different actions in one segment and could change between runs. Now: the unique key is the kind plus the normalised quote (exact duplicates only), and `same_finding` means same kind, overlapping segments, and quotes where one contains the other or shares at least half their words (or wording sharing at least 60%). Two different actions in one segment stay two items; a longer or shorter quote or new wording of one sentence is the same item. Tested in memory and on PostgreSQL.
3. **Transcript corrections and repeated analysis.** `source_changed` used to flag every item whenever any line was edited. It now flags an item only when its own quote is no longer in its own segments as the transcript reads now. Re-analysis refreshes items the owner has not decided (their text, evidence and notes follow the corrected transcript, identity and status kept) and never touches accepted or dismissed ones. Tested in memory and on PostgreSQL.
4. **Python failure #4** (`test_web_client::test_sample_responses_still_match_the_hub`, chat sample gains a `document` field): fails identically in a clean `git worktree` at `HEAD` (modules loaded from the worktree, verified by import paths). It is baseline, from a Phase 50 change, not from this work.
5. **Browser test.** New Playwright spec `clients/web/e2e/analysis.spec.ts` with `e2e/analysis_hub_server.py` (the real hub in front of a real core with analysis on; only the model is scripted, and it makes the mistakes a 7B makes). Desktop: analyse, a sentence the speech-to-text cut in two shown as one quote with the first fragment's time and speaker, a fabricated decision absent, a suggestion marked "Check the quote", the left-out count shown, confirm once gives exactly one task, dismiss, reload keeps state, "Play from" opens the transcript. Mobile: no horizontal overflow. 2 passed. It found one real UI defect, fixed: the Analyse button appeared before the server had said what state the meeting was in.
6. **Diff review.** `git diff HEAD` over the Phase 48 frozen set, `memory/`, `benchmarks/` and `notepad_processing/` is empty. Accepted duplication of Phase 49, deliberately: the accept/finish/receipt flow (about 60 lines) and the two store implementations, because Phase 49's are keyed by note and are deployed and accepted; the runner, hashing, evidence location, instruction filter, first-person rule and time resolution are imported, not copied. `meeting_analysis/extraction.py` imports four underscore-named helpers from `notepad_processing/extraction.py`; renaming them would touch deployed code, so they stay (a follow-up could make them public). Removed unused re-exports. Not integrated: the Phase 47 Brain `derived_from` edge for a task made from a meeting action (the provenance route exists, the Brain edge does not).

### Audit of the real-recording output (single reader, no independent review)

The latest run on the 24-minute recording gave 18 items (13 actions, 4 open questions, 1 decision), 4 `stated` and 14 `uncertain`. Reading each item beside its quote (text stays out of the repository):

- **Factually supported by the quote:** about 6 of 18 (a commitment "I'll work with ... to set up the ingest", a delegated task, two genuine questions, a plan to discuss the architecture next week, and one more with an inexact verb).
- **Not supported though the quote is real:** about 9 of 18: the quote is related talk, a suggestion, or another topic, and the summary adds a conclusion. Eight of those nine are labelled `uncertain`; one is labelled `stated` (the mis-worded action above). So the label filtered most but not all.
- **Duplicates:** none among the 18 (distinct segments and meanings).
- **Missed actions:** 31 sentences with commitment wording; 11 were more than two segments from any cited span. Reading those, about 3 look like real commitments ("I'll try and build it", "Then I'll give you guys access", "I'll see how to get you operational"). The item about the architecture cites a neighbouring request rather than that commitment. So recall is partial.
- **Speech-to-text damage** ("data leak" for a data lake, "Stahub") passes into items; an owner reading the quote can usually see it.

Conclusion: the pipeline is safe as a candidate list (nothing is a task without the owner, every item shows its quote, weak ones are marked), and not yet good enough to be trusted unreviewed. Whether it is useful enough is the owner's judgement on a real meeting.

### Regression after the final validator changes (run on the final tree)

- Python, full suite with the disposable PostgreSQL: 3,287 passed, 31 skipped, 5 failed. The five: the three known baseline failures, `test_web_client` chat sample (baseline, item 4 above), and `reachy-embodiment/tests/test_wake.py::test_natural_pause_joins_the_phrase_and_the_request_into_one_candidate`, a timing flake in a service this work does not touch (failed once, then passed in 5 of 5 reruns, 3 with this work and 2 with it stashed).
- Meeting-analysis tests on the final code: 37 core in-process, 7 PostgreSQL, 15 hub, 8 web unit (287 in the web suite), 2 Playwright. `ruff check services shared` clean, `tsc --noEmit` clean.
- Whole Playwright suite: 130 passed, 4 skipped, 2 failed. `e2e/notepad.spec.ts` (desktop) fails identically with this work stashed (its expected reply wording predates the task-query routing change of 2026-10-11; the spec is stale, not touched here). One `web.spec.ts` mobile layout check failed once in the full run and passed in two reruns of that file (the known intermittent mobile overflow).
- Frozen Phase 48 files, `memory/`, `benchmarks/` and `notepad_processing/`: no diff against `HEAD`.

> Update 2026-10-12 (trial preparation): the retrieval rule described above ("Possible ..." entries for uncertain items, decisions and questions indexed) was narrowed before activation: only an owner-confirmed action is indexed. See [trial preparation](phase-31-trial-preparation-2026-10-12.md).
