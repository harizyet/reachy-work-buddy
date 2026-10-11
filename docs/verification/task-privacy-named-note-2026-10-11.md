# Task reply privacy and title-only named-note routing (2026-10-11)

Two production findings from the router deployment ([record](intent-router-deployment-2026-10-11.md#findings)), corrected locally. **Committed, not deployed.** No router change, no new flag, no schema change, no heuristic added to the router.

## 1. Task reply privacy: root cause and fix

**Root cause.** Four legacy handlers in `app.py` (`tasks.capture`, `tasks.complete`, `tasks.search`, `tasks.read`) labelled a reply with `classify_privacy(turn.text)`, a keyword test on the *question*. A question with no sensitive or work keyword ("What are my tasks?") was therefore labelled **public** although the reply listed stored, work-private tasks, and the hub speaks a public reply on a shared speaker. They also ignored the channel ceiling: every open task was listed whatever its sensitivity. The Phase 49 inquiry and the router paths were already work-private and ceiling-checked.

| Handler | Before | Now |
|---|---|---|
| `tasks.read`, `tasks.search` | label from the question; all tasks listed | tasks above the channel ceiling or outside its scope are left out; label is the most restrictive of the question's label, work-private and the sensitivity of every task named; a shared speaker gets the restriction message and no task text |
| `tasks.capture`, `tasks.complete` | label from the question | same floor and the sensitivity of the task created or completed |
| `reminders.read`, `notes.read` | work-private, no filter | reminders and notes above the ceiling are left out; label is the most restrictive of work-private and the records listed; a shared speaker gets the restriction message |
| `tasks.inquiry`, router dispatch | work-private, ceiling-checked | unchanged (tests added) |

Combining labels only ever raises them (`effective_sensitivity`), and `conversation_store.reply_privacy` still carries an earlier sensitive label forward. Ordinary chat keeps its question-based label ("tell me a joke" stays public).

## 2. Title-only named note: root cause and fix

**Root cause.** `record_reference.parse` recognises a named record only with the word "note" or "meeting", or a quoted title. "What did I write in My Task for next week?" has neither, so it was not claimed; the 49E inquiry does not match it; the older list matcher (`is_list_query`) then saw "what ... task ..." and answered with the structured task list.

**Fix.** `record_reference.parse_tentative` proposes a title for the existing retrieval shapes ("what did I write/put/note ... in X", "what's in X", "show/read X", "what does X say"). The route resolves it with the existing authorised `resolve` (same ceiling and scope rules; a restricted record reads as missing): one match is read verbatim through `answer_record_reference`; several matches get the existing ambiguity reply; with none, the "what did I write" form answers the existing not-found reply (it can only mean something written down) and the other shapes go on as before ("what's in the fridge?" is ordinary chat). A list phrase ("show my tasks") is never turned into a record read because a note shares its words, and an action request or mixed request is never a reference. `What are my tasks?` is unchanged. Nothing about the router or its flag changed.

## Verification

* 20 new tests in `tests/test_intent_router.py` (170 total there), run with the router flag on and off and with note processing on and off: legacy replies never public; no sensitive task, reminder or note listed on a private channel; a shared speaker is read nothing by any handler; inquiry and router labels; the exact production question reads the note (and not the tasks) in every state; possessive optional; same-title ambiguity; no-such-note reply; sensitive note and voice never disclose; normal task questions unchanged even when notes are named "Tasks" and "My Task for next week"; actions and mixed requests still refused. Run against the previous source, 17 of them fail and the 4 guards pass, so the tests do exercise the defects.
* Suites on a disposable `pgvector` PostgreSQL (removed afterwards): companion-core and reachy-hub 2,777 passed, 21 skipped, 3 failed (the same three baseline failures: `test_knowledge_index` reconcile, `test_knowledge_retrieval` historical mode, hub `test_robot_voice` spoken command); coding-agent-service 82 passed; lint clean; the four frozen capture-file hashes match, the five freeze test files pass, and nothing under `benchmarks/`, `knowledge/`, `memory/` or `action_boundary.py` changed.

## Limits

A bare "what did I write in X" for something that is not a record now says it found no note or meeting called X instead of listing tasks. A note titled with a list phrase ("Tasks") is not read by "show my tasks"; ask for it with "the note called Tasks".

## 3. SearXNG secret (procedure prepared, nothing rotated)

Root cause of the exposure: the file holds a bare value, which the documentation already said (`export SEARXNG_SECRET_KEY=$(cat ...)`), but I treated it as a `KEY=value` file, printed its first field while diagnosing a failed `source`, and so wrote the value into the session output. Consumers, the file format rules and a rotation procedure that prints no value are in [deployment.md](../deployment.md#the-bundled-searxng-secret-format-consumers-and-rotation). Rotation and the `searxng` container recreate need separate owner approval and have not been done; no service was restarted and no runtime flag was changed by this work.
