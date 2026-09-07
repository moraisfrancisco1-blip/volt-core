"""add platform_status_summary to market_intelligence_reports and deal_expansion_signals table

Revision ID: 0018_voltaris_real_data
Revises: 0017_customer_agent
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa

revision = "0018_voltaris_real_data"
down_revision = "0017_customer_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_intelligence_reports", sa.Column("platform_status_summary", sa.Text(), nullable=True))

    op.create_table(
        "deal_expansion_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(length=120), nullable=False),
        sa.Column("tenant_name", sa.String(length=255), nullable=False),
        sa.Column("current_plan", sa.String(length=120), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="flagged"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_deal_expansion_signals_tenant_id", "deal_expansion_signals", ["tenant_id"], unique=True)
    op.create_index("ix_deal_expansion_signals_status", "deal_expansion_signals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_deal_expansion_signals_status", table_name="deal_expansion_signals")
    op.drop_index("ix_deal_expansion_signals_tenant_id", table_name="deal_expansion_signals")
    op.drop_table("deal_expansion_signals")
    op.drop_column("market_intelligence_reports", "platform_status_summary")
