"""add sandboxed-fix-verification columns to agent_investigations

Revision ID: 0010_sandbox_results
Revises: 0009_agent_inbox
Create Date: 2026-09-04
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_sandbox_results"
down_revision = "0009_agent_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_investigations", sa.Column("proposed_files", sa.JSON(), nullable=True))
    op.add_column("agent_investigations", sa.Column("sandbox_status", sa.String(length=32), nullable=True))
    op.add_column("agent_investigations", sa.Column("sandbox_output", sa.Text(), nullable=True))
    op.add_column("agent_investigations", sa.Column("sandbox_network_isolated", sa.Boolean(), nullable=True))
    op.add_column("agent_investigations", sa.Column("sandbox_ran_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_investigations", "sandbox_ran_at")
    op.drop_column("agent_investigations", "sandbox_network_isolated")
    op.drop_column("agent_investigations", "sandbox_output")
    op.drop_column("agent_investigations", "sandbox_status")
    op.drop_column("agent_investigations", "proposed_files")
