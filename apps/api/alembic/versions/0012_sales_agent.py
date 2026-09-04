"""add sales_leads and sales_outreach_drafts tables for the Sales agent

Revision ID: 0012_sales_agent
Revises: 0011_market_intelligence
Create Date: 2026-09-04
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_sales_agent"
down_revision = "0011_market_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=160), nullable=True),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("consent_basis", sa.String(length=64), nullable=False),
        sa.Column("fit_score", sa.Float(), nullable=True),
        sa.Column("qualification_summary", sa.Text(), nullable=True),
        sa.Column("suggested_next_step", sa.Text(), nullable=True),
        sa.Column("scheduled_call_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("call_prep_summary", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sales_leads_lead_type", "sales_leads", ["lead_type"])
    op.create_index("ix_sales_leads_status", "sales_leads", ["status"])
    op.create_index("ix_sales_leads_email", "sales_leads", ["email"])

    op.create_table(
        "sales_outreach_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_approval"),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sales_outreach_drafts_lead_id", "sales_outreach_drafts", ["lead_id"])
    op.create_index("ix_sales_outreach_drafts_status", "sales_outreach_drafts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_sales_outreach_drafts_status", table_name="sales_outreach_drafts")
    op.drop_index("ix_sales_outreach_drafts_lead_id", table_name="sales_outreach_drafts")
    op.drop_table("sales_outreach_drafts")

    op.drop_index("ix_sales_leads_email", table_name="sales_leads")
    op.drop_index("ix_sales_leads_status", table_name="sales_leads")
    op.drop_index("ix_sales_leads_lead_type", table_name="sales_leads")
    op.drop_table("sales_leads")
