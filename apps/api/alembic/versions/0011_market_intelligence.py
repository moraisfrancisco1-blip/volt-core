"""add market_intelligence_reports table for the weekly Market Intelligence agent

Revision ID: 0011_market_intelligence
Revises: 0010_sandbox_results
Create Date: 2026-09-04
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_market_intelligence"
down_revision = "0010_sandbox_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_intelligence_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("competitors_summary", sa.Text(), nullable=True),
        sa.Column("regulation_summary", sa.Text(), nullable=True),
        sa.Column("price_signals_summary", sa.Text(), nullable=True),
        sa.Column("industry_news_summary", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("turns_used", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("telegram_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_market_intelligence_reports_status", "market_intelligence_reports", ["status"])


def downgrade() -> None:
    op.drop_index("ix_market_intelligence_reports_status", table_name="market_intelligence_reports")
    op.drop_table("market_intelligence_reports")
