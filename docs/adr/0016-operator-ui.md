# ADR 0016: Operator UI, owner login, and configurable inference

- Status: Accepted
- Date: 2026-09-22

## Context

Phase 19 needs live component monitoring, mode/DND controls, and editable
LLM settings. Previously the generic conversation reply was an echo and
browser telepresence required a shared token in localStorage. A utilization
view needs actual inference and usage accounting.

## Decision

`reachy-hub` owns the static dashboard at `/ui/` (through Caddy:
`/hub/ui/`), login, and authenticated proxies. `companion-core` owns LLM
configuration, inference, and usage. Services communicate over HTTP; shared
models and route constants live under `shared/`. The frontend is plain
HTML/JS/CSS, with no build step or third-party assets.

### Owner access

The first startup with `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and
`SESSION_SECRET_KEY` bootstraps a single owner in the new `users` table.
Passwords use randomly salted PBKDF2-HMAC-SHA256 (600,000 rounds), compared
in constant time; password work runs off the event loop. Later startups
never overwrite the account. There is no signup or password-reset API.

Starlette SessionMiddleware signs a 12-hour, HttpOnly, SameSite=Strict
cookie. `SESSION_COOKIE_SECURE=true` enables HTTPS-only cookies; local
Compose HTTP defaults to false. The existing deployment remains a trusted
homelab/VPN deployment, not an Internet-facing identity service. Logout
clears the browser cookie; signed cookies have no server-side revocation
list. Rotating the signing key invalidates all existing cookies.

`POST /auth/login`, `POST /auth/logout`, and `GET /auth/me` provide the
browser lifecycle. Cookie-authenticated mutations and login/logout require
`X-Reachy-CSRF: 1`; no cross-origin CORS permission is granted. The custom
header prevents cross-site form requests and requires a browser preflight
for foreign origins. Validation errors on credential-bearing routes omit
input values. Telepresence now uses the owner cookie and removes the old
localStorage token.

`require_remote_auth` accepts either the existing `REMOTE_UI_TOKEN` bearer
or an owner session. No configured mechanism returns 503; missing or
invalid credentials return 401 once configured. Mode/DND/privacy-context
mutations, status, settings, and usage are gated. Existing conversational
channels retain their previous access contract. This is not a wholesale
auth retrofit of historical APIs.

Caddy explicitly blocks `/core/settings/*` and `/core/llm/*`: otherwise the
existing core debug proxy would bypass the new hub gates. Core's direct
endpoints remain internal-network-only, like its existing store APIs.

### Inference and accounting

One `OpenAICompatibleChatProvider` posts non-streaming requests to
`{base_url}/chat/completions`, optionally with a bearer key. The primary
local target is [OVMS's chat completion endpoint](https://docs.openvino.ai/2026/model-server/ovms_docs_rest_api_chat.html).
The model must match the server's configured model name. No vendor SDK or
OVMS-specific transport is needed. Redirects are disabled to avoid
forwarding a configured credential to another endpoint.

Configuration is role-based: `local`, reserved `cloud: null`, and
`routing.mode: local_only`. Phase 19 configures the local slot; that slot
may point at any compatible endpoint, including a hosted endpoint. Cloud
routing and fallback are Phase 21, not enabled here. The config is stored
as one JSONB object in the singleton `llm_config` row. Partial PUTs merge
provider fields atomically; omitted keys retain credentials, explicit
`api_key: null` removes a key, and `local: null` disables inference. GET and
PUT responses mask keys (only the final four characters for keys longer
than four). Keys are plaintext at rest in Postgres, a documented limitation;
access to the database and its backups is access to these credentials.

Only the generic conversation branch invokes the provider. Deterministic
calendar/task/memory/email/consent handlers keep their authority; the LLM
has no tool executor. Without configuration the old echo fallback remains.
A failed provider call produces an honest unavailable reply, not an echo
pretending to be inference. Requests time out after 60 seconds; the hub's
conversation request allows 70 seconds, while health probes retain short
timeouts.

The in-memory transcript now includes assistant messages and supplies the
most recent 39 messages, beginning with a user turn. Same-session turns
serialize so concurrent channels cannot interleave replies. Generated
follow-ups preserve the strongest prior privacy label in the conversation
and classify the current input/output; a private calendar/email reply must
not become public just because the next prompt says "tell me more".
This remains a conservative keyword/metadata policy, not semantic privacy
classification. Transcripts still reset on core restart.

`llm_usage_log` records time, role, model, returned token counts, latency,
and success/failure for every attempted call. It stores neither prompts nor
completions nor raw exception bodies. Missing provider token counts remain
null and are reported as unreported calls rather than invented estimates.
Usage summaries use the full requested time window, independently of the
recent-entry limit, and include per-role totals. No cost or GPU utilization
is inferred from token counts.

### Monitoring

`GET /status` concurrently probes core `/health` and each registered robot's
existing state endpoint, and reads masked LLM configuration and usage.
Failure of one probe does not hide the other components. Hub health is the
successful response itself. Telegram shows **configured**, not healthy;
actual poll-loop health belongs to Phase 20. The dashboard refreshes every
10 seconds and shows stale/unavailable states explicitly. Audit and queued
notifications use their existing per-user endpoints, not new copies in
`/status`. Session controls require an existing conversation session.

## Consequences

- Adds three tables (`users`, `llm_config`, `llm_usage_log`) and one small
  dependency (`itsdangerous`). These are new tables, so upgrading an
  otherwise current Phase 18 database needs no volume deletion. Older
  schema caveats from earlier phases still apply.
- Authentication/settings/usage survive service restarts. LLM settings
  changes take effect on the next call without redeployment.
- No Phase 20 chat view or Phase 21 hybrid-routing engine is included.
- Real deployment verification used Chromium, Caddy, Postgres, and the
  existing OVMS `OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov` model. A hosted
  paid provider was not needed for this phase's local-inference criterion.
