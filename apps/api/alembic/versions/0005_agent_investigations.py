"""add agent investigations table

Revision ID: 0005_agent_investigations
Revises: 0004_voice_call_confirmation
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_agent_investigations"
down_revision = "0004_voice_call_confirmation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_investigations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("escalation_id", sa.Integer(), nullable=False),
        sa.Column("investigation_type", sa.String(length=64), nullable=False, server_default="voice_call_failure"),
        sa.Column("system", sa.String(length=120), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("recommended_next_step", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("is_known_pattern", sa.Boolean(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("turns_used", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_investigations_event_id", "agent_investigations", ["event_id"])
    op.create_index("ix_agent_investigations_escalation_id", "agent_investigations", ["escalation_id"])
    op.create_index("ix_agent_investigations_investigation_type", "agent_investigations", ["investigation_type"])
    op.create_index("ix_agent_investigations_system", "agent_investigations", ["system"])
    op.create_index("ix_agent_investigations_environment", "agent_investigations", ["environment"])
    op.create_index("ix_agent_investigations_status", "agent_investigations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_agent_investigations_status", table_name="agent_investigations")
    op.drop_index("ix_agent_investigations_environment", table_name="agent_investigations")
    op.drop_index("ix_agent_investigations_system", table_name="agent_investigations")
    op.drop_index("ix_agent_investigations_investigation_type", table_name="agent_investigations")
    op.drop_index("ix_agent_investigations_escalation_id", table_name="agent_investigations")
    op.drop_index("ix_agent_investigations_event_id", table_name="agent_investigations")
    op.drop_table("agent_investigations")
