"""add parent_investigation_id and repo tracking for chained investigations

Revision ID: 0006_investigation_chaining
Revises: 0005_agent_investigations
Create Date: 2026-08-30
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_investigation_chaining"
down_revision = "0005_agent_investigations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_investigations", sa.Column("parent_investigation_id", sa.Integer(), nullable=True))
    op.add_column("agent_investigations", sa.Column("repo_owner", sa.String(length=120), nullable=True))
    op.add_column("agent_investigations", sa.Column("repo_name", sa.String(length=160), nullable=True))
    op.create_index("ix_agent_investigations_parent_investigation_id", "agent_investigations", ["parent_investigation_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_investigations_parent_investigation_id", table_name="agent_investigations")
    op.drop_column("agent_investigations", "repo_name")
    op.drop_column("agent_investigations", "repo_owner")
    op.drop_column("agent_investigations", "parent_investigation_id")
