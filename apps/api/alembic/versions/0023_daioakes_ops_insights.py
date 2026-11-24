"""add dai_oakes_operations_insights table for the Dai Oakes operations insights agent

Revision ID: 0023_daioakes_ops_insights
Revises: 0022_daioakes_marketing
Create Date: 2026-11-24

Note: revision id kept under 32 chars (alembic_version.version_num is VARCHAR(32)).
"""

from alembic import op
import sqlalchemy as sa

revision = "0023_daioakes_ops_insights"
down_revision = "0022_daioakes_marketing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dai_oakes_operations_insights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dai_oakes_operations_insights_kind", "dai_oakes_operations_insights", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_dai_oakes_operations_insights_kind", table_name="dai_oakes_operations_insights")
    op.drop_table("dai_oakes_operations_insights")
