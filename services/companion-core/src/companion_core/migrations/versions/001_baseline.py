"""Validated adoption of schemas through Phase 22."""
from alembic import op
from companion_core.migrations.legacy import adopt

revision = "001_baseline"
down_revision = None


def upgrade():
    adopt(op.get_bind(), op.get_context().config.attributes.get("adopt_legacy", False))


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
