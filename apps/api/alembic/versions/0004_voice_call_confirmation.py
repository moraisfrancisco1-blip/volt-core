"""add voice call confirmation tracking

Revision ID: 0004_voice_call_confirmation
Revises: 0003_escalation_queue
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_voice_call_confirmation"
down_revision = "0003_escalation_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "escalations",
        sa.Column("call_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "voice_calls",
        sa.Column("call_sid", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "voice_calls",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_voice_calls_call_sid", "voice_calls", ["call_sid"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_voice_calls_call_sid", table_name="voice_calls")
    op.drop_column("voice_calls", "updated_at")
    op.drop_column("voice_calls", "call_sid")
    op.drop_column("escalations", "call_attempts")
