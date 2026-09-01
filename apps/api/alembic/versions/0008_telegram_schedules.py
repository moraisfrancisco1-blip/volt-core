"""add telegram schedules table for Telegram-driven recurring sweep/investigate requests

Revision ID: 0008_telegram_schedules
Revises: 0007_monitoring_sweeps
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_telegram_schedules"
down_revision = "0007_monitoring_sweeps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=120), nullable=True),
        sa.Column("time_of_day", sa.String(length=5), nullable=True),
        sa.Column("interval_hours", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_telegram_schedules_active", "telegram_schedules", ["active"])


def downgrade() -> None:
    op.drop_index("ix_telegram_schedules_active", table_name="telegram_schedules")
    op.drop_table("telegram_schedules")
