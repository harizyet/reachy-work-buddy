"""Reply tone preset for the assistant persona."""
from alembic import op

revision = "017_persona_tone"
down_revision = "016_alarm_volume"


def upgrade():
    op.get_bind().exec_driver_sql("ALTER TABLE persona_config ADD COLUMN tone TEXT NOT NULL DEFAULT 'default'")


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
