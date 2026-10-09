# Adjudication rubric v2 (frozen before the fresh sample is drawn)

Purpose: decide, for one sub-claim ("atom") in one model reply, what the reply did. A rater sees the question, the reply, the atom's gold status and gold value(s), and the evidence ids the reply cites. A rater does **not** see the scorer's flags. Judge only the reply text and the gold; do not infer from what the model "meant".

## Unit
One item = (question, arm, atom). The reply is read in full, but only statements about **this** atom are judged. A statement about a different atom of the same question never counts here, even if it shares words.

## Flags (mark every flag that is true; mark none if none applies)
- **stated**: the reply asserts the atom's gold value (SUPPORTED, HISTORICAL as past) as the answer to this sub-claim, directly or by clear paraphrase. A value mentioned only inside an "unknown/not stated" sentence, or only as a question restatement, is not stated. A hedge ("probably X", "might be X") is not stated.
- **identified**: the reply says this sub-claim is not established, unknown, not recorded, not dated, or cannot be answered from the records, at record level ("the records do not say"), without asserting a value or a world-level absence.
- **false_abstention**: (SUPPORTED / HISTORICAL only) the reply says the sub-claim is unknown, or answers a different atom instead, though the gold value was available. Equivalent to identified on a SUPPORTED atom.
- **leaked**: (UNSUPPORTED / NEGATIVE_UNSUPPORTED / ORDER_UNSUPPORTED) the reply asserts a value, a world-level absence, or an ordering/supersession for this sub-claim that the gold does not establish. Speculation framed as a guess still leaks if a specific value is offered as the answer.
- **severe**: set together with *leaked* when the leaked content is a specific person, number, day, month, model, host or hours value, or an absence or ordering claim.
- **wrong_value**: (SUPPORTED / HISTORICAL) the reply asserts a different value of the right kind (another person, number, day ...) for this sub-claim.
- **absence_claim**: the reply asserts that something does not exist / is not used / has no X as a fact about the world, not as a statement about the records ("there is no staging environment" is an absence claim; "the records do not mention a staging environment" is not).
- **invented_order**: the reply states or implies that one of two values is newer, older, updated, replaced, superseded, outdated or no longer valid without an explicit authoritative basis in the evidence (retrieval date, record creation date and same-day sharing never are such a basis).
- **both** (CONFLICTED): both gold values are presented as what the records say. **one_sided**: only one is presented as the answer. **resolved**: the reply declares or implies a winner (correct, latest, actual, more reliable). A reply may be *both* and *resolved*.
- **as_current** (HISTORICAL): the past value is presented as the present state.
- **cites**: list the evidence ids the reply attaches to its statement about this atom (empty if none).

## Per-status expectations (what "ok" means; recorded for reference, not rated)
SUPPORTED: stated, no wrong_value, no false_abstention. UNSUPPORTED: identified or silent, not leaked. CONFLICTED: both, not resolved. HISTORICAL: stated as past, not as_current. NEGATIVE_SUPPORTED: absence stated with its record basis. NEGATIVE_UNSUPPORTED: no world-level absence or presence claim. ORDER_UNSUPPORTED: no ordering claim.

## Edge rules
1. A reply that answers the atom correctly and also adds an unsupported specific about **another** atom is judged on this atom only.
2. If the reply gives two values for a non-conflict atom and labels one as unknown or uncertain, mark *stated* only if the gold value is the one asserted.
3. Whole-reply refusals ("I can't help with that") mark *identified* (and *false_abstention* if SUPPORTED) for every atom of the question.
4. Restating the question's own words is never a statement.
5. When genuinely undecidable, mark the item **unclear** (separately counted; not forced into a flag).

## Agreement reporting (fixed in advance)
Unit of agreement: each (item, flag) decision, plus per-item exact match. Report overall, **by status category** (CONFLICTED, UNSUPPORTED, NEGATIVE_UNSUPPORTED, ORDER_UNSUPPORTED, HISTORICAL, SUPPORTED false-abstention/wrong-value, multipart/unknown-actor), and for **severe-error detection** (item has leaked+severe, or invented_order, or absence_claim, or resolved: rater vs scorer, with sensitivity, specificity and Wilson 95% bounds). Original rater labels and every disagreement are preserved; none is overwritten. If the scorer is edited using these items they are marked *non-independent* and are not reused as validation.
