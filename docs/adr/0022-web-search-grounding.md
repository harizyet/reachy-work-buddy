# ADR 0022: Web-search grounding for the generic conversation branch

- Status: Accepted
- Date: 2026-09-24

companion-core owns web-search grounding end to end, same as LLM routing
(ADR 0018): a `SearchProvider` protocol plus one adapter per provider
(`companion_core/websearch/searxng.py` first), a deterministic search
policy/heuristic, prompt construction, and the `search_config` settings
table. reachy-hub is untouched beyond the existing authenticated settings
proxy pattern; no new hub endpoint reaches an external search provider
directly, and grounding happens entirely inside core's existing
`/messages` → `/conversation` turn path. See
[docs/phase-24a.md](../phase-24a.md) for the full design.

## Decision

The decision of whether to search a given turn is made entirely by a fixed,
code-authored policy/heuristic (`websearch/policy.py`), never by the model.
Policy has three states — `off` (default, zero outbound calls), `auto`
(fixed keyword/pattern match), `always` (every generic-conversation turn) —
mirroring Phase 21's routing-mode precedent of a deterministic gate ahead
of any model call. This applies identically to `LOCAL`, `CLOUD`, and
`force_frontier` turns; it is one code path, not one gated on role. It
never applies to a turn any deterministic-intent branch (calendar/tasks/
email/memory/RAG-docs/Gmail) already handled earlier in `app.py`'s
`if`/`elif` chain, since those return before the generic `else` branch this
phase touches.

Retrieved content is external, unauthenticated data and is never given the
same authority as the persona/rules system message. `websearch/prompt.py`
keeps the fixed, code-authored rules (untrusted-data handling, citation,
failure disclosure) in one message that never contains any text drawn from
a provider response, and puts titles/snippets/URLs in a separate,
delimited, lower-authority message. This extends the same "external
content is data, never authority" discipline already applied to Gmail
content and calendar entries (ADR 0021) to this new input type. A search
timeout/error on a turn the policy judged search-warranted never silently
falls back to an ungrounded answer; the LLM call still proceeds, but with
an explicit failure notice instead of silence, so the model doesn't quietly
answer a freshness-sensitive question from stale trained knowledge.

`deploy/homelab/docker-compose.yml` ships a `searxng` service (internal-only,
never published to the host — the same non-exposure pattern already used
for mailpit's SMTP port) with a checked-in `deploy/homelab/searxng/settings.yml`
enabling its JSON API and disabling its public-instance rate limiter, both
appropriate only because the container is reachable solely from other
compose services. It is not simulation-gated like mailpit or
reachy-embodiment — unlike a fake mailbox, this is real self-hosted
infrastructure meant for production use too — but it is inert until an
operator both sets `SEARXNG_SECRET_KEY` and points Settings → Web search at
it with a non-Off policy, so a deployment that never touches this feature
runs it for nothing rather than being forced to install it separately.

Provider API keys are credentials, not configuration, and use the existing
core-owned `SecretStore` (ADR 0020) exactly like LLM provider keys:
`search_config` stores only a `secret_ref`, resolved via
`SecretContext("owner", f"websearch:{provider}", "api_key")` at call time
and never persisted or logged in plaintext. A provider switch always starts
a fresh credential rather than reusing a ref written under the previous
provider's context.

The search query is built from the current user turn alone by default,
plus the immediately preceding user turn only when a second, separate
fixed heuristic judges the current turn referential/underspecified on its
own. This is a privacy control as much as a relevance one: an unrelated,
possibly sensitive prior turn is never sent to the search provider just
because it happened to come first. Neither the search-or-not decision nor
the query itself is LLM-rewritten; both come from fixed rules operating on
at most the last two user turns.

## Consequences

Default behavior (policy `off`, no provider configured) is byte-for-byte
unchanged from before this phase — zero outbound search calls. A
self-hosted SearXNG instance keeps Reachy's own outbound query confined to
that instance, but SearXNG itself may still forward to upstream engines it
is configured to use; this is disclosed in the operator UI rather than
implying full network confinement. A hosted cloud provider is an explicit
opt-in, disclosed the same way Phase 21 discloses cloud-inference context
sharing. Citation is a prompting/formatting requirement on the model's
output (the rules message instructs it to cite result ids), not a
code-enforced guarantee; the exit criteria in docs/phase-24a.md test it as
instructed behavior against a fixture provider, not as a hard invariant.
