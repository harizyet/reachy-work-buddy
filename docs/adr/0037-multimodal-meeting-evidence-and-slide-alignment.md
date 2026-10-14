# ADR 0037: Multimodal meeting evidence and slide alignment

- Status: **Proposed 2026-10-14** (built on `feature/meeting-multimodal`, not deployed; accepted when the owner accepts Phase 53)
- Date: 2026-10-14
- Relates to: [ADR 0001](0001-service-boundaries.md), [ADR 0006](0006-response-routing.md), [ADR 0011](0011-destructive-action-consent.md), [ADR 0018](0018-hybrid-llm-routing.md), [ADR 0034](0034-source-evidence-and-derived-artifacts.md), [Phase 31](../phase-31.md), [Phase 50](../phase-50.md), [Phase 53](../phase-53.md)

## Context

The owner records a meeting, then uploads a presentation hours or days later and wants the transcript read next to the slides. Two machine-made sources (a speech-to-text transcript and a document extraction) have to be related, and the only thing that can relate them is the wording of the discussion. Nothing in either source says which slide was on a screen at any moment. A design that hides this produces a tidy slide timeline that nobody can trust.

## Decision

**1. The relationship is an estimate, stored as a derived artifact, and never a fact about the meeting.** A *slide alignment* names a transcript window (consecutive segments), a page of a linked document (or no page), a certainty label, the observable reasons, and the *revision* of each source it was derived from. It is an ADR 0034 derived interpretation. No code path, label or sentence says a slide "was shown"; the product says "likely" and "estimate".

**2. Four evidence classes with different authority are kept separate everywhere (storage, answers, UI):**

| Class | What it is | Can it support a decision? |
|---|---|---|
| What the document says | derived extraction of a page ([ADR 0034](0034-source-evidence-and-derived-artifacts.md)) | no: a slide is not evidence that participants agreed |
| What a speaker said | a quote verified in the transcript | yes |
| What the owner confirmed | an alignment review row | yes, for the association only |
| What Reachy infers | a model-written combination, labelled | never on its own |

A decision, an open question or an action needs a verified *transcript* quote. A disagreement needs one verified quote from *each* side. Quotes are located in the source text, never accepted from the model, and carry the source's own timestamps, speaker label, page and revision.

**3. Certainty is assigned by fixed rules, not by the model.** The four labels (high, medium, low, unknown) come from observable signals only: a resolved explicit reference, distinctive shared words, the lead over the runner-up page, and whether the local model, asked to choose among at most four candidates (or none), chose the lexical leader. The model can choose, decline or comment; it cannot raise a label. The rules are in [phase-53.md](../phase-53.md#43-certainty-rules) and each is tested. There is no numeric confidence, and no claim of calibration.

**4. Slide order is a weak prior, not a constraint.** A page chosen for the window before gets a small ranking bonus and the next page a smaller one. Returning to earlier slides, skipping slides, discussing something on no slide, and two decks with similar content are all representable. An explicit page number ("slide 7") counts only when it resolves to exactly one attached document (or the deck is named); otherwise it is reported and not used.

**5. The owner's decision is a separate record and always wins.** A review (confirm, choose another page, "not about a slide", "remove this suggestion") is stored with the revisions it was made against and is never touched by a rerun. When the transcript text of its window, or the document's revision (original, parser revision, tier, page count), changes, the decision is shown as *needs confirmation again* and stops counting as owner authority until confirmed.

**6. Nothing is copied.** Links, runs, estimates, reviews and findings reference meetings and documents by id and hold hashes and short quotes, not transcripts or document text; no foreign keys, so the phase is removable ([rollback-034.sql](../../deploy/homelab/rollback-034.sql)). Pages are read through the existing document library service and transcripts through the existing meeting store, with the access check of the caller on every read.

**7. Access is the stricter of both sources, recomputed from the sources as they are now.** The caller's ceiling (set by the hub) must allow the meeting and every document used; a source the caller cannot read is indistinguishable from one that does not exist, and no count, title or run state derived from it is shown. A derived output carries the stricter classification and is never below any source it used. Linking never grants wider access, and documents or meetings of different projects are never associated.

**8. Lifecycle follows the sources.** Deleting a document (the listener fires when it enters the deleting state) removes every association, estimate, review and finding that used it, in every meeting, leaving a task the owner already confirmed. Deleting a meeting removes its multimodal rows. Detaching removes the attachment's derived rows for that meeting only. A transcript correction or a reprocess marks derived rows out of date on every read, without rewriting any source.

**9. No new authority.** The model has no tools and runs locally. Instruction-like text in slides or the transcript cannot become a finding, a label or a task. A finding becomes a task only through the owner's confirmation (derived task id, the existing receipt); nothing is indexed for retrieval, promoted to memory, or sent to Phase 44/48/50F paths.

## Consequences

- The transcript can show "Likely slide 7 — Edge Architecture, certainty High" with a reason that is true by construction, and a correction takes one click.
- Fewer windows get a label than a model-only approach would produce: a window needs shared words with a page or an explicit reference to reach the model at all. The product prefers "No confident slide association" to an invented one.
- Vocabulary overlap is a weak method for slides that are mostly figures or for talk about a slide in other words; those windows stay unknown or low and are corrected by hand. No visual model is used.
- Presentations are read as pages by the document pipeline: PPTX, PPT, ODP and PDF give one page per slide (measured, [document types](../verification/phase-53-document-types-2026-10-14.md)). Only PDF and images have page pictures, so a PowerPoint attachment has text and titles but no thumbnail. Other file types are one page (spreadsheets: one per sheet), so a page estimate for them is coarse.
- A dismissed finding is not resurrected by a rerun, and the owner's reviews survive reruns, at the cost of keeping per-window rows until the meeting or document is deleted.
