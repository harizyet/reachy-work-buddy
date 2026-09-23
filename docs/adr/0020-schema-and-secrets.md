# ADR 0020: Versioned schema and core-owned credentials

- Status: Accepted
- Date: 2026-09-23

## Decision

Phase 23 begins with one Alembic history for the shared Postgres database.
The migration command ships in companion-core's image; it imports no hub
runtime. SQL stores retain their interfaces. All production stores check
the exact supported revision instead of running DDL during startup.
Compose gates hub/core on the dedicated migration job.

Revision `001_baseline` freezes the Phase 22 schema. Fresh installations
create it. Legacy adoption requires an explicit flag, a stopped application,
and inspection of table/column types, nullability, defaults, constraints and
indexes. Only documented historical missing columns and tables are repaired.
Unknown drift fails without recording a baseline. Revision `002_secrets`
creates encrypted credentials and converts both LLM roles in the same
transaction as removing plaintext configuration fields. The migration job
serializes with an advisory lock, uses bounded connection/statement/lock
timeouts, and refuses upgrades while other database clients are connected.
Operators must keep old instances stopped throughout cutover; a database
constraint additionally prevents an old writer restoring `api_key` fields.

Core owns the provider-neutral SecretStore protocol and its Postgres
implementation. A caller supplies the transaction for atomic configuration,
reference and credential updates. AES-256-GCM records have a format version,
key ID and random 96-bit nonce, using the maintained
[cryptography AEAD API](https://cryptography.io/en/latest/hazmat/primitives/aead/).
Authenticated associated data binds the record
ID, owner, provider, purpose, version and key ID. LLM settings hold opaque
references; only core resolves them. Hub continues to receive masked settings,
with no decrypt endpoint. Missing/wrong keys and tampering fail closed with
sanitized errors.

Existing LLM settings are deployment-wide, so their credential owner is the
stable internal `owner` identifier, independent of mutable login usernames.
Future account records must supply their actual owner binding through the same
interface. Google-shaped test credentials demonstrate reuse; this ADR does
not implement OAuth or authorize Google account access.

Keys live in a permission-restricted JSON file outside Postgres, distinct from
the hub session-signing key. Core and the migration job mount it; hub does not.
Rotation re-encrypts bounded transactional batches by key ID and can resume
after interruption. Required old keys remain available for retained backups.
There is no automatic destructive downgrade or plaintext fallback.

## Credential inventory

Before this change, persisted provider credentials consisted of local/cloud
LLM keys in `llm_config`. SMTP had no authenticated-credential support or
stored password table. SMTP now resolves an optional SecretStore reference
at dispatch, with STARTTLS required for authentication; environment-injected
passwords remain an explicit bootstrap source and are never persisted.
The consent gate and delayed-dispatch sender call site are unchanged.
Owner password hashes, session signing keys, Telegram tokens, robot tokens,
database passwords and remote UI bearers retain their existing deployment
ownership; this change does not relocate transport/auth secrets into core.

## Ownership and procedures

Hub owns `users`, `sessions`, `robots`, `telegram_chats`, `audit_log`
and `notification_queue`. Core owns `calendar_events`, `tasks`,
`memories`, `document_chunks`, `email_received`, `email_drafts`,
`confirmation_requests`, `llm_config`, `llm_usage_log` and `secrets`.
The deployment job owns `alembic_version`.

See [deployment procedures](../deployment.md#schema-upgrades-and-credential-keys)
and [verification](../verification/phase-23-foundation-2026-09-23.md).
Historical plaintext backups, WAL and old row versions are not erased by a
logical migration. Restrict retention/access and rotate provider credentials
when retiring that exposure. Environment files are not encrypted by this work.
