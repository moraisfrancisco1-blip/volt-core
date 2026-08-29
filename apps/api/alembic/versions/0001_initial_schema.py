"""initial VOLT CORE schema"""

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("api_clients", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(120), nullable=False), sa.Column("key_hash", sa.String(64), nullable=False), sa.Column("environment", sa.String(32), nullable=False, server_default="production"), sa.Column("scopes", sa.Text(), nullable=False, server_default=""), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True), sa.UniqueConstraint("name"), sa.UniqueConstraint("key_hash"))
    op.create_index("ix_api_clients_name", "api_clients", ["name"])
    op.create_index("ix_api_clients_key_hash", "api_clients", ["key_hash"])
    op.create_table("systems", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(120), nullable=False), sa.Column("environment", sa.String(32), nullable=False, server_default="production"), sa.Column("status", sa.String(32), nullable=False, server_default="connected"), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")), sa.UniqueConstraint("name"))
    op.create_index("ix_systems_name", "systems", ["name"])
    op.create_table("events", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("system", sa.String(120), nullable=False), sa.Column("level", sa.String(32), nullable=False), sa.Column("priority", sa.String(8), nullable=False), sa.Column("recommended_action", sa.String(64), nullable=False), sa.Column("message", sa.Text(), nullable=False), sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_events_system", "events", ["system"])
    op.create_index("ix_events_priority", "events", ["priority"])
    op.create_table("approvals", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("event_id", sa.Integer(), nullable=False), sa.Column("system", sa.String(120), nullable=False), sa.Column("action", sa.String(128), nullable=False), sa.Column("decision", sa.String(32), nullable=False, server_default="pending"), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_approvals_event_id", "approvals", ["event_id"])
    op.create_table("voice_calls", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("event_id", sa.Integer(), nullable=False), sa.Column("provider", sa.String(64), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("destination", sa.String(64), nullable=False), sa.Column("script", sa.Text(), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_voice_calls_event_id", "voice_calls", ["event_id"])
    op.create_index("ix_voice_calls_status", "voice_calls", ["status"])
    op.create_table("actions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("approval_id", sa.Integer(), nullable=False), sa.Column("system", sa.String(120), nullable=False), sa.Column("action", sa.String(128), nullable=False), sa.Column("environment", sa.String(32), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("reason", sa.Text(), nullable=True), sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_actions_approval_id", "actions", ["approval_id"])
    op.create_index("ix_actions_system", "actions", ["system"])
    op.create_index("ix_actions_environment", "actions", ["environment"])
    op.create_index("ix_actions_status", "actions", ["status"])
    op.create_table("audit_log", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("type", sa.String(64), nullable=False), sa.Column("reference_id", sa.String(64), nullable=True), sa.Column("detail", sa.Text(), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_index("ix_audit_log_type", "audit_log", ["type"])


def downgrade() -> None:
    for table in ["audit_log", "actions", "voice_calls", "approvals", "events", "systems", "api_clients"]:
        op.drop_table(table)
