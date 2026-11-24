"""add projects, kb_entries and project_health for the shared knowledge base and project stewards

Revision ID: 0025_knowledge_projects
Revises: 0024_governance_layer
Create Date: 2026-11-24

Note: revision id kept under 32 chars (alembic_version.version_num is VARCHAR(32)).
"""

from alembic import op
import sqlalchemy as sa

revision = "0025_knowledge_projects"
down_revision = "0024_governance_layer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="product"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("repo", sa.String(length=160), nullable=True),
        sa.Column("repo_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deploy_url", sa.String(length=255), nullable=True),
        sa.Column("expect_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_projects_key", "projects", ["key"], unique=True)
    op.create_index("ix_projects_status", "projects", ["status"])
    op.create_table(
        "kb_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_key", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=200), nullable=True),
        sa.Column("source_sha", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_key", "source", name="uq_kb_project_source"),
    )
    op.create_index("ix_kb_entries_project_key", "kb_entries", ["project_key"])
    op.create_index("ix_kb_entries_status", "kb_entries", ["status"])
    op.create_table(
        "project_health",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_key", sa.String(length=64), nullable=False),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("days_since_push", sa.Float(), nullable=True),
        sa.Column("open_prs", sa.Integer(), nullable=True),
        sa.Column("oldest_pr_days", sa.Float(), nullable=True),
        sa.Column("ci_state", sa.String(length=16), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=True),
        sa.Column("flags", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_project_health_project_key", "project_health", ["project_key"])
    op.create_index("ix_project_health_created_at", "project_health", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_project_health_created_at", table_name="project_health")
    op.drop_index("ix_project_health_project_key", table_name="project_health")
    op.drop_table("project_health")
    op.drop_index("ix_kb_entries_status", table_name="kb_entries")
    op.drop_index("ix_kb_entries_project_key", table_name="kb_entries")
    op.drop_table("kb_entries")
    op.drop_index("ix_projects_status", table_name="projects")
    op.drop_index("ix_projects_key", table_name="projects")
    op.drop_table("projects")
