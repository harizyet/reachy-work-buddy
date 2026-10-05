# ADR 0026: Semantic routing with deterministic argument validation

- Status: **Proposed as target architecture; only the shadow stage is accepted and implemented.** Promotion past shadow needs a separate owner decision per stage (see [Phase 37](../phase-37.md)).
- Date: 2026-10-05

## Context

Natural-language requests reach companion-core's `process_conversation_turn`, which today runs an ordered chain of phrase matchers (`email_intent`, `task_intent`, `memory_intent`, `clock_intent`, …) and falls through to the generic LLM branch. A gap-finder run found 81 of 82 natural phrasings of an action request reached the LLM instead of a matcher, so the matchers alone do not bound what the model is asked to handle, and the LLM answers "I can't mark tasks as done" to requests the system could perform ("mark it done").

A pilot (outside this repo, summarised in [shadow-router](../shadow-router.md#evidence-carried-forward)) showed that a small CPU classifier can choose the operation class well, that a 7B model proposing tool arguments is not safe to execute unchecked (36% to 52% of fresh holdout cases produced an argument that could not be justified from the utterance), and that confidence thresholds do not make writes safe, because some wrong write routes are highly confident.

## Decision

The eventual architecture splits the work into stages with different authority. Only the last two may decide that something happens.

```text
explicit /reachy commands            (authenticated, deterministic; unchanged)
state-bound replies and approvals    (unchanged)
existing deterministic handlers      (kept as the fallback chain)
        |
semantic router (ModernBERT x3, CPU sidecar)   proposes an operation class: 18 routes incl. none and unsupported
        |
argument extractor (local LLM only)            proposes arguments as JSON; never sees authority
        |
deterministic validator (plain code)           DECIDES eligibility: grounded in the utterance, no unresolved reference,
        |                                       single target, bulk scope from the words as well; otherwise a clarification question
consent gate (ADR 0011)                        DECIDES execution: user confirmation, text-only for destructive actions
        |
tool execution, then the response goes to the 7B
```

Rules this ADR fixes:

1. **Authorization stays outside the router and the model.** The router and extractor propose; the validator and the consent gate authorize. A wrong route is safe only because extraction, validation and consent follow it.
2. **No confidence threshold is a write-safety mechanism.** Thresholds may exist as telemetry; the boundary is validation plus confirmation. Delete and complete show the resolved target and need explicit confirmation; bulk deletes are refused (ADR 0011 stands unchanged).
3. **Robot requests stay on `command_suggestion.classify`** (suggestion only, never actuation). The router's `robot.*` routes are recorded, not acted on, until the router beats the classifier on precision.
4. **Extraction is local-only.** An utterance is never sent to the cloud role for argument extraction (ADR 0018 roles are respected).
5. **The existing rule chain remains the fallback** and is retired only after sustained agreement with production, never by default.
6. **Shadow first.** Every stage is observed before it acts: the shadow path never executes a tool and never changes a reply or any consent, draft, memory, task or robot state.
7. **Recorded data is evaluation-only.** Trial records (including utterance text) exist for the evaluation window and are destroyed when evaluation and testing are complete; there is no retention beyond that and no deadline other than completion.

## Consequences

- A new CPU sidecar (`semantic-router`) joins the homelab Compose file behind the `shadow-router` profile; it holds no tool, consent or credential logic and stores nothing.
- Argument extraction competes for the production 7B when run live (measured about 10% decode and 20 ms TTFT). The trial therefore extracts offline; running it live is a deployment optimisation tested later.
- Over-withholding is the known cost: legitimate but oddly phrased requests become clarification questions. Shadow mode measures this (`safe_but_withheld`).
- All evidence outside MASSIVE is author-written, and speech-to-text errors are untested, so promotion needs real-traffic, blind-graded evidence first.
- Ownership (ADR 0001) is unchanged: companion-core owns tools and this pipeline; the sidecar is an inference service reached over HTTP, never imported.
