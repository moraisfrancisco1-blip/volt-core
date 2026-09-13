"""add dai_oakes_intelligence_reports table for the dedicated Dai Oakes Intelligence agent

Revision ID: 0021_dai_oakes_intel_reports
Revises: 0020_dai_oakes_round2_snapshots
Create Date: 2026-09-10

Note: the original revision id ("0021_dai_oakes_intelligence_reports", 35 chars) exceeded
alembic_version.version_num's VARCHAR(32) column, which crashed the production deploy
(psycopg2.errors.StringDataRightTruncation) before uvicorn ever started. Shortened here,
before this revision had ever successfully applied anywhere.
"""

from alembic import op
import sqlalchemy as sa

revision = "0021_dai_oakes_intel_reports"
down_revision = "0020_dai_oakes_round2_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dai_oakes_intelligence_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("payments_summary", sa.Text(), nullable=True),
        sa.Column("bookings_summary", sa.Text(), nullable=True),
        sa.Column("clients_summary", sa.Text(), nullable=True),
        sa.Column("system_health_summary", sa.Text(), nullable=True),
        sa.Column("alerts_summary", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("turns_used", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("telegram_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_dai_oakes_intelligence_reports_status", "dai_oakes_intelligence_reports", ["status"])


def downgrade() -> None:
    op.drop_index("ix_dai_oakes_intelligence_reports_status", table_name="dai_oakes_intelligence_reports")
    op.drop_table("dai_oakes_intelligence_reports")
