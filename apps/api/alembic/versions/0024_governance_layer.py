"""add llm_usage, output_audit_findings and daily_briefings for the governance layer

Revision ID: 0024_governance_layer
Revises: 0023_daioakes_ops_insights
Create Date: 2026-11-24

Note: revision id kept under 32 chars (alembic_version.version_num is VARCHAR(32)).
"""

from alembic import op
import sqlalchemy as sa

revision = "0024_governance_layer"
down_revision = "0023_daioakes_ops_insights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=96), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_llm_usage_agent", "llm_usage", ["agent"])
    op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"])
    op.create_table(
        "output_audit_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("rule", sa.String(length=48), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("excerpt", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "source_id", "rule", name="uq_output_audit_source_rule"),
    )
    op.create_index("ix_output_audit_findings_source", "output_audit_findings", ["source"])
    op.create_index("ix_output_audit_findings_status", "output_audit_findings", ["status"])
    op.create_table(
        "daily_briefings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("attention_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("daily_briefings")
    op.drop_index("ix_output_audit_findings_status", table_name="output_audit_findings")
    op.drop_index("ix_output_audit_findings_source", table_name="output_audit_findings")
    op.drop_table("output_audit_findings")
    op.drop_index("ix_llm_usage_created_at", table_name="llm_usage")
    op.drop_index("ix_llm_usage_agent", table_name="llm_usage")
    op.drop_table("llm_usage")
