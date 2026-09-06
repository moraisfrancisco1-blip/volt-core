"""add onboardings, onboarding_steps and operations_activation_requests tables for the Operations agent

Revision ID: 0015_operations_agent
Revises: 0014_marketing_agent
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa

revision = "0015_operations_agent"
down_revision = "0014_marketing_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "onboardings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_progress_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_onboardings_deal_id", "onboardings", ["deal_id"], unique=True)

    op.create_table(
        "onboarding_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("onboarding_id", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("requires_activation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_onboarding_steps_onboarding_id", "onboarding_steps", ["onboarding_id"])
    op.create_index("ix_onboarding_steps_status", "onboarding_steps", ["status"])

    op.create_table(
        "operations_activation_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("onboarding_step_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_approval"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_operations_activation_requests_onboarding_step_id", "operations_activation_requests", ["onboarding_step_id"], unique=True)
    op.create_index("ix_operations_activation_requests_status", "operations_activation_requests", ["status"])

    op.create_table(
        "recurring_task_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_name", sa.String(length=160), nullable=False),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_recurring_task_checkpoints_task_name", "recurring_task_checkpoints", ["task_name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_recurring_task_checkpoints_task_name", table_name="recurring_task_checkpoints")
    op.drop_table("recurring_task_checkpoints")

    op.drop_index("ix_operations_activation_requests_status", table_name="operations_activation_requests")
    op.drop_index("ix_operations_activation_requests_onboarding_step_id", table_name="operations_activation_requests")
    op.drop_table("operations_activation_requests")

    op.drop_index("ix_onboarding_steps_status", table_name="onboarding_steps")
    op.drop_index("ix_onboarding_steps_onboarding_id", table_name="onboarding_steps")
    op.drop_table("onboarding_steps")

    op.drop_index("ix_onboardings_deal_id", table_name="onboardings")
    op.drop_table("onboardings")
