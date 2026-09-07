"""add backoffice_reconciliations and backoffice_reports tables for the Back Office agent

Revision ID: 0016_backoffice_agent
Revises: 0015_operations_agent
Create Date: 2026-09-08
"""

from alembic import op
import sqlalchemy as sa

revision = "0016_backoffice_agent"
down_revision = "0015_operations_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backoffice_reconciliations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("data_source", sa.String(length=32), nullable=False),
        sa.Column("match_found", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("stripe_invoice_id", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_backoffice_reconciliations_deal_id", "backoffice_reconciliations", ["deal_id"], unique=True)

    op.create_table(
        "backoffice_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data_source", sa.String(length=32), nullable=False),
        sa.Column("deals_closed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deals_matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deals_unmatched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("backoffice_reports")
    op.drop_index("ix_backoffice_reconciliations_deal_id", table_name="backoffice_reconciliations")
    op.drop_table("backoffice_reconciliations")
