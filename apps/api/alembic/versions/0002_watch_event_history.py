"""extend VOLT WATCH event history

Revision ID: 0002_watch_event_history
Revises: 0001_initial_schema
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_watch_event_history"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("system_id", sa.String(120), nullable=True))
    op.add_column("events", sa.Column("system_name", sa.String(160), nullable=True))
    op.add_column("events", sa.Column("environment", sa.String(32), nullable=False, server_default="production"))
    op.add_column("events", sa.Column("severity", sa.String(32), nullable=True))
    op.add_column("events", sa.Column("event_type", sa.String(120), nullable=True))
    op.add_column("events", sa.Column("title", sa.String(255), nullable=True))
    op.add_column("events", sa.Column("status", sa.String(32), nullable=False, server_default="active"))
    op.add_column("events", sa.Column("source", sa.String(120), nullable=True))
    op.add_column("events", sa.Column("metadata", sa.JSON(), nullable=True))
    op.add_column("events", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")))
    op.add_column("events", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")))
    op.add_column("events", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE events SET system_id = system WHERE system_id IS NULL")
    op.execute("UPDATE events SET system_name = system WHERE system_name IS NULL")
    op.execute("UPDATE events SET severity = CASE level WHEN 'CRITICAL' THEN 'critical' WHEN 'ERROR' THEN 'high' WHEN 'WARNING' THEN 'medium' ELSE 'info' END WHERE severity IS NULL")
    op.execute("UPDATE events SET created_at = received_at WHERE created_at IS NULL")
    op.execute("UPDATE events SET updated_at = received_at WHERE updated_at IS NULL")
    op.create_index("ix_events_system_id", "events", ["system_id"])
    op.create_index("ix_events_environment", "events", ["environment"])
    op.create_index("ix_events_severity", "events", ["severity"])
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_status", "events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_events_status", table_name="events")
    op.drop_index("ix_events_event_type", table_name="events")
    op.drop_index("ix_events_severity", table_name="events")
    op.drop_index("ix_events_environment", table_name="events")
    op.drop_index("ix_events_system_id", table_name="events")
    for column in ["resolved_at", "updated_at", "created_at", "metadata", "source", "status", "title", "event_type", "severity", "environment", "system_name", "system_id"]:
        op.drop_column("events", column)
