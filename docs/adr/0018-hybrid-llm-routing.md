# ADR 0018: Hybrid local/cloud LLM routing

- Status: Accepted
- Date: 2026-09-22

## Post-acceptance verification

Together AI / `zai-org/GLM-5.3` was subsequently verified end-to-end as the
cloud role on 2026-09-22 in the isolated `phase21togetherverify` stack.
Owner-authenticated hub requests verified manual cloud override and actual
local-failure fallback, with both attempts recorded and credentials masked.
See [hosted-cloud run](../verification/history.md#hosted-cloud-follow-up--2026-09-22) for the run details. This supplements the
original OVMS verification below; the design decision is unchanged.

## Decision

Companion-core owns routing in `llm/router.py`. The pure `role_order`
function selects provider roles, independently of vendor, URL, or model
identity. Both roles use the existing compatible HTTP provider; a native
vendor API requires an OpenAI-compatible endpoint or gateway. No vendor
SDK, quality judge, tool executor, or extra service is introduced.

| Policy | Attempts |
|---|---|
| `local_only` | Local; failures return unavailable |
| `cloud_only` | Cloud only |
| `local_with_cloud_fallback` | Local; cloud only after an actual failure |
| `force_frontier: true` | Cloud only, overriding any standing policy |

Failure means timeout, network/HTTP error, or an empty/malformed completion.
An ordinary valid local answer never triggers fallback based on perceived
quality. Cancellation and usage-store failures do not dispatch another
provider. Each provider has a 60-second total inference deadline; hub allows
130 seconds and browser chat 135 seconds for the two-attempt path. A queued
same-session turn can still exceed the caller's deadline. No automatic
browser retry is added.

`force_frontier` defaults false on hub `InboundMessage`, travels through
`CompanionCoreClient.send_turn`, and reaches core `ConversationTurnRequest`.
Like input modality it is channel-independent request metadata. Only the
generic conversation branch uses routing: deterministic intents and consent
checks remain authoritative, including on a forced turn. A missing requested
provider returns unavailable, never silently changes role. With no providers
and no override, the existing unconfigured echo remains.

## Configuration and disclosure

`cloud` now accepts the same `ProviderConfig`/partial `ProviderPatch` as
`local`. Configuration remains in the existing JSONB row. On first cloud
setup, omitting routing chooses fallback if local exists, otherwise
cloud-only. Explicit routing wins; later provider edits preserve the saved
policy. Cloud policies require cloud configuration; fallback additionally
requires local. Removing a required provider must include a valid new policy.
Empty routing patches retain the saved mode. Omitted keys preserve saved
credentials, explicit null clears them, and replies mask both roles' keys.

The operator UI adds cloud fields and routing selection. First cloud setup
suggests fallback (or cloud-only without local) unless the operator explicitly
chooses a policy. Blank URL and model remove a provider. “Disable all models”
clears both roles and restores local-only. Standing policy applies across
channels. The Chat checkbox sends a one-turn override and resets after
submission, logout, or user change. There is no new per-session stored policy
or Telegram-specific toggle.

Cloud inference receives the same bounded conversation context as local.
The UI says so beside configuration and the override. Delivery privacy labels
still describe response routing; they do not gate transfer to an explicitly
configured cloud provider. Existing trusted-network API and owner-auth rules
remain unchanged. Credentials remain plaintext at rest in Postgres as in
ADR 0016; no keys, prompts, raw exceptions, or responses enter usage records.

## Usage and upgrades

Each actual HTTP attempt records its role, model, returned tokens, latency,
and success/failure. Failed local attempts are retained before successful
cloud fallback. Cloud calls carry nullable `escalation_reason`: `error` for
fallback, `manual` for an override. Normal cloud-only policy calls have no
escalation reason. Missing/unconfigured providers create no fictional calls.

Startup idempotently adds nullable `llm_usage_log.escalation_reason` using
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`; existing records remain null and
existing volumes must not be reset. Reads map by column name. No config-table
migration or dependency change is needed.

`GET /llm/usage` adds `latest_escalation` (reason and UTC timestamp, or null)
within the requested summary window, independent of the recent-entry limit.
The dashboard shows local/cloud calls, errors, token totals, and the latest
reason/time for its 24-hour window. These are usage counts, not cost estimates
or quality measurements.

## Verification

The [implementation history](../verification/history.md) records policy and
accounting tests, Docker/Postgres/OVMS checks, and the subsequent real
Together AI cloud-role verification. That later run completes the original
hosted-provider check without changing this decision.
