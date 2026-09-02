from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class ApiClientRecord(Base):
    __tablename__ = "api_clients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    environment: Mapped[str] = mapped_column(String(32), default="production")
    scopes: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SystemRecord(Base):
    __tablename__ = "systems"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    environment: Mapped[str] = mapped_column(String(32), default="production")
    status: Mapped[str] = mapped_column(String(32), default="connected")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EventRecord(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    system: Mapped[str] = mapped_column(String(120), index=True)
    system_id: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    system_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    environment: Mapped[str] = mapped_column(String(32), default="production", index=True)
    level: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    priority: Mapped[str] = mapped_column(String(8), index=True)
    event_type: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recommended_action: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EscalationRecord(Base):
    __tablename__ = "escalations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    system: Mapped[str] = mapped_column(String(120), index=True)
    priority: Mapped[str] = mapped_column(String(8), index=True)
    action: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    call_attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ApprovalRecord(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, index=True)
    system: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(128))
    decision: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VoiceCallRecord(Base):
    __tablename__ = "voice_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, index=True)
    provider: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), index=True)
    destination: Mapped[str] = mapped_column(String(64))
    script: Mapped[str | None] = mapped_column(Text, nullable=True)
    call_sid: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ActionRecord(Base):
    __tablename__ = "actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_id: Mapped[int] = mapped_column(Integer, index=True)
    system: Mapped[str] = mapped_column(String(120), index=True)
    action: Mapped[str] = mapped_column(String(128))
    environment: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentInvestigationRecord(Base):
    __tablename__ = "agent_investigations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, index=True)
    escalation_id: Mapped[int] = mapped_column(Integer, index=True)
    investigation_type: Mapped[str] = mapped_column(String(64), default="voice_call_failure", index=True)
    parent_investigation_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    system: Mapped[str] = mapped_column(String(120), index=True)
    environment: Mapped[str] = mapped_column(String(32), index=True)
    priority: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_known_pattern: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    repo_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    repo_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    turns_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MonitoringSweepRecord(Base):
    __tablename__ = "monitoring_sweeps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    system: Mapped[str] = mapped_column(String(120), index=True)
    environment: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", index=True)
    event_action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    turns_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TelegramScheduleRecord(Base):
    __tablename__ = "telegram_schedules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(32))  # "sweep" | "investigate"
    target: Mapped[str | None] = mapped_column(String(120), nullable=True)  # only for "investigate"
    time_of_day: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "HH:MM"
    interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentInboxRecord(Base):
    __tablename__ = "agent_inbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender: Mapped[str] = mapped_column(String(64), index=True)
    recipient: Mapped[str] = mapped_column(String(64), index=True)
    message_type: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditRecord(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
