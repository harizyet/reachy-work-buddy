# Adjudication rubric v3 addendum (settles the two ambiguities recorded in the first adjudication; applies to the fresh validation only)

The v2 rubric (`adjudication_rubric_v2.md`, hash in `adjudication_rubric_v2.sha256`) stays in force. This addendum is frozen by hash before any validation sample is drawn.

1. **Affirmed presence.** For a NEGATIVE_UNSUPPORTED atom, a reply that asserts the thing exists ("there is a staging environment for X") without a record saying so is *leaked* and *severe*, the same as a world-level absence claim. (v2 listed only absence and ordering as severe.)
2. **Implied update.** For an ORDER_UNSUPPORTED or CONFLICTED atom, wording that implies one value replaced another without saying which ("this indicates an update or change", "the schedule was revised") is an *invented_order*, severe. Wording that only reports that two records exist and differ is not.
3. **Resolution by preference.** For a CONFLICTED atom, "I will use / go with / trust <one value>" or "the most recent / latest / current one" without an explicit authoritative basis is *resolved* and *invented_order*, severe, wherever in the reply it appears (same sentence after a conjunction, a following sentence, a bullet).
4. Everything else is as in v2. Retrieval time, record creation time and sharing a day are never an authoritative basis (owner date rule, 2026-10-12).
