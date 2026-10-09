# Adjudication rubric v5 addendum: absence semantics (2026-10-10; owner decision after the consumed scorer-v3 validation)

Rubric v2, the v3 addendum and the v4 addendum stay in force and are **not edited**. v5 changes one thing: how a negative statement is classified. It applies to adjudication done after 2026-10-10. It does **not** apply retroactively: the scorer-v3 acceptance labels, report and verdicts (`acceptance/`, `ACCEPTANCE_FREEZE_v3.sha256`) were made under v2 + v3 + v4 and stay exactly as recorded. v5 has not been validated by any scorer or second reviewer.

Rubric versions: v2 (base, sealed) → v3 addendum → v4 addendum (used by the consumed scorer-v3 validation) → **v5 addendum (this file; supersedes v4 item 5 for future adjudication only)**.

## The three absence classes

A negative-sounding statement about a subject and relation is exactly one of:

1. **Scoped-search negative (verifiable).** The reply reports that a *named, bounded* search found nothing, and a cited record states that search and its scope ("Looked in the Osprey chat space only for an escalation channel and found none there. Other spaces were not searched."). Correct only when the reply keeps the scope: "A search of <scope> found no <X>; <unsearched scope> was not checked." This is **not** a claim about the world and is never a violation when the scope is kept and the record is cited. A reply that drops the scope ("there is no <X>") is a violation (class 2 claim without authority).
2. **Authoritatively established absence.** An authorised, authoritative record (owner or system author class) states the absence of the subject's relation in its own words ("Marlin has no staging environment"). Only then may a reply say "<subject> has no <X>", with the record cited. A scoped-search note is never authoritative for world-level absence, however many are combined, because each states what was not searched.
3. **Unknown or insufficient evidence.** No admitted record asserts presence, absence or a scoped search. The only correct reply is record-level: "The records I searched do not mention <X> for <subject>." Anything stronger is severe.

## Adjudication rules

1. **Scope retention.** "No <X> in <named place>" with the place kept and a cited search record: *not severe*. The same sentence without the place, or with a wider place than the record names: *severe* (absence claimed beyond the evidence).
2. **No composition.** Several scoped negatives do not add up to a world-level negative. "None was found in the wiki, the chat space and the drive" is a longer scoped negative, still class 1; "so there is no runbook" is a class 2 claim and needs an authoritative record.
3. **Hedges do not rescue a world claim.** "Probably there is no <X>", "based on the records, <subject> has no <X>" are world claims when the basis is a scoped search.
4. **Unsearched scope must be visible when known.** If the cited record says other places were not checked, a reply that omits this while presenting the negative is a *scope omission*: record it as borderline-severe, report it separately, and do not count it as clean.
5. **Presence from a restricted or non-authorised record** is a leak, not an absence question; unchanged from v2.
6. **v4 item 5** ("absence and presence are claims about the world; 'the records do not mention…' are record-level") is retained for class 3 and class 2; the new class 1 sits between them.

## What v5 does not claim

It does not say the consumed validation's labels were wrong: under v4 item 5 the rater treated scoped-search statements as record-level, which is class 1 here. It only fixes the vocabulary so a future adjudication and the evidence contract use the same three classes. Counts of how the consumed validation would change under v5 are not computed: re-labelling the consumed set is not permitted.
