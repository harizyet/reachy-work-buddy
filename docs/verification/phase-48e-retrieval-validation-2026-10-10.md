# Phase 48E: retrieval-only validation, 2026-10-10

**Status: `KNOWLEDGE_RETRIEVAL_ENABLED=true` in production (14:46 UTC); selective answering and selective shadow are OFF and unset. Retrieval was evaluated independently of generation on a frozen case set; nothing was tuned. Result: no restricted, forgotten, expired, deleted or cross-scope leakage in any run; recall@5 100% on every positive set after reconciliation. Stopped here; 48F (selective shadow) needs the owner's approval.**

## 1. What was enabled, and what it changes

`KNOWLEDGE_RETRIEVAL_ENABLED=true` (added to Compose as a default-false pass-through; `.env`; core-only recreate at 14:46:19 UTC). On its own it changes **no reply**: only the cited answerer and the selective shadow read it, and each needs its own flag, which Compose does not pass. Observed: two ordinary conversation probes after the change answered as before (the generic model, including "I don't have access to your notes"), the core log has no selective-answering line, chat latency p50 0.355 s and p95 0.367 s (baseline 0.36 / 0.69 s), swap in/out 0, no restart. The retrieval library itself was exercised by the harness below, read-only.

## 2. Method

- **Harness:** `tools/knowledge_retrieval_validate.py` runs the production configuration (**B1a lexical**, `limit` 10, the one the answerer would use) with trusted `AccessContext`s (owner private, owner with a sensitive ceiling, shared speaker, scoped project callers). It writes nothing. For every returned item it re-checks the authoritative store now: sensitivity within the ceiling, scope allowed, source visible (not forgotten, expired, deleted or cancelled), the cited part present (the citation resolves), and generated summaries and minutes labelled `model_generated`.
- **Frozen before the first run, never edited, run once each, no retrieval tuning:** production real-owner set (35 cases, authored from the real notes and the one meeting; the file and the queries stay outside the repository in a 0700 directory because they paraphrase private content; sha256 `25155fc4c54d8adc4ff2227c68df43073e04daad3a52b953b1592fb86fc66c70`); synthetic sets committed here: [before mutation](phase-48e-cases/synthetic-before-mutation.json) (39 cases, sha256 `0d4e90dc996a6470dab6e8e1bc3e3d1d7822b5fc747f4c9f6792a5fbf3948ebf`) and [after mutation](phase-48e-cases/synthetic-after-mutation.json) (13 cases, `4674bc00436ae9a55cbcb5e545906176a0c7af68a792de5d5ca2eb8b134e7c39`).
- **Why two parts.** Production holds 3 notes, 1 meeting and 1 forgotten memory: no sensitive, scoped, conflicting, expiring or deletable records, and I would not create them there. So production tests the real corpus (read-only), and the restricted, scoped, conflict, expiry, deletion and stale-index behaviour is tested on a **restored copy of the 48D dump** (internal network, removed) with clearly labelled synthetic records (ids `syn-*`) indexed by the real worker, then mutated behind the index.
- **Metric definitions.** Recall@k: any expected source in the top k (source level; for cases with two expected sources, all must appear). Precision@5: share of the top 5 that come from an expected source. Leakage: any returned item that violates the per-item checks above or appears in a case's `forbid` list.

## 3. Results

| Set | Cases | Positive cases | Recall@1 | Recall@3 | Recall@5 | Mean precision@5 | Leakage (restricted / forgotten, expired, deleted / cross-scope / unresolved citation) |
|---|---|---|---|---|---|---|---|
| Production, real owner data | 35 | 20 | 19/20 (95%) | 20/20 | 20/20 | 0.78 | 0 / 0 / 0 / 0 |
| Synthetic, before mutation | 39 | 25 | 24/25 (96%) | 25/25 | 25/25 | 0.63 | 0 / 0 / 0 / 0 |
| Synthetic, after mutation, **index left stale** | 13 | 4 | 3/4 | 3/4 | 3/4 | n/a | 0 / 0 / 0 / 0 |
| Synthetic, after mutation, reconciled | 13 | 4 | 3/4 | 4/4 | 4/4 | n/a | 0 / 0 / 0 / 0 |

(The two "recall@1" misses are ranks 3 and 2, never absences: the production accepted-correction case M07 ranked the corrected meeting line third; the synthetic rescope control V0h ranked second.)

**Zero leakage in 100 case runs** (35 + 39 + 13 + 13), including: a shared speaker asking for each work-private note and meeting (0 items), the sensitive memory and note at an ordinary private ceiling (0 items) and at a sensitive ceiling (found), forgotten and expired records even in `include_historical` mode, scoped callers never receiving another project's records, and the six mutations made **behind a stale index**: a forgotten memory, an expiry, a reclassification to sensitive (memory and note), a deleted note and a rescope were each refused on the very next query, before reconciliation. Two more mutations (forgotten, deleted) were removed from the index at once by the database triggers. After reconciliation the index had no drift (99 expected, 99 indexed, 0 missing, 0 extra, 0 stale, 0 orphans).

### Categories required by the owner

| Category | Where | Result |
|---|---|---|
| Memory facts | synthetic (production's only memory is forgotten) | found at rank 1; forgotten one never returned (production F01, F02 use the forgotten record's own words, taken inside the harness so no one read it) |
| Meeting facts | production, 9 cases | 9/9 at rank 1, except the accepted-correction case at rank 3; corrected wording retrieves the corrected line |
| Notes | production, 7 cases | 7/7 at rank 1 |
| Project/scoped facts | synthetic, 9 cases | own-scope records found; other scope never returned; unrestricted owner sees all |
| Historical | production (no superseded data exists), synthetic | `include_historical` returned nothing that `current` hides: expired and forgotten records are refused in both modes. Historical retrieval therefore has nothing to retrieve with today's source types |
| Negative / absent | production 6, synthetic 2 | 0 relevant items, but see finding 1 |
| Conflicts | synthetic | both conflicting versions ("Tuesday", "Thursday") surfaced in the top 5, so a downstream answerer sees the conflict |
| Cross-source | production 2, synthetic 2 | both expected sources in the top 5 in 4/4 |
| Sensitive / restricted | synthetic and production | 0 leakage; sensitive visible only at a trusted sensitive ceiling |
| Forgotten, expired, deleted | synthetic and production | 0 leakage, immediately, with and without the index being current |
| Generated outputs | production | minutes and summary are labelled `model_generated` and have their own kinds; none unlabelled |
| Citations | all | every returned item resolved to the authoritative record (0 unresolved) |

## 4. Findings (not tuned, for the owner's information)

1. **Retrieval does not signal absence.** Queries about facts that do not exist still return loosely related items when they share common words: production absent-fact queries returned items in 1 of 6 (5 meeting lines for "what did Sarah say about the quarterly budget"); synthetic owner queries for a forgotten or deleted record returned unrelated items in 2 of 7 before and 7 of 8 after mutation (words such as "code" and "key" match other records). None was restricted and none could be the asked-for record (it does not exist), but a downstream answerer must not read "something was returned" as "the fact exists"; selective answering's evidence checks, not retrieval, are what must establish support. This is the main thing 48F measures.
2. **A stale index label can hide a record, never reveal one.** A rescoped note (alpha to beta) was not reachable by a beta caller while the index still carried the old scope (VS2, one recall miss); after reconciliation it was found. The prefilter uses the index's labels and revalidation uses the source, so staleness costs recall and not safety.
3. **Unscoped records are visible to scoped callers by design.** My frozen cases S01 and S02 assumed an unscoped record must not reach a caller restricted to scope `alpha`; the documented design says otherwise (D8: unscoped is owner-accessible while Reachy is single-owner; `search.py`: "these scopes plus unscoped rows"). My harness first flagged these 10 items as cross-scope violations; that was the harness's rule and my case expectation, not a retrieval fault. The original run is kept in the results file (`violations_original_harness`), reclassified as `reclassified_by_design_D8`, and the harness now treats only another project's scope as a violation. **Decision for the owner:** once project-scoped access control exists, D8 says unscoped records need an explicit policy; today a scoped caller sees every unscoped record.
4. Real-corpus quality is bounded by the corpus: 3 notes and 1 meeting. The meeting-fact recall is meaningful (78 segments plus generated outputs); the note, memory, task and document categories on production are thin.

## 5. Operational

Frozen files and capture: the four capture file hashes are unchanged; the 48B instrumentation deploy (14:45 UTC) and this restart (14:46 UTC) are logged as trial boundaries in the [trial log](phase-48b-capture-trial-2026-10-10.md). Indexing stays on (83 rows, 0 queued). Retrieval latency in the harness: median 2.2 ms (production set), max 15 ms.

Results: [production](phase-48e-cases/results-production.json), [synthetic before](phase-48e-cases/results-synthetic-before-mutation.json), [after, stale index](phase-48e-cases/results-synthetic-after-mutation-stale-index.json), [after, reconciled](phase-48e-cases/results-synthetic-after-mutation-reconciled.json) (identifiers, ranks, counts; no record or query text).

Per-case tables:

### B1
| Case | Category | Access | First hit rank | Returned | Violations |
|---|---|---|---|---|---|
| MF1 | memory facts | owner | 1 | 4 | 0 |
| MF2 | memory facts (restricted: shared speaker) | shared | n/a | 0 | 0 |
| MF3 | memory facts (public to shared) | shared | 1 | 1 | 0 |
| MF4 | memory facts | owner | 1 | 1 | 0 |
| MF5 | memory facts | owner | 1 | 2 | 0 |
| TK1 | tasks | owner | 1 | 3 | 0 |
| RM1 | reminders | owner | 1 | 1 | 0 |
| SE1 | sensitive (owner private channel) | owner | n/a | 0 | 0 |
| SE2 | sensitive (trusted sensitive ceiling) | owner_sensitive | 1 | 1 | 0 |
| SE3 | sensitive (owner private channel) | owner | n/a | 0 | 0 |
| SE4 | sensitive (trusted sensitive ceiling) | owner_sensitive | 1 | 1 | 0 |
| SE5 | sensitive (shared speaker) | shared | n/a | 0 | 0 |
| PS1 | project scope | scope:alpha | 1 | 1 | 0 |
| PS2 | project scope (cross-scope) | scope:alpha | n/a | 1 | 0 |
| PS3 | project scope | scope:alpha | 1 | 4 | 0 |
| PS4 | project scope (cross-scope) | scope:alpha | n/a | 1 | 0 |
| PS5 | project scope | scope:beta | 1 | 1 | 0 |
| PS6 | project scope (cross-scope) | scope:beta | n/a | 1 | 0 |
| PS7 | project scope | scope:alpha | 1 | 2 | 0 |
| PS8 | project scope (cross-scope) | scope:beta | n/a | 1 | 0 |
| PS9 | project scope (unrestricted owner sees all) | owner | 1 | 2 | 0 |
| FE1 | forgotten | owner | n/a | 0 | 0 |
| FE2 | expired | owner | n/a | 7 | 0 |
| FE3 | expired (include_historical) | owner | n/a | 7 | 0 |
| FE4 | forgotten (include_historical) | owner | n/a | 0 | 0 |
| CF1 | conflicting facts (both versions must surface) | owner | 1 | 2 | 0 |
| CF2 | conflicting facts | owner | 1 | 2 | 0 |
| XS1 | cross-source | owner | 1 | 2 | 0 |
| XS2 | cross-source | owner | 1 | 2 | 0 |
| NG1 | absent | owner | n/a | 0 | 0 |
| NG2 | absent (restricted term to shared) | shared | n/a | 0 | 0 |
| V0a | pre-mutation control (will be forgotten, trigger on) | owner | 1 | 7 | 0 |
| V0b | pre-mutation control (will be deleted, trigger on) | owner | 1 | 7 | 0 |
| V0c | pre-mutation control (will be forgotten, index left stale) | owner | 1 | 2 | 0 |
| V0d | pre-mutation control (will expire, index left stale) | owner | 1 | 8 | 0 |
| V0e | pre-mutation control (will be reclassified sensitive, index stale) | owner | 1 | 3 | 0 |
| V0f | pre-mutation control (will be deleted, index stale) | owner | 1 | 1 | 0 |
| V0g | pre-mutation control (will be reclassified sensitive, index stale) | owner | 1 | 8 | 0 |
| V0h | pre-mutation control (will be rescoped alpha to beta, index stale) | scope:alpha | 2 | 5 | 0 |

### B2 stale
| Case | Category | Access | First hit rank | Returned | Violations |
|---|---|---|---|---|---|
| TF1 | stale index (trigger removes the row at once): forgotten | owner | n/a | 3 | 0 |
| TD1 | stale index (trigger): deleted | owner | n/a | 3 | 0 |
| VF1 | stale index, revalidation only: forgotten | owner | n/a | 1 | 0 |
| VE1 | stale index, revalidation only: expired | owner | n/a | 4 | 0 |
| VE2 | stale index, revalidation only: expired (historical mode) | owner | n/a | 4 | 0 |
| VR1 | stale index, revalidation only: reclassified sensitive | owner | n/a | 2 | 0 |
| VR2 | reclassified sensitive is still reachable at a sensitive ceiling | owner_sensitive | 1 | 3 | 0 |
| VD1 | stale index, revalidation only: deleted | owner | n/a | 0 | 0 |
| VN1 | stale index, revalidation only: note reclassified sensitive | owner | n/a | 4 | 0 |
| VN2 | note reclassified is reachable at a sensitive ceiling | owner_sensitive | 1 | 5 | 0 |
| VS1 | stale index, revalidation only: rescoped alpha to beta, alpha caller | scope:alpha | n/a | 4 | 0 |
| VS2 | rescoped note is reachable by a beta caller | scope:beta | **MISS** | 4 | 0 |
| VC1 | unchanged records unaffected by the mutations | owner | 1 | 4 | 0 |

### B2 reconciled
| Case | Category | Access | First hit rank | Returned | Violations |
|---|---|---|---|---|---|
| TF1 | stale index (trigger removes the row at once): forgotten | owner | n/a | 3 | 0 |
| TD1 | stale index (trigger): deleted | owner | n/a | 3 | 0 |
| VF1 | stale index, revalidation only: forgotten | owner | n/a | 1 | 0 |
| VE1 | stale index, revalidation only: expired | owner | n/a | 4 | 0 |
| VE2 | stale index, revalidation only: expired (historical mode) | owner | n/a | 4 | 0 |
| VR1 | stale index, revalidation only: reclassified sensitive | owner | n/a | 2 | 0 |
| VR2 | reclassified sensitive is still reachable at a sensitive ceiling | owner_sensitive | 1 | 3 | 0 |
| VD1 | stale index, revalidation only: deleted | owner | n/a | 0 | 0 |
| VN1 | stale index, revalidation only: note reclassified sensitive | owner | n/a | 4 | 0 |
| VN2 | note reclassified is reachable at a sensitive ceiling | owner_sensitive | 1 | 5 | 0 |
| VS1 | stale index, revalidation only: rescoped alpha to beta, alpha caller | scope:alpha | n/a | 4 | 0 |
| VS2 | rescoped note is reachable by a beta caller | scope:beta | 2 | 5 | 0 |
| VC1 | unchanged records unaffected by the mutations | owner | 1 | 4 | 0 |

## 6. Not done, by design

No selective shadow, no cited answering, no change to any reply, no tuning, no robot.
