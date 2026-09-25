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
operator points Settings → Web search at it with a non-Off policy, so a
deployment that never touches this feature runs it for nothing rather than
being forced to install it separately.

This container's own server secret (`SEARXNG_SECRET`, mapped from the
`SEARXNG_SECRET_KEY` deployment variable in `docker-compose.yml`) is
infrastructure the deployment owns, not a user credential: Phase 24
cleanup made `scripts/start-homelab.sh` generate and persist it itself
(`deploy/homelab/.env.searxng-secret`, `0600`) the first time the stack
starts, rather than asking every operator to invent or paste in a random
value. It deliberately does **not** go through `SecretStore` (below) —
that store is for credentials Companion Core resolves at LLM-call time on
behalf of a configured provider; this secret belongs entirely to the
container's own bootstrap and Companion Core never reads or stores it.
The bundled provider option ("Built-in SearXNG" in Settings → Web search)
also needs no Base URL from the operator: `companion_core/websearch/
provider.py` hardcodes the container's internal compose address
(`http://searxng:8080`) for that provider kind. An **External SearXNG**
(or other hosted) provider still supplies its own Base URL/API key, which
follows the `SecretStore` path below exactly as before.

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

## Addendum: hosted Brave provider and spoken replies (Phase 24d, 2026-09-24)

Live robot conversation showed that the bundled SearXNG's scraped engines
are not dependable from a single home address. Google and Brave suspended it
after CAPTCHAs, and Bing returned unrelated pages, so grounded answers were
wrong. `SearchProviderKind.BRAVE` adds the hosted provider this ADR already
anticipated: a fixed Brave Search API endpoint, a required owner key in
SecretStore (`websearch:brave`), and results normalized to the same
untrusted `SearchResult` shape. The rest of the grounding pipeline is
unchanged.

Citation stays a prompting requirement in the reply text. For speech,
reachy-hub removes `[S…]` markers and markdown symbols before synthesis
(`reachy_hub.tts.spoken_text`). Core adds a short-plain-reply instruction to
VOICE-modality generic turns only.

## Addendum: hosted provider rotation within free tiers (Phase 24d, 2026-09-25)

A single hosted provider on its free tier would run out of monthly quota,
and falling back to scraped SearXNG from one home address brings back the
blocking problem above. The owner therefore chose to use Brave, Exa and
Tavily together, with SearXNG demoted to a last-resort fallback.
`search_config.provider` became `fallback` (`builtin_searxng`, `searxng`
or `none`). Migration `007_search_providers` adds `search_provider`
(enabled flag, `secret_ref` and monthly limit per hosted provider) and
`search_usage` (count per provider per UTC calendar month).

Each search-warranted turn still performs one search. The order is fixed
code, like the search decision itself (`websearch/rotation.py`): enabled
hosted providers sorted by the share of their monthly limit already used,
ties in declaration order. This spreads load in proportion to each free
allowance instead of draining one provider first. A call is reserved with a
single conditional upsert before it is sent. A provider at its limit is
never called, and a failed call still counts, because it may still be
billed. Errors fail over to the next tier. A plan-limit response marks
that provider used up for the month. A 429 is treated as a transient rate
limit. The whole chain is bounded by twice the per-provider timeout, so
failovers can't hold a voice turn for tiers × timeout. The failure notice
above still applies when every tier fails.

Limits are Reachy's own counts, not the provider's billing state. Brave
bills the card on file beyond its monthly credit, so its limit is the only
safeguard. That is why the defaults (900) sit below each allowance and are
owner-editable.

## Addendum: follow-up searches and owner context (Phase 24d, 2026-09-25)

A live multi-turn test showed follow-ups ("When was it released?") never
searched under Auto, and a chained follow-up lost its subject because only
the raw previous user turn was added to the query. Both rules stay fixed
code in `websearch/policy.py`:

- Under Auto, a follow-up (an explicit reference word, or a question of at
  most four words) searches when the immediately preceding user turn
  searched. Any turn that doesn't search ends the thread.
- A follow-up's query is prefixed with the thread's **search topic**: the
  query its last self-contained search sent, which the provider has already
  received. With no active topic, the previous user turn is added only for
  an explicit reference word; a short self-contained question no longer
  carries an unrelated prior turn. Both keep the original privacy intent:
  nothing from the conversation reaches the provider beyond the current turn
  and what was already sent.
- A weather query that names no place gets the owner's configured location
  appended (`localize_query`). This sends the location to the search
  provider, which the operator UI discloses.

Every generic conversation turn now carries a code-authored system message
with the owner's local date, time and location (`persona/context.py`), from
the persona's `location` and `timezone` (migration `008_assistant_context`).
The grounding rules also tell the model to answer from the results directly
(a weather reply is a short summary of conditions, temperature and chance of
rain) rather than pointing the user at links.
