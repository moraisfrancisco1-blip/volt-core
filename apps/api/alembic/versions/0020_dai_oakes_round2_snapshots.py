"""add dai_oakes_bookings_snapshots, dai_oakes_clients_snapshots and
dai_oakes_system_health_snapshots tables for Round 2 of the Dai Oakes connector

Revision ID: 0020_dai_oakes_round2_snapshots
Revises: 0019_dai_oakes_payments
Create Date: 2026-09-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0020_dai_oakes_round2_snapshots"
down_revision = "0019_dai_oakes_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dai_oakes_bookings_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("total_bookings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("today_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_7_days_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("by_status", sa.JSON(), nullable=True),
        sa.Column("by_location", sa.JSON(), nullable=True),
        sa.Column("by_deposit_status", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "dai_oakes_clients_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("total_clients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_clients_last_30_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "dai_oakes_system_health_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("webhooks_failed_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("webhooks_processed_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("webhooks_failed_last_24h", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("emails_sent_last_24h", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("emails_failed_last_24h", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_sent_last_24h", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_failed_last_24h", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("admin_actions_last_24h", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("login_rate_limit_hits_last_24h", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("dai_oakes_system_health_snapshots")
    op.drop_table("dai_oakes_clients_snapshots")
    op.drop_table("dai_oakes_bookings_snapshots")
