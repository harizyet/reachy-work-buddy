# ADR 0033: LLM-assisted read routing with deterministic grounding

- Status: **Accepted 2026-10-11** (owner-approved rollout; deployed with `INTENT_ROUTER_ENABLED=true`). Not a numbered phase.
- Date: 2026-10-11
- Relates to: [ADR 0011](0011-destructive-action-consent.md) (destructive-action consent), [ADR 0018](0018-hybrid-llm-routing.md) (model routing), [Phase 24b](../phase-24b.md), [Phase 44H](../phase-44h.md), [Phase 49](../phase-49.md)

## Context

The deterministic intent chain in companion-core handles explicit phrasings. Natural-language questions about the owner's own records ("anything I should be doing next week?", "who is my Google on-prem contact?") either fell to a broad regex that answered something else or reached ordinary chat, where the model, which is given no records, answered anyway. The owner asked for the local model to infer the intended read, without giving it any way to write, bypass consent or invent records.

## Decision

1. **Deterministic first.** Explicit commands, consent and confirmation, named-record references, the Phase 49 task inquiry, alarms and every other existing handler run before the router. The Phase 44H boundary refuses action requests, and the mixed-intent refusal (below) runs before any handler. The router sees only what none of them claimed.
2. **The model chooses among a closed, read-only allowlist.** One JSON object: an operation (`tasks.list`, `reminders.list`, `notes.list`, `records.find`, `memory.recall`, `none`), an advisory `kind`, an optional search phrase and a confidence. Anything else is rejected (strict schema, no extra fields). There is no write operation and no tool execution. The model never sees a record; every sentence of the reply is built by the existing handler from the stores.
3. **Authority stays outside the model.** Access is derived from the input modality and channel only (`selective_answer.access_for`); a model-supplied name, kind, confidence, query or an instruction in the owner's text widens nothing. A shared speaker is read no task, reminder, note or meeting. A search phrase must consist of words the owner used.
4. **Dates are deterministic.** Only today, tomorrow, this week and next week are understood, in the persona timezone, from the owner's words (`task_intent.time_scope`); the model has no date field. Tasks have no due date and stay undated; only reminders and proposals with `due_at` are placed in a window. Any other time wording or two windows at once gets a fixed limitation, not a guess.
5. **Grounding is decided from the owner's words, not by the model.** `requires_records` marks a read-shaped question that needs the owner's own records (their tasks, notes, meetings; their contacts and owners; what they or their team wrote, said, decided or recommended; what a named person recommended). If it does and no supported read answers it (the model said `none`, timed out, failed, was malformed, unsure or invented an operation), the reply is a fixed clarification and ordinary chat is not reached. A general-knowledge question still reaches chat.
6. **Read and write in one message are refused whole.** A message that starts as a read and also asks to change or send something runs neither half and names the operation not performed (`mixed_intent.py`). No multi-step execution. The 44H boundary is unchanged.
7. **Labels follow the records, not the question.** A reply is labelled by the most restrictive of the question's label, work-private and the sensitivity of every record it names, and every list or search handler applies the channel's sensitivity ceiling and scope. A reply built from stored records is never public.
8. **A title alone can name a record.** "What did I write in My Task for next week?" is resolved through the existing authorised `resolve` (one match: read verbatim; several: clarification; none: not found for the "did I write" form), and never becomes the structured task list.
9. **Rollout control.** `INTENT_ROUTER_ENABLED` (default false) switches only the model-driven part: off means no classifier call and no records clarification. The matcher narrowing, the mixed refusal, the label and ceiling rules and the title-only resolution are deterministic and always on.

## Consequences

- Reads of the owner's records stay explainable: the model picks a handler, the handler answers from stores, tests exercise both states of the flag.
- Cue lists (`requires_records`, `mixed_intent`) are fixed patterns and need occasional additions. A question with no personal cue at all still reaches ordinary chat; the provenance backstop and the 44E answerer are the controls there. A question that merely resembles a record lookup ("Who did Obama recommend?") gets a clarification.
- Search is a plain substring match over notes, meetings and memory; a model phrase that is not contiguous in the stored text finds nothing and says so. A better matcher would be a new retrieval capability and needs its own decision.
- One extra local call (about 0.7 s) for eligible questions only; conversational and deterministic turns pay nothing.
- Rollback is the flag (and a core recreate), or the previous image; images before the privacy remediation carry the old label defect.
- Evidence: [engineering record](../verification/intent-router-2026-10-11.md), [privacy and title-only fix](../verification/task-privacy-named-note-2026-10-11.md), [deployments](../verification/intent-router-deployment-2026-10-11.md) and [privacy remediation](../verification/privacy-remediation-and-searxng-rotation-2026-10-11.md).
