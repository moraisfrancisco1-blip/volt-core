from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from .auth import Principal, authenticate, require_scope
from .db import session_scope
from .decision_engine import BASE_PRIORITY, decide_event
from .escalations import dispatch_voice_call, queue_escalation, router as escalation_router, sync_escalation_status
from .models import AuditRecord, EventRecord, SystemRecord

router = APIRouter(prefix="/api", tags=["events"])
router.include_router(escalation_router)
SEVERITY_PRIORITY = BASE_PRIORITY
VALID_STATUSES = {"active", "acknowledged", "resolved"}

class EventIngestion(BaseModel):
    system_id: str = Field(min_length=1, max_length=120)
    system_name: str | None = Field(default=None, max_length=160)
    environment: str = Field(default="production", max_length=32)
    severity: str
    event_type: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=255)
    message: str = Field(min_length=1)
    source: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] | None = None

class EventUpdate(BaseModel):
    status: str | None = None
    acknowledge: bool | None = None
    resolve: bool | None = None

def normalize_severity(value: str) -> str:
    severity = value.strip().lower()
    if severity not in SEVERITY_PRIORITY:
        raise HTTPException(status_code=422, detail="severity must be critical, high, medium, low or info")
    return severity

def event_dict(event: EventRecord) -> dict:
    return {"id": event.id, "system_id": event.system_id or event.system, "system_name": event.system_name or event.system, "environment": event.environment, "severity": event.severity or event.level.lower(), "priority": event.priority, "event_type": event.event_type, "title": event.title, "message": event.message, "status": event.status, "source": event.source, "metadata": event.metadata_, "recommended_action": event.recommended_action, "created_at": event.created_at.isoformat() if event.created_at else None, "updated_at": event.updated_at.isoformat() if event.updated_at else None, "resolved_at": event.resolved_at.isoformat() if event.resolved_at else None}

def create_event(session, payload: EventIngestion, principal: Principal) -> EventRecord:
    if principal.environment != payload.environment and "*" not in principal.scopes:
        raise HTTPException(status_code=403, detail="client cannot write events to another environment")
    severity = normalize_severity(payload.severity)
    decision = decide_event(session, severity=severity, system_id=payload.system_id, environment=payload.environment, event_type=payload.event_type, title=payload.title, message=payload.message)
    system = session.scalar(select(SystemRecord).where(SystemRecord.name == payload.system_id))
    if system is None:
        system = SystemRecord(name=payload.system_id, environment=payload.environment, status="connected"); session.add(system)
    else:
        system.environment = payload.environment; system.status = "connected"
    record = EventRecord(system=payload.system_id, system_id=payload.system_id, system_name=payload.system_name or payload.system_id, environment=payload.environment, level=severity.upper(), severity=severity, priority=decision.priority, event_type=payload.event_type, title=payload.title or payload.message[:255], recommended_action=decision.action, message=payload.message, status="active", source=payload.source, metadata_=payload.metadata)
    session.add(record); session.flush(); escalation = queue_escalation(session, record); dispatch_voice_call(session, record, escalation)
    session.add(AuditRecord(type="decision_made", reference_id=str(record.id), detail=f"priority={decision.priority}; action={decision.action}; reason={decision.reason}; duplicate={decision.duplicate}"))
    session.add(AuditRecord(type="event_received", reference_id=str(record.id), detail=f"{record.system} via {principal.name}"))
    return record

@router.post("/events", dependencies=[Depends(require_scope("watch:write"))])
def ingest_event(payload: EventIngestion, principal: Principal = Depends(authenticate)) -> dict:
    with session_scope() as session: return event_dict(create_event(session, payload, principal))

@router.get("/events")
def list_events(limit: int = Query(default=50, ge=1, le=200), severity: str | None = None, status: str | None = None, system_id: str | None = None) -> list[dict]:
    with session_scope() as session:
        statement = select(EventRecord)
        if severity: statement = statement.where(EventRecord.severity == normalize_severity(severity))
        if status:
            status = status.strip().lower()
            if status not in VALID_STATUSES: raise HTTPException(status_code=422, detail="status must be active, acknowledged or resolved")
            statement = statement.where(EventRecord.status == status)
        if system_id: statement = statement.where(EventRecord.system_id == system_id)
        return [event_dict(row) for row in session.scalars(statement.order_by(EventRecord.id.desc()).limit(limit)).all()]

@router.get("/events/{event_id}")
def get_event(event_id: int) -> dict:
    with session_scope() as session:
        event = session.get(EventRecord, event_id)
        if event is None: raise HTTPException(status_code=404, detail="event not found")
        return event_dict(event)

@router.patch("/events/{event_id}", dependencies=[Depends(require_scope("watch:write"))])
def update_event(event_id: int, update: EventUpdate, principal: Principal = Depends(authenticate)) -> dict:
    with session_scope() as session:
        event = session.get(EventRecord, event_id)
        if event is None: raise HTTPException(status_code=404, detail="event not found")
        if principal.environment != event.environment and "*" not in principal.scopes: raise HTTPException(status_code=403, detail="client cannot update events in another environment")
        requested_status = update.status
        if update.resolve: requested_status = "resolved"
        elif update.acknowledge: requested_status = "acknowledged"
        if requested_status is None: raise HTTPException(status_code=422, detail="provide status, acknowledge or resolve")
        requested_status = requested_status.strip().lower()
        if requested_status not in VALID_STATUSES: raise HTTPException(status_code=422, detail="status must be active, acknowledged or resolved")
        event.status = requested_status; event.updated_at = datetime.now(timezone.utc); event.resolved_at = datetime.now(timezone.utc) if requested_status == "resolved" else None
        sync_escalation_status(session, event)
        session.add(AuditRecord(type="event_status_updated", reference_id=str(event.id), detail=f"{requested_status} via {principal.name}"))
        return event_dict(event)
