"""add dai_oakes_payments table for the Dai Oakes Payment Control connector

Revision ID: 0019_dai_oakes_payments
Revises: 0018_voltaris_real_data
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa

revision = "0019_dai_oakes_payments"
down_revision = "0018_voltaris_real_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dai_oakes_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("amount_paid", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("due_date", sa.String(length=64), nullable=True),
        sa.Column("paid_at", sa.String(length=64), nullable=True),
        sa.Column("stripe_invoice_id", sa.String(length=64), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dai_oakes_payments_external_id", "dai_oakes_payments", ["external_id"], unique=True)
    op.create_index("ix_dai_oakes_payments_status", "dai_oakes_payments", ["status"])


def downgrade() -> None:
    op.drop_index("ix_dai_oakes_payments_status", table_name="dai_oakes_payments")
    op.drop_index("ix_dai_oakes_payments_external_id", table_name="dai_oakes_payments")
    op.drop_table("dai_oakes_payments")
