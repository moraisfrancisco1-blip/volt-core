from datetime import datetime, timezone
from enum import Enum
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from .voice import get_voice_provider, build_voice_script
from .approvals import ApprovalDecision
from .action_gate import ActionEnvironment, ActionStatus, evaluate_action
from .agents.agent_inbox import start_agent_inbox_worker
from .agents.production_monitor import start_production_monitor
from .agents.market_intelligence import start_market_intelligence
from .agents.sales_agent import start_sales_agent
from .agents.deals_agent import start_deals_agent
from .agents.marketing_agent import start_marketing_agent
from .agents.telegram_scheduler import start_telegram_scheduler
from .agents.production_monitor_router import router as monitoring_sweeps_router
from .agents.market_intelligence_router import router as market_intelligence_router
from .agents.sales_router import router as sales_router
from .agents.deals_router import router as deals_router
from .agents.marketing_router import router as marketing_router
from .agents.router import router as investigations_router
from .agents.status_router import router as agent_status_router
from .integrations_router import VOLT_CORS_ORIGINS, router as integrations_status_router
from .db import session_scope
from .models import SystemRecord, EventRecord, ApprovalRecord, VoiceCallRecord, ActionRecord, AuditRecord
from .auth import Principal, authenticate, require_scope
from .bootstrap import bootstrap_admin
from .event_history import router as event_history_router, EventIngestion, create_event, event_dict as detailed_event_dict
from .monitoring import start_monitoring, monitoring_status, run_controlled_self_test
from .telegram import router as telegram_router

app = FastAPI(title="VOLT CORE", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=VOLT_CORS_ORIGINS, allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "OPTIONS"], allow_headers=["*"])
app.include_router(event_history_router)
app.include_router(investigations_router)
app.include_router(monitoring_sweeps_router)
app.include_router(market_intelligence_router)
app.include_router(sales_router)
app.include_router(deals_router)
app.include_router(marketing_router)
app.include_router(agent_status_router)
app.include_router(integrations_status_router)
app.include_router(telegram_router)
voice_provider = get_voice_provider()

@app.on_event("startup")
def startup() -> None:
    bootstrap_admin(); start_monitoring(); run_controlled_self_test(); start_agent_inbox_worker(); start_production_monitor(); start_market_intelligence(); start_sales_agent(); start_deals_agent(); start_marketing_agent(); start_telegram_scheduler()

class Priority(str, Enum): P1 = "P1"; P2 = "P2"; P3 = "P3"; P4 = "P4"
LEVEL_PRIORITY = {"CRITICAL": Priority.P1, "ERROR": Priority.P2, "WARNING": Priority.P3, "INFO": Priority.P4}
ACTION_BY_PRIORITY = {Priority.P1: "call", Priority.P2: "call", Priority.P3: "call", Priority.P4: "digest"}
VOICE_PRIORITIES = {"P1", "P2", "P3"}
class SystemRegistration(BaseModel): name: str; environment: str = "production"
class WatchEvent(BaseModel): system: str; level: str; message: str
class VoiceCallRequest(BaseModel): event_id: int; to: str
class ApprovalRequest(BaseModel): event_id: int; action: str
class ApprovalDecisionRequest(BaseModel): decision: ApprovalDecision
class ActionRequest(BaseModel): approval_id: int; environment: ActionEnvironment = ActionEnvironment.STAGING

def event_dict(event: EventRecord) -> dict:
    return {"id": event.id, "system": event.system, "level": event.level, "priority": event.priority, "recommended_action": event.recommended_action, "message": event.message, "received_at": event.received_at.isoformat() if event.received_at else None}
def call_dict(call: VoiceCallRecord) -> dict:
    return {"id": call.id, "event_id": call.event_id, "status": call.status, "provider": call.provider, "destination": call.destination, "created_at": call.created_at.isoformat() if call.created_at else None}
def action_dict(action: ActionRecord) -> dict:
    return {"id": action.id, "approval_id": action.approval_id, "system": action.system, "action": action.action, "environment": action.environment, "status": action.status, "reason": action.reason, "executed_at": action.executed_at.isoformat() if action.executed_at else None, "created_at": action.created_at.isoformat() if action.created_at else None}

@app.get("/health")
def health() -> dict: return {"status": "online", "service": "volt-core", "database": "postgresql"}
@app.get("/api/v1/monitoring")
def monitoring() -> dict: return monitoring_status()
@app.get("/api/v1/dashboard")
def dashboard() -> dict:
    with session_scope() as session:
        systems = session.scalars(select(SystemRecord)).all(); events = session.scalars(select(EventRecord).order_by(EventRecord.id.desc()).limit(50)).all(); critical = [i for i in events if i.priority in {"P1", "P2"}]
        return {"core": "online", "mode": "observe", "production_write": False, "systems": [{"name": i.name, "environment": i.environment, "status": i.status, "updated_at": i.updated_at.isoformat() if i.updated_at else None} for i in systems], "events": [event_dict(i) for i in events], "critical_count": len(critical), "monitoring": monitoring_status()}
@app.get("/api/v1/status", dependencies=[Depends(require_scope("status:read"))])
def status() -> dict:
    with session_scope() as session: return {"core": "online", "mode": "observe", "production_write": False, "systems": len(session.scalars(select(SystemRecord)).all()), "events": len(session.scalars(select(EventRecord)).all()), "calls": len(session.scalars(select(VoiceCallRecord)).all()), "approvals": len(session.scalars(select(ApprovalRecord)).all()), "actions": len(session.scalars(select(ActionRecord)).all())}
@app.post("/api/v1/systems", dependencies=[Depends(require_scope("systems:write"))])
def register_system(system: SystemRegistration, principal: Principal = Depends(authenticate)) -> dict:
    if principal.environment != system.environment and "*" not in principal.scopes: raise HTTPException(status_code=403, detail="client cannot register systems to another environment")
    with session_scope() as session:
        record = session.scalar(select(SystemRecord).where(SystemRecord.name == system.name))
        if record is None: record = SystemRecord(name=system.name, environment=system.environment, status="connected"); session.add(record)
        else: record.environment = system.environment; record.status = "connected"
        session.add(AuditRecord(type="system_registered", reference_id=system.name, detail=principal.name)); return {"name": record.name, "environment": record.environment, "status": record.status}
@app.get("/api/v1/systems", dependencies=[Depends(require_scope("systems:read"))])
def list_systems() -> list[dict]:
    with session_scope() as session: return [{"name": i.name, "environment": i.environment, "status": i.status, "updated_at": i.updated_at.isoformat() if i.updated_at else None} for i in session.scalars(select(SystemRecord)).all()]
@app.post("/api/v1/watch/events", dependencies=[Depends(require_scope("watch:write"))])
def ingest_event(event: WatchEvent, principal: Principal = Depends(authenticate)) -> dict:
    normalized_level = event.level.upper()
    if normalized_level not in LEVEL_PRIORITY: raise HTTPException(status_code=422, detail="level must be CRITICAL, ERROR, WARNING or INFO")
    severity = {"CRITICAL": "critical", "ERROR": "high", "WARNING": "medium", "INFO": "info"}[normalized_level]
    with session_scope() as session:
        record = create_event(session, EventIngestion(system_id=event.system, system_name=event.system, environment=principal.environment, severity=severity, event_type="legacy_watch", title=event.message[:255], message=event.message, source="legacy-watch"), principal)
        return event_dict(record)
@app.get("/api/v1/watch/events", dependencies=[Depends(require_scope("watch:read"))])
def list_events(limit: int = 50) -> list[dict]:
    with session_scope() as session: return [event_dict(i) for i in session.scalars(select(EventRecord).order_by(EventRecord.id.desc()).limit(min(max(limit,1),200))).all()]
@app.get("/api/v1/watch/escalations", dependencies=[Depends(require_scope("watch:read"))])
def escalations() -> list[dict]:
    with session_scope() as session: return [event_dict(i) for i in session.scalars(select(EventRecord).where(EventRecord.priority.in_(["P1","P2","P3"])).order_by(EventRecord.id.desc())).all()]
@app.post("/api/v1/voice/calls", dependencies=[Depends(require_scope("voice:write"))])
def request_voice_call(request: VoiceCallRequest) -> dict:
    with session_scope() as session:
        event = session.get(EventRecord, request.event_id)
        if event is None: raise HTTPException(status_code=404, detail="event not found")
        data = event_dict(event)
        if data["priority"] not in VOICE_PRIORITIES: raise HTTPException(status_code=422, detail="voice calls are reserved for P1, P2 and P3 events")
        script = build_voice_script(data); result = voice_provider.place_call(request.to, script); call = VoiceCallRecord(event_id=event.id, status=result["status"], provider=result["provider"], destination=request.to, script=script); session.add(call); session.flush(); session.add(AuditRecord(type="voice_call_requested", reference_id=str(call.id), detail=str(event.id))); return call_dict(call)
@app.get("/api/v1/voice/calls", dependencies=[Depends(require_scope("voice:read"))])
def list_voice_calls(limit: int = 100) -> list[dict]:
    with session_scope() as session: return [call_dict(i) for i in session.scalars(select(VoiceCallRecord).order_by(VoiceCallRecord.id.desc()).limit(min(max(limit,1),500))).all()]
@app.post("/api/v1/approvals", dependencies=[Depends(require_scope("approvals:write"))])
def request_approval(request: ApprovalRequest) -> dict:
    with session_scope() as session:
        event = session.get(EventRecord, request.event_id)
        if event is None: raise HTTPException(status_code=404, detail="event not found")
        approval = ApprovalRecord(event_id=event.id, system=event.system, action=request.action, decision="pending"); session.add(approval); session.flush(); session.add(AuditRecord(type="approval_requested", reference_id=str(approval.id), detail=request.action)); return {"id": approval.id, "event_id": approval.event_id, "system": approval.system, "action": approval.action, "decision": approval.decision, "created_at": approval.created_at.isoformat() if approval.created_at else None, "decided_at": None}
@app.post("/api/v1/approvals/{approval_id}/decision", dependencies=[Depends(require_scope("approvals:write"))])
def decide_approval(approval_id: int, request: ApprovalDecisionRequest) -> dict:
    with session_scope() as session:
        approval = session.get(ApprovalRecord, approval_id)
        if approval is None: raise HTTPException(status_code=404, detail="approval not found")
        approval.decision = request.decision.value; approval.decided_at = datetime.now(timezone.utc); session.add(AuditRecord(type="approval_decision", reference_id=str(approval_id), detail=approval.decision)); return {"id": approval.id, "decision": approval.decision, "decided_at": approval.decided_at.isoformat()}
@app.get("/api/v1/approvals", dependencies=[Depends(require_scope("approvals:read"))])
def list_approvals() -> list[dict]:
    with session_scope() as session: return [{"id": i.id, "event_id": i.event_id, "system": i.system, "action": i.action, "decision": i.decision, "created_at": i.created_at.isoformat() if i.created_at else None, "decided_at": i.decided_at.isoformat() if i.decided_at else None} for i in session.scalars(select(ApprovalRecord).order_by(ApprovalRecord.id.desc())).all()]
@app.post("/api/v1/actions", dependencies=[Depends(require_scope("actions:write"))])
def request_action(request: ActionRequest) -> dict:
    with session_scope() as session:
        approval = session.get(ApprovalRecord, request.approval_id)
        if approval is None: raise HTTPException(status_code=404, detail="approval not found")
        evaluation = evaluate_action({"id": approval.id, "system": approval.system, "action": approval.action, "decision": approval.decision}, request.environment); status = evaluation["status"]; executed_at = datetime.now(timezone.utc) if status == ActionStatus.READY.value else None
        if status == ActionStatus.READY.value: status = ActionStatus.EXECUTED.value
        action = ActionRecord(approval_id=approval.id, system=approval.system, action=approval.action, environment=request.environment.value, status=status, reason=evaluation.get("reason"), executed_at=executed_at); session.add(action); session.flush(); session.add(AuditRecord(type="action_evaluated", reference_id=str(action.id), detail=action.status)); return action_dict(action)
@app.get("/api/v1/actions", dependencies=[Depends(require_scope("actions:read"))])
def list_actions(limit: int = 100) -> list[dict]:
    with session_scope() as session: return [action_dict(i) for i in session.scalars(select(ActionRecord).order_by(ActionRecord.id.desc()).limit(min(max(limit,1),500))).all()]
@app.get("/api/v1/audit", dependencies=[Depends(require_scope("audit:read"))])
def audit_log(limit: int = 100) -> list[dict]:
    with session_scope() as session: return [{"id": i.id, "type": i.type, "reference_id": i.reference_id, "detail": i.detail, "created_at": i.created_at.isoformat() if i.created_at else None} for i in session.scalars(select(AuditRecord).order_by(AuditRecord.id.desc()).limit(min(max(limit,1),500))).all()]
