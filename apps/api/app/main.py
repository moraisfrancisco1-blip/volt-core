from datetime import datetime, timezone
from enum import Enum
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from .voice import MockVoiceProvider, build_voice_script
from .approvals import ApprovalDecision
from .action_gate import ActionEnvironment, ActionStatus, evaluate_action
from .db import Base, engine, session_scope
from .models import SystemRecord, EventRecord, ApprovalRecord, AuditRecord

app = FastAPI(title="VOLT CORE", version="0.7.0")
CALLS = []
ACTIONS = []
voice_provider = MockVoiceProvider()


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


LEVEL_PRIORITY = {"CRITICAL": Priority.P1, "ERROR": Priority.P2, "WARNING": Priority.P3, "INFO": Priority.P4}
ACTION_BY_PRIORITY = {Priority.P1: "call", Priority.P2: "approval", Priority.P3: "notify", Priority.P4: "digest"}


class SystemRegistration(BaseModel):
    name: str
    environment: str = "production"


class WatchEvent(BaseModel):
    system: str
    level: str
    message: str


class VoiceCallRequest(BaseModel):
    event_id: int
    to: str


class ApprovalRequest(BaseModel):
    event_id: int
    action: str


class ApprovalDecisionRequest(BaseModel):
    decision: ApprovalDecision


class ActionRequest(BaseModel):
    approval_id: int
    environment: ActionEnvironment = ActionEnvironment.STAGING


def event_dict(event: EventRecord) -> dict:
    return {"id": event.id, "system": event.system, "level": event.level, "priority": event.priority, "recommended_action": event.recommended_action, "message": event.message, "received_at": event.received_at.isoformat() if event.received_at else None}


@app.get("/health")
def health() -> dict:
    return {"status": "online", "service": "volt-core", "database": "postgresql"}


@app.get("/api/v1/status")
def status() -> dict:
    with session_scope() as session:
        return {"core": "online", "mode": "observe", "production_write": False, "systems": len(session.scalars(select(SystemRecord)).all()), "events": len(session.scalars(select(EventRecord)).all()), "calls": len(CALLS), "approvals": len(session.scalars(select(ApprovalRecord)).all()), "actions": len(ACTIONS)}


@app.post("/api/v1/systems")
def register_system(system: SystemRegistration) -> dict:
    with session_scope() as session:
        record = session.scalar(select(SystemRecord).where(SystemRecord.name == system.name))
        if record is None:
            record = SystemRecord(name=system.name, environment=system.environment, status="connected")
            session.add(record)
        else:
            record.environment = system.environment
            record.status = "connected"
        return {"name": record.name, "environment": record.environment, "status": record.status}


@app.get("/api/v1/systems")
def list_systems() -> list[dict]:
    with session_scope() as session:
        return [{"name": item.name, "environment": item.environment, "status": item.status, "updated_at": item.updated_at.isoformat() if item.updated_at else None} for item in session.scalars(select(SystemRecord)).all()]


@app.post("/api/v1/watch/events")
def ingest_event(event: WatchEvent) -> dict:
    normalized_level = event.level.upper()
    if normalized_level not in LEVEL_PRIORITY:
        raise HTTPException(status_code=422, detail="level must be CRITICAL, ERROR, WARNING or INFO")
    with session_scope() as session:
        system = session.scalar(select(SystemRecord).where(SystemRecord.name == event.system))
        if system is None:
            raise HTTPException(status_code=404, detail="system not registered")
        priority = LEVEL_PRIORITY[normalized_level]
        record = EventRecord(system=event.system, level=normalized_level, priority=priority.value, recommended_action=ACTION_BY_PRIORITY[priority], message=event.message)
        session.add(record)
        session.flush()
        session.add(AuditRecord(type="event_received", reference_id=str(record.id), detail=record.system))
        return event_dict(record)


@app.get("/api/v1/watch/events")
def list_events(limit: int = 50) -> list[dict]:
    with session_scope() as session:
        events = session.scalars(select(EventRecord).order_by(EventRecord.id.desc()).limit(limit)).all()
        return [event_dict(item) for item in events]


@app.get("/api/v1/watch/escalations")
def escalations() -> list[dict]:
    with session_scope() as session:
        events = session.scalars(select(EventRecord).where(EventRecord.priority.in_(["P1", "P2"])).order_by(EventRecord.id.desc())).all()
        return [event_dict(item) for item in events]


@app.post("/api/v1/voice/calls")
def request_voice_call(request: VoiceCallRequest) -> dict:
    with session_scope() as session:
        event = session.get(EventRecord, request.event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        data = event_dict(event)
        if data["priority"] != "P1":
            raise HTTPException(status_code=422, detail="voice calls are reserved for P1 events")
        result = voice_provider.place_call(request.to, build_voice_script(data))
        call = {"id": len(CALLS) + 1, "event_id": event.id, "status": result["status"], "provider": result["provider"], "created_at": datetime.now(timezone.utc).isoformat()}
        CALLS.append(call)
        session.add(AuditRecord(type="voice_call_requested", reference_id=str(call["id"]), detail=str(event.id)))
        return call


@app.get("/api/v1/voice/calls")
def list_voice_calls() -> list[dict]:
    return list(reversed(CALLS))


@app.post("/api/v1/approvals")
def request_approval(request: ApprovalRequest) -> dict:
    with session_scope() as session:
        event = session.get(EventRecord, request.event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        approval = ApprovalRecord(event_id=event.id, system=event.system, action=request.action, decision="pending")
        session.add(approval)
        session.flush()
        session.add(AuditRecord(type="approval_requested", reference_id=str(approval.id), detail=request.action))
        return {"id": approval.id, "event_id": approval.event_id, "system": approval.system, "action": approval.action, "decision": approval.decision, "created_at": approval.created_at.isoformat() if approval.created_at else None, "decided_at": None}


@app.post("/api/v1/approvals/{approval_id}/decision")
def decide_approval(approval_id: int, request: ApprovalDecisionRequest) -> dict:
    with session_scope() as session:
        approval = session.get(ApprovalRecord, approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="approval not found")
        approval.decision = request.decision.value
        approval.decided_at = datetime.now(timezone.utc)
        session.add(AuditRecord(type="approval_decision", reference_id=str(approval_id), detail=approval.decision))
        return {"id": approval.id, "decision": approval.decision, "decided_at": approval.decided_at.isoformat()}


@app.get("/api/v1/approvals")
def list_approvals() -> list[dict]:
    with session_scope() as session:
        approvals = session.scalars(select(ApprovalRecord).order_by(ApprovalRecord.id.desc())).all()
        return [{"id": item.id, "event_id": item.event_id, "system": item.system, "action": item.action, "decision": item.decision, "created_at": item.created_at.isoformat() if item.created_at else None, "decided_at": item.decided_at.isoformat() if item.decided_at else None} for item in approvals]


@app.post("/api/v1/actions")
def request_action(request: ActionRequest) -> dict:
    with session_scope() as session:
        approval = session.get(ApprovalRecord, request.approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="approval not found")
        approval_data = {"id": approval.id, "system": approval.system, "action": approval.action, "decision": approval.decision}
        action = evaluate_action(approval_data, request.environment)
        action["id"] = len(ACTIONS) + 1
        if action["status"] == ActionStatus.READY.value:
            action["status"] = ActionStatus.EXECUTED.value
            action["executed_at"] = datetime.now(timezone.utc).isoformat()
        ACTIONS.append(action)
        session.add(AuditRecord(type="action_evaluated", reference_id=str(action["id"]), detail=action["status"]))
        return action


@app.get("/api/v1/actions")
def list_actions() -> list[dict]:
    return list(reversed(ACTIONS))


@app.get("/api/v1/audit")
def audit_log(limit: int = 100) -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(select(AuditRecord).order_by(AuditRecord.id.desc()).limit(limit)).all()
        return [{"id": item.id, "type": item.type, "reference_id": item.reference_id, "detail": item.detail, "created_at": item.created_at.isoformat() if item.created_at else None} for item in rows]
