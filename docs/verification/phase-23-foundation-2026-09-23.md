# Phase 23 foundation verification — 2026-09-23

Scope: schema migrations, shared core SecretStore, LLM credential cutover,
and SMTP credential resolution. Google OAuth/Accounts are not implemented.
No production database, credentials, external account or robot was changed.

## Automated evidence

Final fast suite with real migration tests enabled:

```text
349 passed, 2 skipped, 10 deselected, 2 warnings in 32.67s
```

The two skips require espeak-ng, absent from PATH; ten slow speech/model tests
were deliberately deselected. Two existing Starlette/httpx deprecation warnings
remain. An initial sandboxed TestClient run stalled and was interrupted;
the successful run used local socket access. Ruff, `git diff --check` and relative documentation links/anchors
passed.

The 15 focused migration/secret tests passed separately against real
`pgvector/pgvector:pg16`, in named disposable project
`reachy-phase23-verify`. Each database test creates and drops a unique database.

| Check | Result |
|---|---|
| Fresh install; repeat/no-op upgrade | PASS |
| Historical session, audit, soft-delete, send-delay and usage columns | PASS; rows preserved |
| Unknown columns/tables, missing required columns, nullability and constraints | PASS; refused without partial adoption |
| Concurrent migration exclusion; old client connection refusal | PASS |
| Injected failure during second LLM credential migration | PASS; plaintext baseline/revision restored atomically, retry succeeded |
| Both LLM roles; masking; omitted key; null deletion; replacement; restart | PASS |
| Concurrent partial settings updates | PASS; both edits retained |
| Old writer attempts plaintext update | PASS; database check constraint refused |
| Owner/password persistence | PASS |
| Owner/provider/purpose/reference binding; ciphertext/nonce/version tampering | PASS |
| Wrong key and inaccessible/malformed key file | PASS; sanitized refusal |
| Interrupted one-record rotation batches; resume | PASS |
| Real pg_dump/pg_restore before and after rotation | PASS; matching old/new keys recover, wrong key denied |
| Google-shaped refresh-token and SMTP contexts | PASS; same SecretStore, fixture values |
| SMTP sender resolves reference, requires STARTTLS, refuses missing ref | PASS; send transport captured, no mail sent |

## Built-image and HTTP evidence

Named disposable project `reachy-phase23-appverify` built core, hub and
migration images using their isolated package installs. A legacy database
was seeded with an owner password hash, session, usage entry and fixture LLM
key. The actual migration image adopted it with `--adopt-legacy`, then
Compose's migration dependency gate started core/hub/Caddy successfully.

Real HTTP checks through Caddy verified owner login, preserved session/usage,
masked settings, omitted-key updates, CSRF rejection and conversation inference
against a local HTTP fixture that required the migrated bearer credential.
The same checks passed after restarting hub/core and with the final rebuilt
core/migration images. An immediate probe during recreation returned 502
because hub was ready before core; waiting for both health endpoints resolved
it. The existing launcher still waits only on hub health, so that message alone
is not evidence of core readiness. This is real container,
database and HTTP evidence, **not hosted-model or Google-account acceptance**.

Active-row inspection reported revision `002_secrets`, zero plaintext
`api_key` fields and one encrypted credential in the fixture deployment.
The fixture provider key was absent from collected stack logs.

Both disposable Compose projects and their volumes were removed after
verification; the pre-existing OVMS container was left running. Temporary
fixture key/env files were deleted.

## Limits and continuation

Existing production deployments still require the documented backup, key
provisioning and coordinated cutover. No production upgrade was attempted.
No physical checks, Nano launcher changes, Google API requests or real SMTP
sends occurred. Browser UI assets were unchanged.

Continue Phase 23 with the account-integration ADR, owner-bound OAuth,
Accounts UI and read-only adapters. Real Google refresh/revoke/reconnect,
production audience requirements and the later physical acceptance repeat
remain open. See [the phase plan](../phase-22-23.md) and
[deployment procedure](../deployment.md#schema-upgrades-and-credential-keys).
