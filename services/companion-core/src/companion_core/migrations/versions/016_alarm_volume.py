"""Phase 38 alarm volume: per-alarm playback gain in percent (100 = unchanged)."""
from alembic import op

revision = '016_alarm_volume'
down_revision = '015_alarms'


def upgrade():
    op.get_bind().exec_driver_sql('ALTER TABLE alarms ADD COLUMN volume INTEGER NOT NULL DEFAULT 100')


def downgrade():
    raise RuntimeError('Restore a tested backup; automatic destructive downgrade is unsupported')
