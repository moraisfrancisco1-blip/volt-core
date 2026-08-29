from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from .auth import Principal, authenticate, require_scope
from .db import session_scope
from .models import AuditRecord, EscalationRecord, EventRecord, VoiceCallRecord
from .voice import build_voice_script, get_operator_phone_number, get_voice_provider

router = APIRouter(tags=["escalations"])

ACTIVE_STATUSES = {"queued", "acknowledged", "dispatched"}
VALID_STATUSES = ACTIVE_STATUSES | {"completed", "cancelled"}
PHONE_CALL_PRIORITIES = {"P1", "P2", "P3"}


class EscalationUpdate(BaseModel):
    status: str


def escalation_dict(record: EscalationRecord) -> dict:
    return {
        "id": record.id,
        "event_id": record.event_id,
        "system": record.system,
        "priority": record.priority,
        "action": record.action,
        "status": record.status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def queue_escalation(session, event: EventRecord) -> EscalationRecord:
    existing = session.scalar(select(EscalationRecord).where(EscalationRecord.event_id == event.id))
    if existing is not None:
        return existing
    record = EscalationRecord(
        event_id=event.id,
        system=event.system,
        priority=event.priority,
        action=event.recommended_action,
        status="queued",
    )
    session.add(record)
    session.flush()
    session.add(
        AuditRecord(
            type="escalation_queued",
            reference_id=str(record.id),
            detail=f"event={event.id} priority={record.priority} action={record.action}",
        )
    )
    return record


def dispatch_phone_call(session, event: EventRecord, escalation: EscalationRecord) -> VoiceCallRecord | None:
    if event.priority not in PHONE_CALL_PRIORITIES or event.recommended_action != "call":
        return None
    existing = session.scalar(select(VoiceCallRecord).where(VoiceCallRecord.event_id == event.id))
    if existing is not None:
        return existing
    destination = get_operator_phone_number()
    if not destination:
        session.add(
            AuditRecord(
                type="voice_call_skipped",
                reference_id=str(event.id),
                detail="operator phone number is not configured",
            )
        )
        return None
    event_data = {
        "priority": event.priority,
        "system": event.system,
        "message": event.message,
        "recommended_action": event.recommended_action,
    }
    script = build_voice_script(event_data)
    try:
        result = get_voice_provider().place_call(destination, script)
    except Exception as exc:
        session.add(
            AuditRecord(
                type="voice_call_failed",
                reference_id=str(event.id),
                detail=str(exc)[:500],
            )
        )
        return None
    call = VoiceCallRecord(
        event_id=event.id,
        status=result.get("status", "queued"),
        provider=result.get("provider", "unknown"),
        destination=destination,
        script=script,
    )
    session.add(call)
    session.flush()
    escalation.status = "dispatched"
    escalation.updated_at = datetime.now(timezone.utc)
    session.add(
        AuditRecord(
            type="voice_call_dispatched",
            reference_id=str(call.id),
            detail=f"event={event.id} priority={event.priority} provider={call.provider}",
        )
    )
    return call


def sync_escalation_status(session, event: EventRecord) -> EscalationRecord | None:
    record = session.scalar(select(EscalationRecord).where(EscalationRecord.event_id == event.id))
    if record is None:
        return None
    target = "completed" if event.status == "resolved" else "acknowledged" if event.status == "acknowledged" else "queued"
    if record.status != target:
        record.status = target
        record.updated_at = datetime.now(timezone.utc)
    return record


@router.get("/escalations")
def list_escalations(
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
) -> list[dict]:
    with session_scope() as session:
        statement = select(EscalationRecord)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_STATUSES:
                raise HTTPException(status_code=422, detail="invalid escalation status")
            statement = statement.where(EscalationRecord.status == normalized)
        rows = session.scalars(statement.order_by(EscalationRecord.id.desc()).limit(limit)).all()
        return [escalation_dict(row) for row in rows]


@router.patch("/escalations/{escalation_id}", dependencies=[Depends(require_scope("watch:write"))])
def update_escalation(
    escalation_id: int,
    update: EscalationUpdate,
    principal: Principal = Depends(authenticate),
) -> dict:
    normalized = update.status.strip().lower()
    if normalized not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail="invalid escalation status")
    with session_scope() as session:
        record = session.get(EscalationRecord, escalation_id)
        if record is None:
            raise HTTPException(status_code=404, detail="escalation not found")
        event = session.get(EventRecord, record.event_id)
        if event and principal.environment != event.environment and "*" not in principal.scopes:
            raise HTTPException(status_code=403, detail="client cannot update escalations in another environment")
        record.status = normalized
        record.updated_at = datetime.now(timezone.utc)
        session.add(
            AuditRecord(
                type="escalation_status_updated",
                reference_id=str(record.id),
                detail=f"{normalized} via {principal.name}",
            )
        )
        return escalation_dict(record)
