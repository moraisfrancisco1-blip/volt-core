from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from .auth import Principal, authenticate, require_scope
from .db import session_scope
from .models import AuditRecord, EscalationRecord, EventRecord

router = APIRouter(tags=["escalations"])

ACTIVE_STATUSES = {"queued", "acknowledged", "dispatched"}
VALID_STATUSES = ACTIVE_STATUSES | {"completed", "cancelled"}
SLA_MINUTES = {"P1": 5, "P2": 15, "P3": 60, "P4": 240}
NEXT_PRIORITY = {"P4": "P3", "P3": "P2", "P2": "P1", "P1": "P1"}
ACTION_BY_PRIORITY = {"P1": "call", "P2": "call", "P3": "call", "P4": "digest"}


class EscalationUpdate(BaseModel):
    status: str


def escalation_due_at(record: EscalationRecord):
    return record.created_at + timedelta(minutes=SLA_MINUTES.get(record.priority, 240)) if record.created_at else None


def escalation_dict(record: EscalationRecord) -> dict:
    due_at = escalation_due_at(record)
    now = datetime.now(timezone.utc)
    overdue = bool(due_at and record.status in ACTIVE_STATUSES and due_at < now)
    return {
        "id": record.id, "event_id": record.event_id, "system": record.system,
        "priority": record.priority, "action": record.action, "status": record.status,
        "sla_minutes": SLA_MINUTES.get(record.priority, 240), "due_at": due_at.isoformat() if due_at else None,
        "overdue": overdue, "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def queue_escalation(session, event: EventRecord) -> EscalationRecord:
    existing = session.scalar(select(EscalationRecord).where(EscalationRecord.event_id == event.id))
    if existing is not None: return existing
    record = EscalationRecord(event_id=event.id, system=event.system, priority=event.priority, action=event.recommended_action, status="queued")
    session.add(record); session.flush()
    session.add(AuditRecord(type="escalation_queued", reference_id=str(record.id), detail=f"event={event.id} priority={record.priority} action={record.action} sla={SLA_MINUTES.get(record.priority, 240)}m"))
    return record


def sync_escalation_status(session, event: EventRecord) -> EscalationRecord | None:
    record = session.scalar(select(EscalationRecord).where(EscalationRecord.event_id == event.id))
    if record is None: return None
    target = "completed" if event.status == "resolved" else "acknowledged" if event.status == "acknowledged" else "queued"
    if record.status != target:
        record.status = target; record.updated_at = datetime.now(timezone.utc)
    return record


def process_overdue_escalations(session) -> list[dict]:
    now = datetime.now(timezone.utc)
    rows = session.scalars(select(EscalationRecord).where(EscalationRecord.status.in_(ACTIVE_STATUSES))).all()
    changed = []
    for record in rows:
        due_at = escalation_due_at(record)
        if not due_at or due_at >= now or record.status == "acknowledged": continue
        event = session.get(EventRecord, record.event_id)
        old_priority = record.priority
        new_priority = NEXT_PRIORITY.get(old_priority, old_priority)
        if new_priority != old_priority:
            record.priority = new_priority
            record.action = ACTION_BY_PRIORITY[new_priority]
            if event:
                event.priority = new_priority
                event.recommended_action = record.action
                event.updated_at = now
            record.status = "dispatched"
            record.created_at = now
            record.updated_at = now
            session.add(AuditRecord(type="escalation_timeout", reference_id=str(record.id), detail=f"event={record.event_id} {old_priority}->{new_priority}; redispatched after missed SLA"))
            changed.append(escalation_dict(record))
        elif old_priority == "P1":
            record.status = "dispatched"
            record.created_at = now
            record.updated_at = now
            session.add(AuditRecord(type="escalation_timeout", reference_id=str(record.id), detail=f"event={record.event_id} P1 re-dispatched after missed SLA"))
            changed.append(escalation_dict(record))
    return changed


@router.get("/escalations")
def list_escalations(limit: int = Query(default=50, ge=1, le=200), status: str | None = None) -> list[dict]:
    with session_scope() as session:
        statement = select(EscalationRecord)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_STATUSES: raise HTTPException(status_code=422, detail="invalid escalation status")
            statement = statement.where(EscalationRecord.status == normalized)
        rows = session.scalars(statement.order_by(EscalationRecord.id.desc()).limit(limit)).all()
        return [escalation_dict(row) for row in rows]


@router.patch("/escalations/{escalation_id}", dependencies=[Depends(require_scope("watch:write"))])
def update_escalation(escalation_id: int, update: EscalationUpdate, principal: Principal = Depends(authenticate)) -> dict:
    normalized = update.status.strip().lower()
    if normalized not in VALID_STATUSES: raise HTTPException(status_code=422, detail="invalid escalation status")
    with session_scope() as session:
        record = session.get(EscalationRecord, escalation_id)
        if record is None: raise HTTPException(status_code=404, detail="escalation not found")
        event = session.get(EventRecord, record.event_id)
        if event and principal.environment != event.environment and "*" not in principal.scopes: raise HTTPException(status_code=403, detail="client cannot update escalations in another environment")
        record.status = normalized; record.updated_at = datetime.now(timezone.utc)
        session.add(AuditRecord(type="escalation_status_updated", reference_id=str(record.id), detail=f"{normalized} via {principal.name}"))
        return escalation_dict(record)
