"""Owner-armed spoken wake monitoring per robot (Phase 24g, ADR 0023)."""
from alembic import op

revision = "009_wake_arm"
down_revision = "008_assistant_context"


def upgrade():
    op.get_bind().exec_driver_sql("""
        CREATE TABLE robot_wake_arm (
            robot_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            arm_id TEXT NOT NULL,
            armed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)


def downgrade():
    raise RuntimeError("Restore a tested backup; automatic destructive downgrade is unsupported")
