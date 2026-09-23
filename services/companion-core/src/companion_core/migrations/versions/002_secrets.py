"""Encrypt both LLM roles atomically with the plaintext removal."""
import json
from uuid import uuid4

from alembic import op
from companion_core.secrets import SecretContext
from pydantic import ValidationError
from sqlalchemy import text

from shared.models.llm import LLMConfig

revision = "002_secrets"
down_revision = "001_baseline"


def upgrade():
    conn = op.get_bind()
    keys = op.get_context().config.attributes["keyring"]
    conn.exec_driver_sql("""
        CREATE TABLE secrets (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, provider TEXT NOT NULL,
            purpose TEXT NOT NULL, key_id TEXT NOT NULL, version INTEGER NOT NULL,
            nonce BYTEA NOT NULL, ciphertext BYTEA NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now())
    """)
    rows = conn.execute(text("SELECT id, config FROM llm_config FOR UPDATE")).all()
    for config_id, config in rows:
        # Validation diagnostics must not embed credential-bearing input.
        try:
            LLMConfig.model_validate(config)
        except ValidationError:
            raise RuntimeError("Invalid legacy LLM configuration; review settings before upgrade") from None
        for role in ("local", "cloud"):
            provider = config.get(role)
            if provider is None:
                continue
            value = provider.pop("api_key", None)
            provider["secret_ref"] = None
            if value is not None:
                ref = str(uuid4())
                ctx = SecretContext("owner", f"llm:{role}", "api_key")
                record = keys.encrypt(ref, ctx, value)
                conn.execute(text("""
                    INSERT INTO secrets (id, owner, provider, purpose, key_id, version, nonce, ciphertext)
                    VALUES (:id,:owner,:provider,:purpose,:key_id,:version,:nonce,:ciphertext)
                """), dict(id=ref, owner=ctx.owner, provider=ctx.provider, purpose=ctx.purpose, **record))
                provider["secret_ref"] = ref
        conn.execute(text("UPDATE llm_config SET config=CAST(:config AS jsonb) WHERE id=:id"),
                     {"config": json.dumps(config), "id": config_id})
    # Old binaries cannot put plaintext back even if accidentally restarted.
    conn.exec_driver_sql("""
        ALTER TABLE llm_config ADD CONSTRAINT llm_config_no_plaintext CHECK (
            NOT jsonb_path_exists(config, '$.**.api_key'))
    """)


def downgrade():
    raise RuntimeError("Restore a tested backup; decrypting credentials into plaintext is unsupported")
