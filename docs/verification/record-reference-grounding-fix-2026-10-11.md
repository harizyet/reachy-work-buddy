# Daily-driver grounding defect: named-record references (2026-10-11)

A defect found in production use after Phase 44 closed; not a Phase 44 workstream. Local patch only: **not deployed, no flag changed, no production data touched.**

## 1. Effective production flags (read-only check, 2026-10-11)

Read from `deploy/homelab/.env`, `deploy/homelab/docker-compose.yml`, and `docker inspect` of the running `reachy-homelab-companion-core-1` (container created 2026-10-10 14:56 UTC, started 15:02 UTC):

| Flag | Effective value |
|---|---|
| `KNOWLEDGE_INDEXING_ENABLED` | `true` |
| `KNOWLEDGE_RETRIEVAL_ENABLED` | `true` |
| `KNOWLEDGE_SELECTIVE_SHADOW_ENABLED` | `true` (log path `/data/shadow-router/selective-shadow.jsonl`) |
| `KNOWLEDGE_SELECTIVE_ANSWERING_ENABLED` | not set, and deliberately not passed by Compose |
| `MEMORY_CANDIDATES_ENABLED` / `_CAPTURE_ENABLED` | `true` / `true` |

**The discrepancy is stale text, not a drifting runtime.** The statements "only `KNOWLEDGE_INDEXING_ENABLED=false`" are dated records of earlier states: the 44B deployment (2026-10-08), 47D (2026-10-08), phase-45/47 prose, the opening line of the Phase 48 table (the state when 48 was proposed, before 48A to 48F), and `phase-44e-larger-model-comparison-2026-10-12.md` (a restore check that predates 48D). The authoritative sequence is 48D (indexing on 14:35 UTC), 48E (retrieval on 14:46 UTC) and 48F (shadow on 14:56 UTC), recorded in their own files. Answering remains off: nothing in the running core can reply from the index. Indexing and retrieval do not change any reply; only the measure-only shadow reads them.

## 2. Defect and cause

Production traces and the in-process reproduction are in the investigation report. In short: a note title containing "my tasks" matched the task-list phrase (`tasks.read` answered "You have no open tasks."), and a turn that named a note matched no handler, so the model answered from the owner's own words with invented content and a false source. The 44E classifier (`knowledge/routing.py`) had the same collision, so enabling answering would not have intercepted either turn.

## 3. Fix

[`record_reference.py`](../../services/companion-core/src/companion_core/record_reference.py), wired in [`app.py`](../../services/companion-core/src/companion_core/app.py) and [`knowledge/routing.py`](../../services/companion-core/src/companion_core/knowledge/routing.py):

- An explicit reference (`note/meeting called|named|titled X`, `what did I write in ...`, `in my notes`, `according to my notes/meeting`) is parsed first, only for questions and read requests (an action request or a command prefix is never one). The generic intent matchers then see no text, so no title can steer routing. `what tasks do I have?` is not a reference.
- A read of a named record returns the stored text verbatim with its title and date, no model, cut at 3,000 characters with a notice. Resolution is an exact title match (case and edge punctuation aside, a leading "my/the" tolerated) across notes and finished meetings, under the turn's access rules. A missing record, an unreadable one (over the channel ceiling, e.g. work-private on the spoken channel) and a not-yet-transcribed meeting all get one identical not-found reply; two readable matches are reported as ambiguous.
- Anything needing interpretation (including a grounded question about a record that does resolve) returns the existing 44E wording, "I couldn't establish that from the records I was able to check.", with no model call. No summariser was added; answering from a record waits for the authorised evidence path.
- Backstop in the generic model branch: a reply crediting the owner's notes, meetings, calendar, etc. ("according to / based on / from your ...", "your notes say", "you wrote") is replaced by the same wording when no meeting was attached as evidence. Fixed pattern, sentence-level, plain denials ("I can't see your notes") are left alone.
- The shadow's `classify` no longer files a named-record question under `status`; this changes only what the measure-only shadow counts.

## 4. Verification (local, disposable data, in-process)

[`tests/test_record_reference.py`](../../services/companion-core/tests/test_record_reference.py) (62 cases): the exact regression (empty task store, note "Tasks for next week" whose body is unlike the invented list), missing record, titles made of `reminders`/`alarms`/`tasks`/`today`, restricted and spoken-channel records indistinguishable from missing, ambiguity, meetings, recognition and non-recognition tables, unchanged task/reminder/note-list handlers, the 44E classifier, and the backstop (blocked, left alone, exempt when a meeting is attached). Mocks and in-process only; nothing was exercised against the production database or model.

Full companion-core suite: 1900 passed, 100 skipped, 6 failed; ruff clean. Four failures are the evaluation freeze checks (dev8, dev10, dev12, dev14), all because `knowledge/routing.py` is a hashed file. The other two (`test_knowledge_index::test_reconcile_repairs_a_missing_stale_orphaned_and_expired_index`, `test_knowledge_retrieval::test_historical_mode_reaches_the_prefilter_and_revalidation`) fail identically with this patch stashed, so they predate it and are not investigated here.

## 5. Open items for the owner

- The dev8/dev10/dev12/dev14 `test_the_frozen_files_are_unchanged` tests fail because `knowledge/routing.py` is a hashed file in `dev10_freeze.json`. The change was requested, but updating that manifest is an evaluation-integrity decision, so it was left alone.
- Not verified: whether the production note exists and its store (the production database read was not permitted).
- Not deployed. Deploying needs the usual image build and owner approval.
