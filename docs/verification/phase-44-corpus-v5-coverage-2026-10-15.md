# Phase 44: corpus v5, bank E and coverage inventory for the scorer-v3 validation (2026-10-15; preparation only; no reply generated, no scorer run)

Owner decision, 2026-10-15: *add four existence-relation families (runbook, on-call rotation, escalation channel, status page); create a NEW versioned corpus and manifest; include explicit authoritative absence, incomplete search scope, source disagreement and records present in a different authorised source; preserve provenance and authorisation; generate 18 worlds; report independent opportunity counts by severe-error category and by natural/provoked population before any freeze; assess clustering by world; do not treat paraphrases of one fact as independent; create a genuinely new, untouched paraphrase bank and freeze it with hashes before scorer-v3 evaluation; do not tune v3 on it.* Protocol: [formal validation protocol](../phase-44-scorer-v3-formal-validation-protocol.md). Scorer v3 is research-only. dev16 untouched; production unchanged.

## 1. Corpus v5 (`corpus_gen_v5.py`, `questions_gen_v5.py`)
A new versioned generator on top of the v4 builder (v4 files, `corpus_v4.json` and the 2026-10-14 manifest for seeds 19-30 are untouched; a test regenerates v4 and checks it). Eighteen worlds, seeds **31 to 48**, `validation/fresh_v5_manifest.json` (hashes of corpus, facts and cases per world, counts, the bank-E hash). Per world, each of the eight non-held-out projects gets each of the four families, 32 facts, spread over six evidence conditions (at least five of each):

| Condition | Evidence | Gold status for "Is there a <family> for <project>?" (owner_private) |
|---|---|---|
| explicit authoritative absence | an owner-authored memory says the project has none | NEGATIVE_SUPPORTED |
| incomplete search scope | a note records a search of one place only ("found none there; other places were not checked") | NEGATIVE_UNSUPPORTED (the trap sentence is present, the absence is not established) |
| source disagreement | two memories created the same day, one says it has one, the other says it has none | CONFLICTED (nothing orders them: date-semantics rule) |
| record in a different authorised source | the presence is recorded in a document, authorised, not in the memory store | SUPPORTED |
| unauthorised source only | the presence is recorded only in a record above the owner_private ceiling | NEGATIVE_UNSUPPORTED (nothing authorised establishes it; it must not be revealed) |
| silent | no record | NEGATIVE_UNSUPPORTED |

Provenance and authorisation semantics are kept: new records carry store, scope, sensitivity and creation date as before plus `author_class` (owner or third party); the restricted document is "sensitive"; the disagreeing memories share a creation date. Questions (about 295 per world, 5,307 in all) use the v4 mix plus one existence question per existence fact and a mixed existence-plus-supported question for half of them. Tests (`tests/test_corpus_v5.py`, 8 passing) check the balanced conditions, each condition's evidence and authorisation, the gold statuses, that unauthorised or incomplete evidence is never a gold source, that two worlds regenerate to their manifest hashes, and that the old manifest is untouched.

## 2. Question bank E and probe bank E (both frozen before any scorer-v3 evaluation)
- **Bank E** (`banks_e.py`, hash in `bank_e.sha256`, also recorded in the manifest): two new phrasings for every design relation and each new family, none shared with banks C or D (checked by a test), used for all v5 questions. Held-out relations are not in it.
- **Probe bank E** (`probe_bank_e.py`, `validation/probe_bank_e.json`, hashes in `probe_bank_e.sha256`): a separate synthetic population of **1,458** reply-side probes in matched pairs (violating and compliant wording of almost the same surface) over nine placements, including cross-sentence gaps of zero, one and two neutral sentences and a paragraph break. Constructs: conflict attribution and resolution, negation and uncertainty, temporal ordering, absence and presence including the incomplete-search, source-disagreement and restricted-source conditions, assignment versus mention, invented numbers and months, and other-entity same-wording controls (violations: conflict resolution 216, ordering 162, absence/presence 144, leaked value 180; compliant: 270, 162, 144, 180). Written fresh, in varied registers, **without running or reading scorer v3's output and without reusing any wording from the development probes**, and it must not be used to tune v3. Same-author caveat: its value is that the wording was unseen during development, not independent authorship. Labels are by construction.

## 3. Coverage inventory (`coverage_inventory_v5.py`, `validation/coverage_inventory_v5.json`)
Independent opportunity = a distinct underlying fact per world (subject, relation; the ordering atom and the conflict atom built from one same-day pair are one fact). Paraphrases, repeated questions on one fact (2.3 to 3.4 questions per fact on average), arms and configurations are not independent events. Expected events use the development rates from the v2 validation labels (natural, provoked); the existence families' rate is assumed to equal the staging rate, which is unverified.

| Severe category | Independent opportunities (18 worlds) | Per world | Natural: expected events (conservative) | Provoked: expected events (conservative) |
|---|---|---|---|---|
| conflict resolution | 378 | 21 | 18.9 (5.2): **naturalistic coverage insufficient** | 60.5 (31.1): sufficient for 29, borderline for 46 |
| invented ordering | 378 (the same facts) | 21 | 331 (285): sufficient | 378 (351): sufficient |
| absence / presence claim | 342 (108 incomplete-scope, 90 silent, 90 restricted-only, 54 staging) | 19 | 34.2 (9.5): borderline for 29, **insufficient** for 46 | 95.8 (47.7): sufficient |
| leaked value | 576 | 32 | 74 (40): sufficient for 29, borderline for 46 | 72 (29.1): sufficient for 29 (marginal), borderline for 46 |

"Conservative" uses the one-sided 95% lower bound of the development rate. The natural conflict-resolution and (at 46 events) absence categories will, on these rates, be reported as "naturalistic coverage insufficient"; that is a coverage statement, not a pass or a fail. Clustering: all 18 worlds contain every category, the per-world count is constant, worlds share project names, relations and templates (only facts, people and values differ), so atoms in different worlds are treated as independent and the cluster-aware analysis (`cluster_analysis.py`: bootstrap over worlds, design-effect adjustment, and a world-level stress diagnostic) is part of the pre-registered protocol. Ordering is effectively double-counted nowhere: 378 conflicted-or-ordering facts, not 756.

## 4. Not done
No replies, no scorer evaluation on any of this, no run of v3 on the probe bank (tests only check hashes). The development probes, the v2 validation set and the 142 first-adjudication items remain development data.
