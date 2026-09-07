"""add customer_queries, customer_response_drafts and customer_query_patterns tables for the Customer agent

Revision ID: 0017_customer_agent
Revises: 0016_backoffice_agent
Create Date: 2026-09-08
"""

from alembic import op
import sqlalchemy as sa

revision = "0017_customer_agent"
down_revision = "0016_backoffice_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_queries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("customer_name", sa.String(length=160), nullable=True),
        sa.Column("customer_email", sa.String(length=255), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=True),
        sa.Column("sensitive_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_customer_queries_customer_email", "customer_queries", ["customer_email"])
    op.create_index("ix_customer_queries_classification", "customer_queries", ["classification"])
    op.create_index("ix_customer_queries_status", "customer_queries", ["status"])

    op.create_table(
        "customer_response_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("query_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_approval"),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_customer_response_drafts_query_id", "customer_response_drafts", ["query_id"])
    op.create_index("ix_customer_response_drafts_status", "customer_response_drafts", ["status"])

    op.create_table(
        "customer_query_patterns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("normalized_question", sa.String(length=500), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("example_question", sa.Text(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_customer_query_patterns_normalized_question", "customer_query_patterns", ["normalized_question"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_customer_query_patterns_normalized_question", table_name="customer_query_patterns")
    op.drop_table("customer_query_patterns")

    op.drop_index("ix_customer_response_drafts_status", table_name="customer_response_drafts")
    op.drop_index("ix_customer_response_drafts_query_id", table_name="customer_response_drafts")
    op.drop_table("customer_response_drafts")

    op.drop_index("ix_customer_queries_status", table_name="customer_queries")
    op.drop_index("ix_customer_queries_classification", table_name="customer_queries")
    op.drop_index("ix_customer_queries_customer_email", table_name="customer_queries")
    op.drop_table("customer_queries")
