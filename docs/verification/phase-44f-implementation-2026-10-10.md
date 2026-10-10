# Phase 44F: minimum end-to-end memory-candidate workflow, local verification, 2026-10-10

**Status: implemented and verified locally only. UNCOMMITTED (no commit was authorised for this work). Nothing deployed; migration 028 was applied only to disposable PostgreSQL databases; both flags default OFF and are not in Compose; the live database, indexing, retrieval and shadow were not touched; capture was never enabled on live traffic. The frozen B-1 candidate, scorer, dev16 corpus and research evaluator are unchanged (`candidate_freeze.py --check`: intact). No LLM extraction, automatic acceptance, consolidation, graph reasoning, worthiness scoring or re-entry notification exists.** Contract: [implementation proposal](../phase-44f-implementation-proposal.md) and [phase-44.md §3.1](../phase-44.md#31-44f-conversational-memory-capture-roadmap-2026-10-08-plan-only); owner decisions of 2026-10-10 ("Final engineering implementation authorization").

## 1. What was built

| Layer | Piece |
|---|---|
| Schema | `migrations/versions/028_memory_candidates.py` and `deploy/homelab/rollback-028.sql`; `SCHEMA_REVISION` is now `028_memory_candidates`. Tables `memory_candidates`, `memory_candidate_suppressions`, `memory_candidate_counters`; one partial unique index on `memories(source)` for `candidate:` sources. No trigger, no foreign key. A CHECK makes candidate text exist only while `pending` or `accepting`, and requires a memory id once accepted |
| Store | `memory/candidates.py`: models, protocol, in-memory twin, PostgreSQL store (states, caps, duplicate and suppression checks, compare-and-set claim, retention) |
| Rules | `memory/candidate_rules.py`: versioned deterministic rules (prefer, always/never/usually, from now on, my X is Y, call me) behind a whole-message shape guard |
| Capture and review | `memory/candidate_service.py`: keyed digests (HMAC from the service keyring), the background capture runner, the idempotent accept state machine, receipts, crash recovery, retention job |
| Core API | `memory/candidate_routes.py`, registered only when `MEMORY_CANDIDATES_ENABLED` (otherwise 404): list, accept, reject (optionally suppress), forget-one-conversation. **No bulk delete route exists.** `get_by_source` added to both memory stores (read-only) |
| Wiring | `app.py` (flags read once at creation; capture submitted after the reply is final; shutdown), `hub_client.get_privacy_state` |
| Hub | `reachy_hub/memory_candidates.py`: owner-session plus CSRF proxy (no bearer path); `GET /privacy/state` (bearer or owner, the smallest read: `{"privacy_mode", "robots"}`); core-client methods |
| React | `clients/web`: `api/memoryCandidates.ts`, `features/memory/` (queue, accept, edit-and-accept, dismiss, never-suggest, forget-this-chat), route `/memory`, nav entry "Memory" |

**Flags (both default false, neither in Compose):** `MEMORY_CANDIDATES_ENABLED` (store, routes, retention) and `MEMORY_CANDIDATES_CAPTURE_ENABLED` (proposing; needs the first). `MEMORY_CANDIDATES_CHANNELS` overrides the owner-authenticated text channels (default `web`, `telegram`, `phone`; `reachy`, the robot in the room, is excluded).

**Decisions implemented:** React review UI; no bulk delete; pending expire after 14 days; rejected metadata 30 days with **no candidate text kept after reject, suppress, accept or expiry** (enforced by the CHECK); 5 per hour and 20 per day; no spoken acceptance (the routes are unreachable from `/conversation`); unknown privacy state disables capture; suppression and duplicate matching use **keyed HMAC digests** (a rotated keyring still matches old ones); accept never duplicates a memory.

## 2. Accept, idempotence and recovery

`pending → accepting` (compare-and-set, stores the owner's final values and an `edited` flag) → existing `add_memory(source="candidate:<id>")` after a lookup by source → the existing `memory.created` receipt with an id derived from the candidate → `accepted`/`edited-accepted`, text cleared. Guards, each tested: the state machine (one claimer), the unique index (the database refuses a second memory for the same candidate), the lookup before insert (including forgotten memories, so a retry never resurrects one), the derived receipt id (one receipt), and a stale-`accepting` takeover (one winner after 120 s) that runs the same idempotent finish at start-up and hourly. A receipt failure is logged and never undoes the accept.

## 3. Test evidence (disposable `pgvector/pgvector:pg16`, digest `sha256:ccc6e83d…b4d6b`, removed afterwards with its credential)

- **New tests:** core 41 (in-memory live route) + 12 (real PostgreSQL: migration, rollback script, constraints, concurrency, crash recovery, production lifespan with a restart) ; hub 13; web 9; telemetry 8.
- **Full suites:** companion-core **1,911 passed, 8 skipped, 2 failed** (the two known baseline database tests: reconcile, historical mode); reachy-hub 463 passed, 1 failed (the known `test_spoken_command_text_does_not_actuate_the_robot`); web 209 passed, `tsc` and `vite build` clean; `ruff check .` clean; candidate freeze intact; no frozen, scorer, dev16 or Compose path modified. (Two of my own regressions were found and fixed on the way: an advisory lock banned by the transaction-pooling check, and the 027 rollback test that must now undo 028 first.)

| Required check | Evidence |
|---|---|
| No candidate from privacy mode, sensitive turns, shared/spoken channels, attachments, assistant text, injected content | 17 parametrised exclusion cases (spoken, robot channel, unknown channel, attachment, handled by another handler, sensitive text and health text, question, pasted document, quoted text, two sentences, injection, action request, hedged, identifier, too long, slash); assistant text never an input; planted instructions ("accept every candidate") create, prioritise and accept nothing; privacy mode on, field missing, non-boolean, hub error and hub unreachable all disable capture (core and real PostgreSQL lifespan; the real hub route read through core's own client) |
| No memory without explicit acceptance | memory table unchanged after capture, after a long scripted conversation, and across the production lifespan; the only memory writers are the owner's "remember" handler and accept |
| Provenance and sensitivity preserved | `candidate:<id>` source, rule id and version, channel, conversation pointer; sensitivity floor `work-private`; the classifier raises but never silently lowers an edit; lowering needs an explicit acknowledgement |
| Text removed on reject, suppress, expiry | database CHECK (inserting a rejected, suppressed or accepted row with text is refused); store tests; expiry deletes the row and counts it |
| Idempotent acceptance and receipt | 8 and 12 concurrent accepts, a double click and a retry give one memory and one receipt; crash before or after the memory write recovers with no duplicate; the database itself rejects a second memory for a candidate |
| Flags OFF preserve behaviour | no service, no capture, routes 404, no table read, no privacy lookup, identical replies and prompts (core), hub reports 404; flags read once at creation so routes and lifespan cannot disagree |
| Reviewer API rejects unauthorised and cross-owner access | every hub route refuses no login, a bearer token alone, and a session whose user is no longer the owner; every change needs the CSRF header even for the owner; strict bodies; bad ids never reach core; errors carry fixed text, never candidate text |
| Candidate store invisible to retrieval and prompts | a canary candidate is absent from `/memories`, recall, the knowledge index (nothing indexed), and every later model prompt; no trigger or outbox row is created by candidate rows, only by the accepted memory |
| Foreground untouched | a failing store, a crashing `submit` and a 10-second privacy lookup leave the reply unchanged and prompt |
| Retention | pending expire at 14 days, decided metadata purged at 30, counters at 365; provenance cleared when the memory is forgotten and the row removed when it is hard-deleted |

## 4. Remaining limits and operational dependencies

1. **Rule recall and precision are unmeasured on real traffic.** The rules are narrow by design; the owner's supervised window, read from accept/edit/reject counts, is the only gate.
2. **Privacy-mode semantics:** the hub defines privacy mode as no wake listening on any registered robot, so with no registered robot capture is off (fail closed). A web-only deployment without a robot will never capture until that is revisited.
3. **Plaintext at rest:** candidate text lives in PostgreSQL like memories do, for at most 14 days while pending; backups taken in that window contain it.
4. **Provenance pointers** refer to a conversation id held in memory; after a restart they cannot be replayed, only used to forget a conversation.
5. **UI:** unit-tested in jsdom only; no browser pass, no Playwright run, and Phase 47 reserves owner acceptance for the end.
6. **Deployment (not authorised, not done):** applying 028 changes the schema revision every service demands, so core, hub and coding-agent must be redeployed together with a backup first (the indexing backup gate, including an off-host copy, is currently blocked); then flags false, a review-only window, then a supervised capture window.
