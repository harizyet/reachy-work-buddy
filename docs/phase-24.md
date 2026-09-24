# Phase 24 — Web-search-grounded general LLM assistant

Status: planned, not implemented. Independent of Phase 23's Google Accounts
and Phase 25's owner recognition — it only touches the existing generic
conversation branch, the pluggable `ChatProvider`/role-routing LLM stack
(Phases 19/21), and Phase 23's migration framework for its own config table.
Does not depend on Phase 22b hardware or Phase 25's recognition gate.

## Motivation

Small local models (the default `LOCAL` role) routinely answer factual or
current questions from stale trained knowledge instead of admitting they
don't know — the classic small-model hallucination failure. A deterministic
web search performed before every generic-conversation LLM call, with the
model instructed to answer only from the returned results, turns "guess from
training data" into "read this and answer," for both the `LOCAL` role and
questions escalated to `CLOUD`/frontier models under Phase 21's routing.

## Required behaviour

- Every generic-conversation turn (the existing `else` branch in
  `companion_core/app.py` that currently calls `route_completion` directly)
  triggers exactly one web search against the turn's own text, before the
  LLM call — deterministic and unconditional, not a judgment call left to
  the model. This matches the existing deterministic-intent-before-LLM
  pattern already used for calendar/task/email/RAG-docs matching
  (`*_intent.py` modules); it is simply always-on instead of prefix-triggered.
- The top-N results (title, snippet, URL) are formatted into a dedicated
  grounding system message — separate from the persona system message —
  instructing the model to answer only from the provided results and to say
  so plainly when they don't answer the question, rather than falling back
  to its own trained claim. Injected after persona, before conversation
  history, mirroring how persona is already prepended today.
- Applies uniformly to `LOCAL`, `CLOUD`, and `force_frontier` turns — "more
  complex questions sent to larger models" is the same code path as ordinary
  local turns, not a separate one gated on role.
- Does not apply to any deterministic-intent branch already handled earlier
  in `app.py`'s `if`/`elif` chain (calendar, tasks, email, memory, RAG-docs
  search, Gmail) — those never reach the generic `else` branch, so they are
  structurally unaffected.

## Non-goals

- **No general agentic tool-calling loop.** The model never decides whether
  or what to search; there is exactly one deterministic retrieval step per
  turn, not a tool-use framework the model can invoke, chain, or loop on.
  This avoids the hallucinated-tool-call and unbounded-loop failure modes of
  general tool calling and matches the instruction not to add speculative,
  later-phase functionality — a single fixed grounding step, nothing more.
- **No answer-quality arbitration.** Whether the returned results actually
  answer the question is left to the model's own use of them, not a second
  LLM call judging relevance — same honesty-about-scope discipline as this
  codebase's other placeholder classifiers and Phase 21's escalation logic
  (a real automatic quality judgment needs another LLM call and is out of
  scope for v1).
- **No multi-query or follow-up search refinement in v1.** One query per
  turn, taken from the turn's own text (trimmed, not rewritten), one search
  call, one result set.
- **No merge with Phase 13's RAG-over-owned-documents.** Web search is an
  external, unauthenticated public source; it is not written into the
  vector store and does not change RAG's existing provenance model.

## Architecture and service boundaries

Preserve ADR 0001: no sibling-service runtime imports. This is a
companion-core (cognition) concern end to end, same as LLM routing;
reachy-hub is untouched, and no new hub endpoint is added — grounding
happens entirely inside the existing `/messages` → core turn path.

New `companion_core/websearch/` module, shaped like `llm/client.py`'s
`OpenAICompatibleChatProvider`: a small `SearchProvider` protocol plus one
`HttpSearchProvider` implementation — pluggable `base_url`/`api_key`, no
vendor SDK, no separate provider-per-vendor code fork. Two configurations
are expected to work against it:

- A self-hosted [SearXNG](https://docs.searxng.org/) instance reachable over
  its JSON API — the default/first-recommended target, consistent with this
  project's local-first precedent for the `LOCAL` LLM role (Phase 19).
- A cloud search API (e.g. Brave Search) as an explicit opt-in alternative,
  configured the same way Phase 21 added the `CLOUD` LLM role: a
  `base_url`/`api_key` pair, not a second code path.

New shared model `shared/models/websearch.py`: `SearchConfig` (enabled flag,
provider `base_url`, optional `api_key`, result count, timeout seconds) —
same shape and precedent as `shared/models/llm.py`'s `ProviderConfig`. Stored
in a new `search_config` table (single row, matching `persona_config`'s
convention) added via a proper Phase 23-style versioned migration, not
`CREATE TABLE IF NOT EXISTS`.

The operator UI gets a "Web search" settings card (Settings, alongside the
existing LLM and Persona cards): provider URL/key, enable toggle, result
count. `GET`/`PUT /settings/websearch` on core, hub-proxied the same way
`GET`/`PUT /settings/persona` already is.

## Privacy

Sending the current turn's text to a configured search provider is a new
outbound network path, distinct from Phase 21's cloud-LLM-escalation
reasoning (which only covers the already-configured `CLOUD` role's own
call). Default is disabled: with no provider configured, there are zero
outbound search calls and behaviour is byte-for-byte unchanged from today —
the same "no fictional calls" discipline Phase 21 already applies to its
usage log. A self-hosted SearXNG instance keeps every query inside the
homelab network and should be the documented default specifically to avoid
handing a third-party search company a standing query log; a cloud provider
is opt-in and disclosed in the settings UI next to its toggle, the same way
Phase 21 discloses that cloud inference receives the same bounded context as
local. Only the current turn's own text is sent — never the full
conversation history. Logging follows the existing usage-log convention of
recording provider/success/latency only, never the query content itself,
the same "never persist raw provider errors/content" rule already applied to
LLM usage and (in Phase 26's plan) meeting error details.

## Failure handling

A search timeout, transport error, or empty/malformed response must never
block or crash the turn: on any failure, the turn falls back to calling the
LLM without the grounding message and proceeds exactly as it does today,
mirroring Phase 21's "provider failure is not a crash" doctrine for the LLM
call itself. There is no retry loop — one attempt per turn — with its own
short bounded deadline (a few seconds, well under Phase 21's existing 60s
per-provider / 130s hub / 135s browser budgets, since this runs *before*
the LLM call those budgets were already sized around).

## Implementation sequence

1. Add `shared/models/websearch.py` (`SearchConfig`) and the
   `search_config` migration under companion-core's existing migration
   framework (Phase 23).
2. Add `companion_core/websearch/` — the `SearchProvider` protocol,
   `HttpSearchProvider`, and a result-formatting function that always names
   its sources (same discipline as `rag_intent.format_answer`, which always
   names the retrieved document — here, the result URLs).
3. Wire the generic-conversation `else` branch in `app.py`: when a provider
   is configured, call it with `turn.text` before `route_completion`, inject
   the grounding message ahead of conversation history, and continue
   ungrounded on any provider failure.
4. Add `GET`/`PUT /settings/websearch` on core and the matching hub proxy
   route, following the existing persona settings pattern exactly.
5. Add the operator UI "Web search" settings card.
6. Once implemented, record the boundary/privacy decision as an ADR (next
   number after 0021) — this plan documents the intended shape, but the
   binding decision is written from the real implementation, matching this
   project's existing practice for prior phases.

## Exit criteria

| Check | Required result |
|---|---|
| Grounded answer | Against a fixture provider with known canned results (not live internet, for deterministic tests), a factual/current-events question produces an answer drawn from the fixture results, not an unprompted trained claim |
| Small-model hallucination reduction | The same fixture-driven test, run with search enabled vs. disabled for the `LOCAL` role, shows the grounded answer reflects fixture content; this demonstrates the mechanism, not a general hallucination-rate claim |
| Complex/escalated questions | `force_frontier` and `CLOUD`-role turns receive the same grounding message as `LOCAL`-role turns, from the same code path |
| Deterministic intents unaffected | Calendar/task/email/memory/RAG-docs/Gmail branches never trigger a web search call, verified by call-count assertions |
| Failure isolation | A forced provider timeout, error, or malformed response still returns the ordinary ungrounded reply, not an error or a hang |
| Privacy default | No provider configured: zero outbound search calls, identical behaviour to before this phase |
| Disclosure | The operator UI clearly shows which provider (self-hosted vs. cloud) is configured and that turn text is sent to it |
| Regression | Existing Python/Ruff/browser checks and Phase 19–21 tests still pass |

No implementation, live search-provider call, or provider account signup is
performed by this planning change.
