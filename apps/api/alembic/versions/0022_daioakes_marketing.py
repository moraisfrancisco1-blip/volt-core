"""add dai_oakes_marketing_content table for the Dai Oakes content marketing agent

Revision ID: 0022_daioakes_marketing
Revises: 0021_dai_oakes_intel_reports
Create Date: 2026-09-14

Note: revision id kept well under 32 chars -- alembic_version.version_num is
VARCHAR(32) on Postgres, and a revision id that exceeds it crashed production for
three days after the 0021 migration (see that file's own note).
"""

from alembic import op
import sqlalchemy as sa

revision = "0022_daioakes_marketing"
down_revision = "0021_dai_oakes_intel_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dai_oakes_marketing_content",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("source_facts", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_approval"),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_dai_oakes_marketing_content_status", "dai_oakes_marketing_content", ["status"])


def downgrade() -> None:
    op.drop_index("ix_dai_oakes_marketing_content_status", table_name="dai_oakes_marketing_content")
    op.drop_table("dai_oakes_marketing_content")
