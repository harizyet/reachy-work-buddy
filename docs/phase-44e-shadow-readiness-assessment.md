# Phase 44E: readiness assessment for B1a measure-only shadow mode (2026-10-11)

For the owner's decision. **Nothing here is deployed or enabled.** Production indexing (`KNOWLEDGE_INDEXING_ENABLED=false`), shadow activation and any answer-path integration each need separate owner approval. What the shadow is: after a reply is final, it classifies the turn, and for qualifying knowledge questions runs status or person routing or B1a lexical retrieval, builds the 1,500-token block, and records **aggregate counts only** (never text, hashes, ids, titles or sessions). It cannot change a reply, a prompt, the model that answers, a store, an authorization or the robot ([contract](../services/companion-core/src/companion_core/knowledge/shadow.py)). Evidence is in the [follow-up](verification/phase-44e-followup-2026-10-09.md), [readiness](verification/phase-44e-shadow-readiness-2026-10-10.md), [indexing trial](verification/phase-44b-indexing-workload-trial-2026-10-09.md), [blind review](verification/phase-44e-blind-review-2026-10-10.md) and [answer-quality](verification/phase-44e-answer-quality-2026-10-11.md) records.

## 1. The six readiness items

| Item | State | Evidence | Verdict |
|---|---|---|---|
| **Knowledge-query qualification** | Built (`knowledge/qualify.py`): fixed rules, a vocabulary from the owner's own record titles, names and rare words, refreshed in the shadow's worker. | Synthetic sets: precision 0.79 to 0.96, recall 0.93 to 1.00; a clean final set 0.94 and 1.00. | Good enough to **start** counting; precision on real traffic is unmeasured (section 4). |
| **Offline, reproducible embedding model** | Proposal only ([design](phase-44-model-cache-proposal.md)). The model already sits in a persistent volume at revision `1110a243…`, loaded by name (so it contacts the hub). The pinned revision reproduces the 81 stored vectors to float noise (max 1.2e-7). | Read-only check, 2026-10-10. | **Not needed by the shadow itself** (it is lexical and loads no model). **Needed before continuous indexing** (the indexer loads MiniLM, +516 MB, 13 s, and contacts the hub). |
| **Production lifespan and queue isolation** | Built and tested on a disposable Postgres through the real lifespan: shared pool (no pool of its own), identical foreground prompts, model, replies and database state with the shadow off and on, queue saturation, database faults, shutdown, restart, a shadow that cannot start or stop. A real-model live-route run (7 attacks, on and off) changed nothing. | 7 lifespan tests, 12 route tests, 14 real-model runs. | Ready for a first observed production run. |
| **Aggregate telemetry, 30-day retention** | Built: hourly rows, counts and bucketed histograms, a funnel that reconciles, 0600, pruned at start and daily, default 30 days. | Allowlist, 15-string absence, funnel identities, pruning tests. | Ready. |
| **Authorized, privacy-safe real-world evaluation** | Designed below (section 4); not run. | n/a | Needs your approval of the protocol. |
| **Rollback plan** | Section 5. | Tested: flag off is a `None` check; deletion of the log removes everything. | Ready. |

## 2. What a first shadow rollout would and would not measure

The shadow reads the knowledge index for retrieval turns. **With indexing off the index is frozen at its 81 rows** (one of the owner's two notes is in it; the second genuine note is pending in the outbox). So an immediate shadow rollout measures (a) how many turns are knowledge questions and how many qualify, (b) how often the status and person routes answer from the stores (these read the authoritative stores directly and do not need the index), (c) latency, token and exclusion counts, and (d) B1a retrieval only against that small frozen index. Steady-state B1a retrieval quality on real data needs continuous indexing, which is a separate approval with its own prerequisites (offline model, observed steady state).

## 3. Production blockers versus research that can continue

**Blockers for starting a measure-only shadow rollout** (all small, none technical research):
1. **Owner approval of the rollout and its protocol**, and of a core deployment: the production core image predates the shadow code, so using it needs a build and a recreate of core with the flag still off (a production deploy: backup, smoke checks, the usual sequence).
2. **A log location and retention decision:** a volume path for `KNOWLEDGE_SHADOW_LOG_PATH` (new volume or a bind), 30-day retention confirmed.
3. **A first observed run with you present** (deploy flag off and verify nothing changed; then turn the shadow on for a short window and read the aggregate rows).
4. **The evaluation protocol approved** (section 4), so the numbers can be interpreted.

**Not blockers (research that can continue after a safe measure-only rollout):** invented supersession and negative-claim handling; contamination (the model volunteering planted text); the conflict-omission detector; the claim and receipt boundary (Phase 44H, whose cheap first step, a fixed reply for unclaimed action requests, is independent of the shadow); a larger-model comparison; better qualification recall; answer-path integration; 44F.

**Blockers for later steps, not for the shadow:** continuous indexing needs the offline model cache, an observed steady-state run and the pending outbox row accounted for; any answer-path integration needs the 44H security review, an active claim boundary and a shadow period meeting the 14-day, 50-qualifying-question criterion (counted by `evaluated_qualifying`, with the precision from section 4).

## 4. Privacy-safe real-world evaluation design (proposal)

Goal: learn the qualifier's precision and recall on real traffic without storing any text. Telemetry holds counts per hour only, so labels cannot be attached to turns. Protocol:
1. **Scripted batches, known labels.** The owner prepares two lists on paper: 25 questions they would really ask about their records, and 25 ordinary turns that are not (chit-chat, general questions, commands). They never go into the repository.
2. **Separate hours.** In one hour the owner asks only the first list on a private channel; in another hour only the second. Because the telemetry window is the hour, each window's `admitted` and `not_qualifying` counts give true positives and false negatives (first window) and false positives and true negatives (second window) directly.
3. **Natural traffic.** After that, normal use for the criterion window; the rate of `admitted` turns, `empty_results` and routed paths describes usage.
4. **No text, no ids, no sessions** are ever recorded; the lists stay with the owner; the owner decides to stop at any time.
Needs: the shadow on, indexing unchanged, two hours of the owner's time, and your approval of the protocol.

## 5. Explicit rollback

Unset `KNOWLEDGE_SHADOW_ENABLED` and recreate core (about 30 seconds, the same command as the indexing trial's rollback): no object, no query, no file, no connection. No migration, endpoint or table is involved. Delete the log file to erase everything it ever recorded. If the deploy itself is rolled back, restore the previous core image (rollback images are kept per the deployment procedure). The shadow's failure modes (error, timeout, queue overflow, startup failure, write failure) only increment counters; none can reach a reply.

## 6. Recommendation

The pipeline is ready for a **short, observed, flag-controlled measure-only shadow window**, in two approvals: (1) deploy the current core with the shadow off and verify identical behaviour; (2) enable the shadow for the scripted evaluation. Continuous indexing, the offline model cache, answer-path integration and Phase 44F stay behind their own approvals. The known weaknesses (invented supersession, contamination, scorer coverage) do not affect a measure-only shadow because it changes no answer.
