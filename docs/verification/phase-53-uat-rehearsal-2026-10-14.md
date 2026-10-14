# Phase 53 UAT rehearsal (2026-10-14)

A browser rehearsal of the owner's acceptance on a **disposable stack**, before the production gate. Nothing was merged, deployed, migrated on the homelab database or enabled. Not the owner's acceptance: the meeting is the repository's development recording and the deck was written for the earlier trial (so nothing here measures accuracy, and nothing was tuned to that deck).

**Stack.** Real Chromium (Playwright) signed in as the owner on a real in-process hub in front of a real companion-core (`clients/web/e2e/multimodal_hub_server.py`), the production web build, the real document library service with a disposable MinerU worker container, the live local 7B, a disposable PostgreSQL (`pgvector`) for the Phase 53 and library stores, the real 23.6-minute transcript (349 segments). Scripts: `clients/web/e2e/multimodal-rehearsal-attach-to-qa.mjs` and `…-restart.mjs`. Afterwards the server, both containers, the worker volume and the scratch data were removed; the 11 homelab services were never touched.

## 1. Walk-through results

| Step | Observed |
|---|---|
| Attach | a `.pptx` was then refused (formats were widened afterwards, see [document types](phase-53-document-types-2026-10-14.md)); the PDF uploaded and attaches from the meeting, shows Ready, 10 pages |
| Estimate | progress text appeared at once ("waiting its turn · 0 s…"); 21 windows done in 28.5 s |
| Presentation | 21 windows: 5 boxed cards (High or Medium), 2 one-line Low hints, 13 "No confident slide association"; summary line "6 of 21 parts have a confident page (high 4, medium 2); 2 more have only a low-certainty hint and 13 have none, which is a valid result" |
| Source navigation | Details opens the reason, shared words, the model's comment labelled model-written, the caveat and a page thumbnail (1 image); **Open the page** lands in the extraction inspector at page 2 of 10 with the page picture; the transcript citation in an answer switches to the transcript tab |
| Corrections | Confirm on one card and "Not about a slide" on another survive a full reload (`Confirmed by you` 1, "marked by you" 1) |
| Combined Q&A | works after defect 1 below; 2.3 s; labelled part, transcript citations with timestamps and speaker, a page link `#/documents/<id>?page=6`, "Reachy's estimate, not proof of what was shown", caveats, class and model shown. The 7B put everything in one "inference" part (its choice; the citations carry the separation) |
| Analysis | 74.5 s; headings Actions to review, Decisions, Open questions, Discussion points |
| Gates in the browser | the only mutating requests were login, one ask and the analysis start(s); **0** accept/dismiss requests, **0** tasks after analysis, `localStorage` holds no keys |
| Incidental console messages | a 401 on the sign-in screen (expected) and a 404 for the meeting's audio (the fixture meeting has no audio file) |

## 2. Real defects found and the smallest fixes

1. **A valid model answer was discarded when the model kept writing.** The 7B returned a good JSON object and then a stray string and a second object; the parser took text from the first brace to the last, so the question failed with "I couldn't produce an answer I could check" every time, and the same weakness explains the earlier unreadable analysis chunk. *Fix:* all three Phase 53 parsers read the first complete JSON object (`first_json_object`); Phase 31's frozen parser is untouched. Test added.
2. **After a restart a run left "processing" waited out its 15-minute lease.** *Fix:* the runner's startup queues such runs again (`requeue_interrupted`, one runner per process; both stores). Rehearsed with a real kill -9 during a stalled analysis: after the restart the run was finished in 74.6 s, the open page recovered without a reload, and no duplicate findings or tasks appeared. Tests added (mock and the PostgreSQL store is covered by the flow).
3. **A Low estimate was used as if it were a result** (as context for the analysis, as a link in an answer, as "this page was discussed"). *Fix:* a single rule (`counts_as_discussed`): only the owner's valid decision, or a current High or Medium estimate, counts; a Low estimate is shown dimly and is relied on only after the owner confirms it.
4. **"No page" could mean "nothing fits" or "the model's answer was unusable".** *Fix:* such windows are stored as `unchecked` (migration 034 amended; it has not been applied anywhere), shown as "Not checked: the model's answer for this part could not be used", and counted in the run's partial result.
5. **An analysis with unreadable chunks looked complete.** *Fix:* the run records chunks read and failed; the overview returns `partial: {missing, of}` and both runs show a "Partial result: N of M … Run it again to retry those parts" banner. If nothing at all is usable the run fails (fixed code) instead.
6. **A double click sent two analysis requests** (the server correctly made one run). *Fix:* the button ignores a second click for 1.5 s; verified in the browser (1 request).
7. **No progress and a silent connection loss.** *Fix:* elapsed time, what to expect and "you can leave this page" while a run works; a "Can't reach Reachy right now" note when polling fails, keeping what was on screen.
8. A card seemed to apply to the whole transcript from its first line. *Fix:* it states the transcript part it covers ("this part of the transcript, 0:00–1:15").

## 3. The Ookla mismatch

**Earlier claim corrected:** the trial record said the Ookla slide was missed because speech-to-text spelled the name differently. In the real transcript "Ookla" is spelled correctly four times, including inside the window that was reported as having no page; the variants ("Okla", "Ookar", "Ooklar", "OCLR") occur in other windows, none of which is about the Ookla slide.

What actually happened, reproduced on the real MinerU text and the live model: the window has the Ookla slide as its clear lexical leader (score 37.6 against 12.5, 14 distinctive shared words), so the candidate selection was right. The model's decision flipped between runs and prompt contexts: with the text of the following window attached it declined ("about Stahub app telemetry… not on any slide"), without it and in the rehearsal run it chose the Ookla slide at High. The window is a mixed one (about 75 s covering app telemetry and then Ookla logs). Declining there is within the contract, and the system does not force a match. A prompt sentence telling the model to ignore the neighbouring context was tried on that single case and did not change the answer, so it was not kept.

**Can the existing semantic retrieval help?** The existing local embedding model (`rag/embeddings`, MiniLM, already cached on the host and loaded by the knowledge index) was probed on all 21 windows against the 10 pages, read-only and without storing anything. It ranked the same page first as the lexical score in 12 of 21 windows and a different page in 9. Its high-similarity cases (cosine ≥ 0.5) were all windows the lexical score already led with; the disagreements were low-similarity (≤ 0.4) windows where it drifted to the title or last slides for planning talk. It rescued no window the lexical score missed, loading it took 16 s cold, and it would add a ~90 MB model to the alignment path. **Conclusion: not adopted.** There is no demonstrated need; a fuzzy spelling rule was likewise not added because the one window it would affect is not about that slide. If real decks show paraphrase misses, an embedding similarity could be used to *admit extra candidates* (never to raise certainty) behind the same flag, using the existing embedder and no new service; this is recorded as an option, not built.

## 4. Partial results

Both runs now present partial results as such (defect 5, 4). Unit tests: an unusable answer for one window gives an `unchecked` window and `partial {missing: 1, of: 2}`; all windows unusable fails the run; an unreadable analysis chunk gives `partial` with the readable chunks' findings kept and no task created. Web tests check the banners and the "Not checked" wording.

## 5. The long analysis operation

| Aspect | Result |
|---|---|
| Progress | elapsed seconds and expectation shown; "waiting its turn" vs "working"; the page polls every 2.5 s |
| Duration | 74–103 s on the real transcript (6 model calls) |
| Repeated requests | double click: 1 request; 6 simultaneous server requests: one run; an identical finished request is not redone; force starts a new run whose findings merge without duplicates |
| Timeout | the run limit (30 minutes) ends in `timeout`, a fixed message, and Retry; tested by forcing a 50 ms limit with a stalled model, then retrying to success |
| Restart | defect 2; rehearsed with a real process kill; the page picked the result up without reload |
| Hub unreachable | note shown; nothing lost; the job continues in core |
| Reload mid-run | state comes from the server, so the page shows the same progress |

## 6. Confirmation and privacy gates

All intact and re-tested after every change: nothing becomes a task without the owner's confirm request (0 accept calls in the browser, 0 tasks; the mock suite creates a task exactly once on confirm); a decision/question/action still needs a verified transcript quote and a disagreement both quotes; instruction-like text in slides, the transcript, comments and answers is still rejected; the hub still sets the ceiling and overwrites a browser-supplied one; a source the caller cannot read is still a single 404 with no title, count or run state; sensitivity is still the stricter of the sources; deleting a document or meeting still removes derived data (PostgreSQL tests re-run with the amended migration); no index, memory or Phase 31/44/48/50F path is touched. The Low-estimate change only *reduces* what is relied on.

## 7. Verification numbers after the fixes

Phase 53 core (mock) 72 passed; disposable PostgreSQL 7 + the older migration chain; hub proxy 4; web 349 passed with `tsc` clean; ruff clean; the full core and hub suites 3,160 passed, 155 skipped, **2 failed: the same two known database-dependent core tests** that fail on a clean tree.

## 8. Still not done

The owner's own deck and meeting; Android; a real-conversation load test of the shared 7B; the 30–60 minute meeting; production migration, activation and rollback on the homelab (not authorised).
