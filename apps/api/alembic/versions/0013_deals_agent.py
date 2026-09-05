"""add deals and deal_proposals tables for the Deals agent

Revision ID: 0013_deals_agent
Revises: 0012_sales_agent
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0013_deals_agent"
down_revision = "0012_sales_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False, server_default="qualified"),
        sa.Column("suggested_stage", sa.String(length=32), nullable=True),
        sa.Column("suggested_stage_reason", sa.Text(), nullable=True),
        sa.Column("stage_changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_deals_lead_id", "deals", ["lead_id"])
    op.create_index("ix_deals_stage", "deals", ["stage"])

    op.create_table(
        "deal_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("price_summary", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_approval"),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_deal_proposals_deal_id", "deal_proposals", ["deal_id"])
    op.create_index("ix_deal_proposals_status", "deal_proposals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_deal_proposals_status", table_name="deal_proposals")
    op.drop_index("ix_deal_proposals_deal_id", table_name="deal_proposals")
    op.drop_table("deal_proposals")

    op.drop_index("ix_deals_stage", table_name="deals")
    op.drop_index("ix_deals_lead_id", table_name="deals")
    op.drop_table("deals")
