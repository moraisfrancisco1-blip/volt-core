from datetime import datetime, timezone
from enum import Enum
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from .voice import get_voice_provider, build_voice_script
from .approvals import ApprovalDecision
from .action_gate import ActionEnvironment, ActionStatus, evaluate_action
from .db import session_scope
from .models import SystemRecord, EventRecord, ApprovalRecord, VoiceCallRecord, ActionRecord, AuditRecord
from .auth import Principal, authenticate, require_scope
from .bootstrap import bootstrap_admin
from .event_history import router as event_history_router

app = FastAPI(title="VOLT CORE", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://volt-core.vercel.app", "https://volt-core-git-main-voltaris-os.vercel.app"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(event_history_router)
voice_provider = get_voice_provider()


@app.on_event("startup")
def startup() -> None:
    bootstrap_admin()


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


def call_dict(call: VoiceCallRecord) -> dict:
    return {"id": call.id, "event_id": call.event_id, "status": call.status, "provider": call.provider, "destination": call.destination, "created_at": call.created_at.isoformat() if call.created_at else None}


def action_dict(action: ActionRecord) -> dict:
    return {"id": action.id, "approval_id": action.approval_id, "system": action.system, "action": action.action, "environment": action.environment, "status": action.status, "reason": action.reason, "executed_at": action.executed_at.isoformat() if action.executed_at else None, "created_at": action.created_at.isoformat() if action.created_at else None}


@app.get("/health")
def health() -> dict:
    return {"status": "online", "service": "volt-core", "database": "postgresql"}


@app.get("/api/v1/dashboard")
def dashboard() -> dict:
    with session_scope() as session:
        systems = session.scalars(select(SystemRecord)).all()
        events = session.scalars(select(EventRecord).order_by(EventRecord.id.desc()).limit(50)).all()
        critical = [item for item in events if item.priority in {"P1", "P2"}]
        return {
            "core": "online", "mode": "observe", "production_write": False,
            "systems": [{"name": item.name, "environment": item.environment, "status": item.status, "updated_at": item.updated_at.isoformat() if item.updated_at else None} for item in systems],
            "events": [event_dict(item) for item in events], "critical_count": len(critical),
        }


@app.get("/api/v1/status", dependencies=[Depends(require_scope("status:read"))])
def status() -> dict:
    with session_scope() as session:
        return {"core": "online", "mode": "observe", "production_write": False, "systems": len(session.scalars(select(SystemRecord)).all()), "events": len(session.scalars(select(EventRecord)).all()), "calls": len(session.scalars(select(VoiceCallRecord)).all()), "approvals": len(session.scalars(select(ApprovalRecord)).all()), "actions": len(session.scalars(select(ActionRecord)).all())}


@app.post("/api/v1/systems", dependencies=[Depends(require_scope("systems:write"))])
def register_system(system: SystemRegistration, principal: Principal = Depends(authenticate)) -> dict:
    if principal.environment != system.environment and "*" not in principal.scopes:
        raise HTTPException(status_code=403, detail="client cannot register systems in another environment")
    with session_scope() as session:
        record = session.scalar(select(SystemRecord).where(SystemRecord.name == system.name))
        if record is None:
            record = SystemRecord(name=system.name, environment=system.environment, status="connected")
            session.add(record)
        else:
            record.environment = system.environment
            record.status = "connected"
        session.add(AuditRecord(type="system_registered", reference_id=system.name, detail=principal.name))
        return {"name": record.name, "environment": record.environment, "status": record.status}


@app.get("/api/v1/systems", dependencies=[Depends(require_scope("systems:read"))])
def list_systems() -> list[dict]:
    with session_scope() as session:
        return [{"name": item.name, "environment": item.environment, "status": item.status, "updated_at": item.updated_at.isoformat() if item.updated_at else None} for item in session.scalars(select(SystemRecord)).all()]


@app.post("/api/v1/watch/events", dependencies=[Depends(require_scope("watch:write"))])
def ingest_event(event: WatchEvent, principal: Principal = Depends(authenticate)) -> dict:
    normalized_level = event.level.upper()
    if normalized_level not in LEVEL_PRIORITY:
        raise HTTPException(status_code=422, detail="level must be CRITICAL, ERROR, WARNING or INFO")
    with session_scope() as session:
        system = session.scalar(select(SystemRecord).where(SystemRecord.name == event.system))
        if system is None:
            raise HTTPException(status_code=404, detail="system not registered")
        if principal.environment != system.environment and "*" not in principal.scopes:
            raise HTTPException(status_code=403, detail="client cannot write events to another environment")
        priority = LEVEL_PRIORITY[normalized_level]
        record = EventRecord(system=event.system, level=normalized_level, priority=priority.value, recommended_action=ACTION_BY_PRIORITY[priority], message=event.message)
        session.add(record)
        session.flush()
        session.add(AuditRecord(type="event_received", reference_id=str(record.id), detail=f"{record.system} via {principal.name}"))
        return event_dict(record)


@app.get("/api/v1/watch/events", dependencies=[Depends(require_scope("watch:read"))])
def list_events(limit: int = 50) -> list[dict]:
    with session_scope() as session:
        events = session.scalars(select(EventRecord).order_by(EventRecord.id.desc()).limit(min(max(limit, 1), 200))).all()
        return [event_dict(item) for item in events]


@app.get("/api/v1/watch/escalations", dependencies=[Depends(require_scope("watch:read"))])
def escalations() -> list[dict]:
    with session_scope() as session:
        events = session.scalars(select(EventRecord).where(EventRecord.priority.in_(["P1", "P2"])).order_by(EventRecord.id.desc())).all()
        return [event_dict(item) for item in events]


@app.post("/api/v1/voice/calls", dependencies=[Depends(require_scope("voice:write"))])
def request_voice_call(request: VoiceCallRequest) -> dict:
    with session_scope() as session:
        event = session.get(EventRecord, request.event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="event not found")
        data = event_dict(event)
        if data["priority"] != "P1":
            raise HTTPException(status_code=422, detail="voice calls are reserved for P1 events")
        script = build_voice_script(data)
        result = voice_provider.place_call(request.to, script)
        call = VoiceCallRecord(event_id=event.id, status=result["status"], provider=result["provider"], destination=request.to, script=script)
        session.add(call)
        session.flush()
        session.add(AuditRecord(type="voice_call_requested", reference_id=str(call.id), detail=str(event.id)))
        return call_dict(call)


@app.get("/api/v1/voice/calls", dependencies=[Depends(require_scope("voice:read"))])
def list_voice_calls(limit: int = 100) -> list[dict]:
    with session_scope() as session:
        calls = session.scalars(select(VoiceCallRecord).order_by(VoiceCallRecord.id.desc()).limit(min(max(limit, 1), 500))).all()
        return [call_dict(item) for item in calls]


@app.post("/api/v1/approvals", dependencies=[Depends(require_scope("approvals:write"))])
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


@app.post("/api/v1/approvals/{approval_id}/decision", dependencies=[Depends(require_scope("approvals:write"))])
def decide_approval(approval_id: int, request: ApprovalDecisionRequest) -> dict:
    with session_scope() as session:
        approval = session.get(ApprovalRecord, approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="approval not found")
        approval.decision = request.decision.value
        approval.decided_at = datetime.now(timezone.utc)
        session.add(AuditRecord(type="approval_decision", reference_id=str(approval_id), detail=approval.decision))
        return {"id": approval.id, "decision": approval.decision, "decided_at": approval.decided_at.isoformat()}


@app.get("/api/v1/approvals", dependencies=[Depends(require_scope("approvals:read"))])
def list_approvals() -> list[dict]:
    with session_scope() as session:
        approvals = session.scalars(select(ApprovalRecord).order_by(ApprovalRecord.id.desc())).all()
        return [{"id": item.id, "event_id": item.event_id, "system": item.system, "action": item.action, "decision": item.decision, "created_at": item.created_at.isoformat() if item.created_at else None, "decided_at": item.decided_at.isoformat() if item.decided_at else None} for item in approvals]


@app.post("/api/v1/actions", dependencies=[Depends(require_scope("actions:write"))])
def request_action(request: ActionRequest) -> dict:
    with session_scope() as session:
        approval = session.get(ApprovalRecord, request.approval_id)
        if approval is None:
            raise HTTPException(status_code=404, detail="approval not found")
        approval_data = {"id": approval.id, "system": approval.system, "action": approval.action, "decision": approval.decision}
        evaluation = evaluate_action(approval_data, request.environment)
        status = evaluation["status"]
        executed_at = datetime.now(timezone.utc) if status == ActionStatus.READY.value else None
        if status == ActionStatus.READY.value:
            status = ActionStatus.EXECUTED.value
        action = ActionRecord(approval_id=approval.id, system=approval.system, action=approval.action, environment=request.environment.value, status=status, reason=evaluation.get("reason"), executed_at=executed_at)
        session.add(action)
        session.flush()
        session.add(AuditRecord(type="action_evaluated", reference_id=str(action.id), detail=action.status))
        return action_dict(action)


@app.get("/api/v1/actions", dependencies=[Depends(require_scope("actions:read"))])
def list_actions(limit: int = 100) -> list[dict]:
    with session_scope() as session:
        actions = session.scalars(select(ActionRecord).order_by(ActionRecord.id.desc()).limit(min(max(limit, 1), 500))).all()
        return [action_dict(item) for item in actions]


@app.get("/api/v1/audit", dependencies=[Depends(require_scope("audit:read"))])
def audit_log(limit: int = 100) -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(select(AuditRecord).order_by(AuditRecord.id.desc()).limit(min(max(limit, 1), 500))).all()
        return [{"id": item.id, "type": item.type, "reference_id": item.reference_id, "detail": item.detail, "created_at": item.created_at.isoformat() if item.created_at else None} for item in rows]
