import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from .agents.dispatcher import enqueue_investigation
from .auth import Principal, authenticate, require_scope
from .db import session_scope
from .models import AuditRecord, EscalationRecord, EventRecord, VoiceCallRecord
from .voice import build_voice_script, get_voice_provider, status_callback_url

router = APIRouter(tags=["escalations"])
ACTIVE_STATUSES = {"queued", "calling", "notified", "acknowledged"}
VALID_STATUSES = ACTIVE_STATUSES | {"completed", "cancelled"}
SLA_MINUTES = {"P1": 5, "P2": 15, "P3": 60, "P4": 240}
NEXT_PRIORITY = {"P4": "P3", "P3": "P2", "P2": "P1", "P1": "P1"}
ACTION_BY_PRIORITY = {"P1": "call", "P2": "call", "P3": "call", "P4": "digest"}
MAX_CALL_ATTEMPTS = max(1, int(os.getenv("VOLT_MAX_CALL_ATTEMPTS", "3")))
# Twilio CallStatus values are queued/ringing/in-progress/completed/busy/failed/no-answer/canceled.
# "completed" is the only literal Twilio sends for a call that connected; "answered" is accepted
# defensively in case a different voice provider reports it directly.
CONFIRMED_CALL_STATUSES = {"completed", "answered"}
FAILED_CALL_STATUSES = {"busy", "failed", "no-answer", "canceled"}

class EscalationUpdate(BaseModel): status: str

def _as_utc(value: datetime | None) -> datetime | None:
    if value is None: return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def escalation_due_at(record: EscalationRecord):
    created_at = _as_utc(record.created_at)
    return created_at + timedelta(minutes=SLA_MINUTES.get(record.priority, 240)) if created_at else None

def escalation_dict(record: EscalationRecord) -> dict:
    due_at = escalation_due_at(record); now = datetime.now(timezone.utc)
    overdue = bool(due_at and record.status in ACTIVE_STATUSES and record.status not in {"acknowledged", "notified"} and due_at < now)
    return {"id": record.id, "event_id": record.event_id, "system": record.system, "priority": record.priority, "action": record.action, "status": record.status, "call_attempts": record.call_attempts, "sla_minutes": SLA_MINUTES.get(record.priority, 240), "due_at": due_at.isoformat() if due_at else None, "overdue": overdue, "created_at": _as_utc(record.created_at).isoformat() if record.created_at else None, "updated_at": _as_utc(record.updated_at).isoformat() if record.updated_at else None}

def queue_escalation(session, event: EventRecord) -> EscalationRecord:
    existing = session.scalar(select(EscalationRecord).where(EscalationRecord.event_id == event.id))
    if existing is not None: return existing
    record = EscalationRecord(event_id=event.id, system=event.system, priority=event.priority, action=event.recommended_action, status="queued")
    session.add(record); session.flush(); session.add(AuditRecord(type="escalation_queued", reference_id=str(record.id), detail=f"event={event.id} priority={record.priority} action={record.action} sla={SLA_MINUTES.get(record.priority, 240)}m")); return record

def should_auto_call(event: EventRecord) -> bool:
    metadata = event.metadata_ or {}
    if metadata.get("monitor_self_test") is True:
        return False
    return event.environment == "production" and os.getenv("VOLT_AUTO_CALL_ENABLED", "true").lower() == "true" and bool(os.getenv("VOLT_ALERT_PHONE"))

def dispatch_voice_call(session, event: EventRecord, escalation: EscalationRecord) -> None:
    # Places a voice call for this escalation attempt. Never marks the escalation as
    # successfully notified here -- that only happens once Twilio confirms delivery via
    # the /api/voice/status callback (see voice_status_callback below).
    if escalation.action != "call" or not should_auto_call(event):
        return
    destination = os.getenv("VOLT_ALERT_PHONE")
    escalation.call_attempts += 1
    script = build_voice_script({"priority": event.priority, "system": event.system_name or event.system, "message": event.message, "recommended_action": event.recommended_action})
    try:
        provider = get_voice_provider()
        result = provider.place_call(destination, script, status_callback=status_callback_url())
        call = VoiceCallRecord(event_id=event.id, status=result.get("status", "queued"), provider=result.get("provider", "unknown"), destination=destination, script=script, call_sid=result.get("sid"))
        session.add(call)
        escalation.status = "calling"; escalation.updated_at = datetime.now(timezone.utc)
        session.add(AuditRecord(type="voice_call_dispatched", reference_id=str(event.id), detail=f"attempt={escalation.call_attempts} provider={call.provider} sid={call.call_sid or 'n/a'}"))
    except Exception as exc:
        session.add(AuditRecord(type="voice_call_dispatch_failed", reference_id=str(event.id), detail=str(exc)[:500]))

def _retry_or_escalate(session, event: EventRecord, escalation: EscalationRecord) -> None:
    # A call attempt is unconfirmed (never answered/completed), or this escalation has never
    # placed a call at all (e.g. a P4 digest). Either retry at the same priority, or once
    # attempts are exhausted, bump to the next priority and try again there. Status always
    # ends up "queued" -> dispatch_voice_call, never a silent success.
    now = datetime.now(timezone.utc)
    # First confirmed failure at this priority (not a subsequent retry, not a P4 digest
    # that never called anyone): hand it to Jarvis for a read-only investigation. This
    # never touches escalation/event state and can never fail this function.
    if escalation.action == "call" and escalation.call_attempts == 1:
        enqueue_investigation(event_id=event.id, escalation_id=escalation.id, system=event.system, environment=event.environment, priority=escalation.priority)
    escalate = escalation.action != "call" or escalation.call_attempts >= MAX_CALL_ATTEMPTS
    if escalate:
        old_priority = escalation.priority; new_priority = NEXT_PRIORITY.get(old_priority, old_priority)
        escalation.priority = new_priority; escalation.action = ACTION_BY_PRIORITY[new_priority]
        event.priority = new_priority; event.recommended_action = escalation.action; event.updated_at = now
        escalation.call_attempts = 0
        session.add(AuditRecord(type="escalation_priority_bumped", reference_id=str(escalation.id), detail=f"event={event.id} {old_priority}->{new_priority}"))
    escalation.status = "queued"; escalation.created_at = now; escalation.updated_at = now
    dispatch_voice_call(session, event, escalation)

def sync_escalation_status(session, event: EventRecord) -> EscalationRecord | None:
    record = session.scalar(select(EscalationRecord).where(EscalationRecord.event_id == event.id))
    if record is None: return None
    if event.status == "resolved": target = "completed"
    elif event.status == "acknowledged": target = "acknowledged"
    # A live or confirmed call attempt is not undone by an unrelated event PATCH
    # (e.g. someone re-flipping status back to "active") -- only ack/resolve can move it.
    elif record.status in {"calling", "notified"}: target = record.status
    else: target = "queued"
    if record.status != target: record.status = target; record.updated_at = datetime.now(timezone.utc)
    return record

def process_overdue_escalations(session) -> list[dict]:
    now = datetime.now(timezone.utc); rows = session.scalars(select(EscalationRecord).where(EscalationRecord.status.in_(ACTIVE_STATUSES))).all(); changed = []
    for record in rows:
        if record.status in {"acknowledged", "notified"}: continue
        due_at = escalation_due_at(record)
        if not due_at or due_at >= now: continue
        event = session.get(EventRecord, record.event_id)
        if event is None: continue
        session.add(AuditRecord(type="escalation_timeout", reference_id=str(record.id), detail=f"event={record.event_id} sla missed without confirmed delivery; attempts={record.call_attempts}"))
        _retry_or_escalate(session, event, record)
        changed.append(escalation_dict(record))
    return changed

def _verify_twilio_signature(request: Request, form: dict) -> bool:
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not auth_token:
        return True  # no live Twilio credentials configured (mock/dev) -- nothing to verify against
    from twilio.request_validator import RequestValidator

    signature = request.headers.get("X-Twilio-Signature", "")
    url = status_callback_url() or str(request.url)
    return RequestValidator(auth_token).validate(url, form, signature)

@router.post("/voice/status")
async def voice_status_callback(request: Request) -> dict:
    form = dict(await request.form())
    call_sid = form.get("CallSid")
    call_status = str(form.get("CallStatus") or "").strip().lower()
    if not call_sid:
        raise HTTPException(status_code=422, detail="missing CallSid")
    if not _verify_twilio_signature(request, form):
        raise HTTPException(status_code=403, detail="invalid Twilio signature")
    with session_scope() as session:
        call = session.scalar(select(VoiceCallRecord).where(VoiceCallRecord.call_sid == call_sid))
        if call is None:
            return {"received": True, "matched": False}
        call.status = call_status; call.updated_at = datetime.now(timezone.utc)
        escalation = session.scalar(select(EscalationRecord).where(EscalationRecord.event_id == call.event_id))
        if escalation is None:
            return {"received": True, "matched": True}
        if call_status in CONFIRMED_CALL_STATUSES:
            escalation.status = "notified"; escalation.updated_at = datetime.now(timezone.utc)
            session.add(AuditRecord(type="voice_call_confirmed", reference_id=str(call.event_id), detail=f"sid={call_sid} status={call_status}"))
        elif call_status in FAILED_CALL_STATUSES:
            session.add(AuditRecord(type="voice_call_unanswered", reference_id=str(call.event_id), detail=f"sid={call_sid} status={call_status} attempt={escalation.call_attempts}"))
            event = session.get(EventRecord, call.event_id)
            if event is not None and escalation.status not in {"completed", "cancelled", "notified"}:
                _retry_or_escalate(session, event, escalation)
        return {"received": True, "matched": True}

@router.get("/escalations")
def list_escalations(limit: int = Query(default=50, ge=1, le=200), status: str | None = None) -> list[dict]:
    with session_scope() as session:
        statement = select(EscalationRecord)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_STATUSES: raise HTTPException(status_code=422, detail="invalid escalation status")
            statement = statement.where(EscalationRecord.status == normalized)
        rows = session.scalars(statement.order_by(EscalationRecord.id.desc()).limit(limit)).all(); return [escalation_dict(row) for row in rows]

@router.patch("/escalations/{escalation_id}", dependencies=[Depends(require_scope("watch:write"))])
def update_escalation(escalation_id: int, update: EscalationUpdate, principal: Principal = Depends(authenticate)) -> dict:
    normalized = update.status.strip().lower()
    if normalized not in VALID_STATUSES: raise HTTPException(status_code=422, detail="invalid escalation status")
    with session_scope() as session:
        record = session.get(EscalationRecord, escalation_id)
        if record is None: raise HTTPException(status_code=404, detail="escalation not found")
        event = session.get(EventRecord, record.event_id)
        if event and principal.environment != event.environment and "*" not in principal.scopes: raise HTTPException(status_code=403, detail="client cannot update escalations in another environment")
        record.status = normalized; record.updated_at = datetime.now(timezone.utc); session.add(AuditRecord(type="escalation_status_updated", reference_id=str(record.id), detail=f"{normalized} via {principal.name}")); return escalation_dict(record)
