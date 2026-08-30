from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from ..auth import Principal
from ..db import session_scope
from ..event_history import EventIngestion, create_event
from ..models import EventRecord
from .railway_tools import ProductionSweepJob

CATEGORIES = ("error_rate", "latency", "resource_usage", "deployment_failure", "other")
SEVERITIES = ("critical", "high", "medium", "low", "info")

RAISE_ALERT_SCHEMA: dict[str, Any] = {
    "name": "raise_monitoring_alert",
    "description": "Raise an alert for this system into VOLT CORE's normal event/escalation pipeline. Only call this when you're genuinely concerned -- if an alert of this category is already open for this system, this tool tells you instead of creating a duplicate, and you should not try again this sweep.",
    "input_schema": {
        "type": "object",
        "properties": {
            "severity": {"type": "string", "enum": list(SEVERITIES), "description": "How serious this is."},
            "category": {"type": "string", "enum": list(CATEGORIES), "description": "What kind of problem this is -- used to detect if you already raised this same alert."},
            "title": {"type": "string", "description": "Short summary of the problem."},
            "message": {"type": "string", "description": "The full explanation, with the specific numbers that led you to this conclusion."},
        },
        "required": ["severity", "category", "title", "message"],
    },
}


def _principal(job: ProductionSweepJob) -> Principal:
    return Principal(client_id=0, name="volt-core-production-monitor", environment=job.environment, scopes={"*"})


def raise_monitoring_alert(job: ProductionSweepJob, severity: str, category: str, title: str, message: str) -> dict:
    if category not in CATEGORIES:
        return {"error": f"unknown category {category!r}"}
    event_type = f"railway_{category}"
    with session_scope() as session:
        # State-based dedup, not time-windowed: an elevated error rate is an ongoing
        # condition, not a point-in-time event, and the model rephrases title/message
        # differently every sweep -- decision_engine's exact-fingerprint dedup (10-minute
        # window) would never catch this. As long as a non-resolved event of this exact
        # (system_id, environment, event_type) triple already exists, don't raise again.
        existing = session.scalar(
            select(EventRecord)
            .where(EventRecord.system_id == job.system, EventRecord.environment == job.environment,
                   EventRecord.event_type == event_type, EventRecord.status != "resolved")
            .order_by(EventRecord.id.desc())
        )
        if existing is not None:
            return {"created": False, "event_id": existing.id, "reason": "an alert of this category is already open for this system"}
        try:
            record = create_event(session, EventIngestion(
                system_id=job.system, system_name=job.system, environment=job.environment,
                severity=severity, event_type=event_type, title=title[:255], message=message,
                source="volt-core-production-monitor",
            ), _principal(job))
        except HTTPException as exc:
            return {"created": False, "error": str(exc.detail)}
        return {"created": True, "event_id": record.id}
