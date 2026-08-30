from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import select

from ..db import session_scope
from ..models import AuditRecord, EscalationRecord, EventRecord, SystemRecord, VoiceCallRecord


@dataclass(frozen=True)
class InvestigationJob:
    event_id: int
    escalation_id: int
    system: str
    environment: str
    priority: str


def _event_dict(event: EventRecord) -> dict:
    return {
        "id": event.id,
        "system_id": event.system_id or event.system,
        "system_name": event.system_name or event.system,
        "environment": event.environment,
        "severity": event.severity or event.level.lower(),
        "priority": event.priority,
        "event_type": event.event_type,
        "title": event.title,
        "message": event.message,
        "status": event.status,
        "source": event.source,
        "metadata": event.metadata_,
        "recommended_action": event.recommended_action,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
        "resolved_at": event.resolved_at.isoformat() if event.resolved_at else None,
    }


def get_incident_event(job: InvestigationJob) -> dict:
    with session_scope() as session:
        event = session.get(EventRecord, job.event_id)
        if event is None:
            return {"error": "event not found"}
        return _event_dict(event)


def get_recent_system_events(job: InvestigationJob, limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 100))
    with session_scope() as session:
        statement = (
            select(EventRecord)
            .where(EventRecord.system_id == job.system, EventRecord.environment == job.environment, EventRecord.id != job.event_id)
            .order_by(EventRecord.id.desc())
            .limit(limit)
        )
        rows = session.scalars(statement).all()
        return {"events": [_event_dict(row) for row in rows]}


def get_escalation_and_call_trail(job: InvestigationJob) -> dict:
    with session_scope() as session:
        escalation = session.get(EscalationRecord, job.escalation_id)
        calls = session.scalars(
            select(VoiceCallRecord).where(VoiceCallRecord.event_id == job.event_id).order_by(VoiceCallRecord.id.asc())
        ).all()
        return {
            "escalation": None
            if escalation is None
            else {
                "id": escalation.id,
                "priority": escalation.priority,
                "action": escalation.action,
                "status": escalation.status,
                "call_attempts": escalation.call_attempts,
                "created_at": escalation.created_at.isoformat() if escalation.created_at else None,
                "updated_at": escalation.updated_at.isoformat() if escalation.updated_at else None,
            },
            "calls": [
                {
                    "id": call.id,
                    "status": call.status,
                    "provider": call.provider,
                    "destination": call.destination,
                    "call_sid": call.call_sid,
                    "created_at": call.created_at.isoformat() if call.created_at else None,
                    "updated_at": call.updated_at.isoformat() if call.updated_at else None,
                }
                for call in calls
            ],
        }


def get_system_monitoring_status(job: InvestigationJob) -> dict:
    from .. import monitoring  # lazy: monitoring.py imports escalations.py, which imports this package

    with session_scope() as session:
        system = session.scalar(select(SystemRecord).where(SystemRecord.name == job.system))
        system_dict = (
            None
            if system is None
            else {
                "name": system.name,
                "environment": system.environment,
                "status": system.status,
                "updated_at": system.updated_at.isoformat() if system.updated_at else None,
            }
        )
    monitor_target = next(
        (target for target in monitoring.monitoring_status().get("targets", []) if target.get("system_id") == job.system),
        None,
    )
    return {"system": system_dict, "monitor": monitor_target}


def get_recent_audit_log(job: InvestigationJob, limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 100))
    references = {str(job.event_id), str(job.escalation_id)}
    with session_scope() as session:
        statement = (
            select(AuditRecord).where(AuditRecord.reference_id.in_(references)).order_by(AuditRecord.id.desc()).limit(limit)
        )
        rows = session.scalars(statement).all()
        return {
            "entries": [
                {
                    "type": row.type,
                    "reference_id": row.reference_id,
                    "detail": row.detail,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]
        }


# The complete, closed set of things Jarvis can read for an investigation. Nothing else
# is reachable -- no bash, no filesystem, no network, no write access to any table.
TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "get_incident_event": get_incident_event,
    "get_recent_system_events": get_recent_system_events,
    "get_escalation_and_call_trail": get_escalation_and_call_trail,
    "get_system_monitoring_status": get_system_monitoring_status,
    "get_recent_audit_log": get_recent_audit_log,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_incident_event",
        "description": "Read the full details of the event that triggered this investigation: severity, priority, title, message, metadata, and current status.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_recent_system_events",
        "description": "Read recent events from the same system and environment as the incident (most recent first), to check for a burst, a pattern, or a related earlier warning.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Max events to return (default 20, max 100)"}},
            "required": [],
        },
    },
    {
        "name": "get_escalation_and_call_trail",
        "description": "Read the escalation record (priority, status, how many call attempts so far) and every voice call attempt made for this incident (provider, status, timestamps).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_system_monitoring_status",
        "description": "Read the current known status of the affected system: its registered status/environment, and if it's an actively health-checked monitor target, the latest check result and consecutive-failure count.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_recent_audit_log",
        "description": "Read the audit trail already recorded for this event and escalation (e.g. voice_call_dispatched, voice_call_unanswered, escalation_priority_bumped) -- often the most directly diagnostic material available.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Max audit entries to return (default 20, max 100)"}},
            "required": [],
        },
    },
]

SUBMIT_TOOL_NAME = "submit_investigation_result"

SUBMIT_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_TOOL_NAME,
    "description": "Submit your final diagnosis of this incident. Call this exactly once, as your last action, once you have gathered enough context. This is the only way to end the investigation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "hypothesis": {
                "type": "string",
                "description": "Your best explanation for what is happening and why the alert call was not confirmed.",
            },
            "recommended_next_step": {
                "type": "string",
                "description": "A concrete next step for a human operator to take. Never recommend an automated production action -- that always requires human approval.",
            },
            "confidence": {
                "type": "number",
                "description": "Your confidence in this hypothesis, from 0.0 (guessing) to 1.0 (certain).",
            },
            "is_known_pattern": {
                "type": "boolean",
                "description": "True if this matches a pattern already visible in the recent event/audit history (e.g. a recurring failure), false if it looks novel.",
            },
        },
        "required": ["hypothesis", "recommended_next_step", "confidence", "is_known_pattern"],
    },
}
