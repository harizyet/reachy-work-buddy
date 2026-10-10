# Phase 44 closure report (engineering), 2026-10-10

**Status: PHASE 44 ENGINEERING COMPLETE for the local development milestone (verified from a fresh clone 2026-10-10; engineering complete does not mean deployed); nothing in Phase 44 beyond the earlier deployments (migrations 026 and 027, the 44H boundary, the one-note indexing trial) is deployed or active. All new flags are OFF and absent from Compose. The 44F code and the telemetry hardening are committed and pushed (owner-approved closure). No further Phase 44 subphases or research gates are created by this report.** Evidence: the [44E integration](verification/phase-44e-selective-integration-2026-10-10.md), [shadow](verification/phase-44e-selective-shadow-2026-10-10.md) and [44F](verification/phase-44f-implementation-2026-10-10.md) records, the [deployment-readiness proposal](phase-44-deployment-readiness-proposal.md) and [telemetry policy](phase-44e-selective-shadow-telemetry-policy.md).

## 1. Engineering complete

| Requirement | State |
|---|---|
| 44A contracts, access model, schema, retrieval-time source revalidation | built, deployed (026), tested |
| 44B unified index, transactional outbox, indexing worker, reconciliation | built, deployed (027) with indexing OFF; the production indexing-workload trial passed (one note, 2026-10-09) |
| 44D authorised retrieval (B1a lexical) | built and benchmarked; zero exposure on the frozen holdout; now called by the answerer and shadow only when their flags are on |
| 44E context builder, labelled and bounded evidence, injection-safe rendering | built; used by the measure-only shadow |
| 44E deterministic cited answering integrated into the conversation route (frozen B-1 untouched, separate adapter, both flags default OFF, fixed failure reply with no model fallback, zero-evidence wording, privacy-ceiling and citation verification) | committed (`b34d366`, `26b16f0`) |
| 44E selective shadow: aggregate-only routing and outcome counters, bounded, fail-safe, with hardened telemetry (one row per hour merged across flushes and restarts, atomic writes, retention, small-cell suppression in the report/export command) | implemented and tested; the hardening is committed |
| 44F minimum workflow: deterministic candidates, review API, hub proxy, React queue, receipts, exclusions, retention, idempotent accept, crash recovery, migration 028 with rollback | implemented, verified and pushed (not deployed) |
| 44H unclaimed-action boundary | deployed 2026-10-12; preserved in every new path (regression-tested) |
| 44H security regression suites (planted instructions, restricted-record invisibility, citation validity, flag rollback) for every new path | in place |

## 2. Deferred by explicit decision

44C entities and relationships; 44G conflict/`superseded_by` classification and Ossie import/export; model-written phrasing (I-3) and any model-based candidate extractor; 44F optional mechanisms (worthiness, placement, connection links, curiosity, re-entry); bulk deletion of candidates (v1 has none; an ADR 0011 addendum would be needed); a narrower refusal safeguard for record-dependent untyped questions (only descriptive telemetry exists; to be proposed after representative routing evidence); the broader answer/action receipt boundary for claims inside model answers (proposal only); scorer research (stopped).

## 3. Operationally blocked

| Blocker | What is needed |
|---|---|
| Production indexing/backfill of the owner's records | a verified **off-host** backup and an isolated restore (the backup programme is paused and the NAS offers no usable transfer path), a re-taken memory baseline (host available memory read 3.4 GB on 2026-10-10 against 7.7 GB at the trial minimum), a measured bulk-load contention run, a rehearsed rollback, then the derived connection, memory and latency ceilings |
| Retrieval, selective-answering and shadow activation | an indexed corpus of real records; a shadow window of real routing evidence; owner approval of each step in the [proposed gate](verification/phase-44e-selective-integration-2026-10-10.md#4-proposed-controlled-deployment-gate-for-owner-review-nothing-here-is-authorised) |
| Deploying migration 028 and 44F | owner approval, a backup (see above), a coordinated redeploy of core, hub and coding-agent (the schema revision is demanded by every service), flags false, then a review-only window and a supervised capture window |
| 44F in use | privacy mode is defined by an armed robot, so a web-only deployment never captures; the React page needs the owner's browser acceptance (reserved to the end of Phase 47) |

## 4. Research acceptance outstanding

The dev16 one-shot acceptance of the deterministic path (not frozen, not run; the research track is paused); an independent second reviewer (reviewer B unassigned, so no independent-validation claim and no agreement figure); criterion 6 adjudication; criteria 7 to 9 need at least 29 independent facts each and dev15 offers 16, 3 and 9; B-1 coverage and correctness on real records and unseen phrasing; the owner's live qualification precision assessment and the 44E acceptance decision. None of the engineering milestones above is evidence for these.

## 5. Final verification (fresh clone of the pushed closure commit, disposable PostgreSQL)

Migration 028, `rollback-028.sql` and the 027 rollback (both script and Alembic downgrade) verified; 243 security and integration tests passed; full suites: companion-core 1,911 passed with only the 2 known baseline failures, reachy-hub 463 passed with only the 1 known baseline failure, web 209 passed with `tsc` and the production build clean; `ruff` clean; candidate freeze intact; the frozen B-1 candidate manifest (`b095e9be…`), evaluator (`d364af6b…`), scorer (`6bfb790e…`), criterion-6 rules (`9141ed6d…`), dev16 cases, bank D and every acceptance artifact are byte-identical to the verified freeze baseline `9fa658f`. No new failure, security or data-integrity finding appeared.
