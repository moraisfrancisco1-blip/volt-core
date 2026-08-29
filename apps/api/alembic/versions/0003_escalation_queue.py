"""add persistent escalation queue

Revision ID: 0003_escalation_queue
Revises: 0002_watch_event_history
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_escalation_queue"
down_revision = "0002_watch_event_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "escalations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("system", sa.String(length=120), nullable=False),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_escalations_event_id", "escalations", ["event_id"])
    op.create_index("ix_escalations_priority", "escalations", ["priority"])
    op.create_index("ix_escalations_status", "escalations", ["status"])
    op.execute(
        """
        INSERT INTO escalations (event_id, system, priority, action, status)
        SELECT e.id, e.system, e.priority, e.recommended_action,
               CASE WHEN e.status = 'resolved' THEN 'completed' ELSE 'queued' END
        FROM events e
        WHERE NOT EXISTS (
            SELECT 1 FROM escalations q WHERE q.event_id = e.id
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_escalations_status", table_name="escalations")
    op.drop_index("ix_escalations_priority", table_name="escalations")
    op.drop_index("ix_escalations_event_id", table_name="escalations")
    op.drop_table("escalations")
