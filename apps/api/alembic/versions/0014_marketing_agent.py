"""add marketing_content table for the Marketing agent

Revision ID: 0014_marketing_agent
Revises: 0013_deals_agent
Create Date: 2026-09-05
"""

from alembic import op
import sqlalchemy as sa

revision = "0014_marketing_agent"
down_revision = "0013_deals_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketing_content",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("audience", sa.String(length=32), nullable=False),
        sa.Column("parent_content_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_facts", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_approval"),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_marketing_content_content_type", "marketing_content", ["content_type"])
    op.create_index("ix_marketing_content_parent_content_id", "marketing_content", ["parent_content_id"])
    op.create_index("ix_marketing_content_status", "marketing_content", ["status"])


def downgrade() -> None:
    op.drop_index("ix_marketing_content_status", table_name="marketing_content")
    op.drop_index("ix_marketing_content_parent_content_id", table_name="marketing_content")
    op.drop_index("ix_marketing_content_content_type", table_name="marketing_content")
    op.drop_table("marketing_content")
