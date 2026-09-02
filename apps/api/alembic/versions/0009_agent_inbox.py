"""add agent inbox table for generic agent-to-agent message dispatch

Revision ID: 0009_agent_inbox
Revises: 0008_telegram_schedules
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_agent_inbox"
down_revision = "0008_telegram_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_inbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sender", sa.String(length=64), nullable=False),
        sa.Column("recipient", sa.String(length=64), nullable=False),
        sa.Column("message_type", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_inbox_sender", "agent_inbox", ["sender"])
    op.create_index("ix_agent_inbox_recipient", "agent_inbox", ["recipient"])
    op.create_index("ix_agent_inbox_message_type", "agent_inbox", ["message_type"])
    op.create_index("ix_agent_inbox_status", "agent_inbox", ["status"])


def downgrade() -> None:
    op.drop_index("ix_agent_inbox_status", table_name="agent_inbox")
    op.drop_index("ix_agent_inbox_message_type", table_name="agent_inbox")
    op.drop_index("ix_agent_inbox_recipient", table_name="agent_inbox")
    op.drop_index("ix_agent_inbox_sender", table_name="agent_inbox")
    op.drop_table("agent_inbox")
