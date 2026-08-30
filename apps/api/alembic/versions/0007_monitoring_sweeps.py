"""add monitoring sweeps table for the proactive Production Monitor agent

Revision ID: 0007_monitoring_sweeps
Revises: 0006_investigation_chaining
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_monitoring_sweeps"
down_revision = "0006_investigation_chaining"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitoring_sweeps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("system", sa.String(length=120), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("event_action", sa.String(length=16), nullable=True),
        sa.Column("created_event_id", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("turns_used", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_monitoring_sweeps_system", "monitoring_sweeps", ["system"])
    op.create_index("ix_monitoring_sweeps_environment", "monitoring_sweeps", ["environment"])
    op.create_index("ix_monitoring_sweeps_status", "monitoring_sweeps", ["status"])
    op.create_index("ix_monitoring_sweeps_created_event_id", "monitoring_sweeps", ["created_event_id"])


def downgrade() -> None:
    op.drop_index("ix_monitoring_sweeps_created_event_id", table_name="monitoring_sweeps")
    op.drop_index("ix_monitoring_sweeps_status", table_name="monitoring_sweeps")
    op.drop_index("ix_monitoring_sweeps_environment", table_name="monitoring_sweeps")
    op.drop_index("ix_monitoring_sweeps_system", table_name="monitoring_sweeps")
    op.drop_table("monitoring_sweeps")
