from datetime import datetime, timezone
from enum import Enum
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from .voice import MockVoiceProvider, build_voice_script
from .approvals import ApprovalDecision, apply_decision, create_approval
from .action_gate import ActionEnvironment, ActionStatus, evaluate_action

app = FastAPI(title="VOLT CORE", version="0.6.0")
SYSTEMS = {}
EVENTS = []
CALLS = []
APPROVALS = []
ACTIONS = []
AUDIT_LOG = []
voice_provider = MockVoiceProvider()


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


@app.get("/health")
def health() -> dict:
    return {"status": "online", "service": "volt-core"}


@app.get("/api/v1/status")
def status() -> dict:
    return {"core": "online", "mode": "observe", "production_write": False, "systems": len(SYSTEMS), "events": len(EVENTS), "calls": len(CALLS), "approvals": len(APPROVALS), "actions": len(ACTIONS)}


@app.post("/api/v1/systems")
def register_system(system: SystemRegistration) -> dict:
    SYSTEMS[system.name] = {"name": system.name, "environment": system.environment, "status": "connected", "updated_at": datetime.now(timezone.utc).isoformat()}
    return SYSTEMS[system.name]


@app.get("/api/v1/systems")
def list_systems() -> list[dict]:
    return list(SYSTEMS.values())


@app.post("/api/v1/watch/events")
def ingest_event(event: WatchEvent) -> dict:
    if event.system not in SYSTEMS:
        raise HTTPException(status_code=404, detail="system not registered")
    normalized_level = event.level.upper()
    if normalized_level not in LEVEL_PRIORITY:
        raise HTTPException(status_code=422, detail="level must be CRITICAL, ERROR, WARNING or INFO")
    priority = LEVEL_PRIORITY[normalized_level]
    record = {"id": len(EVENTS) + 1, "system": event.system, "level": normalized_level, "priority": priority.value, "recommended_action": ACTION_BY_PRIORITY[priority], "message": event.message, "received_at": datetime.now(timezone.utc).isoformat()}
    EVENTS.append(record)
    AUDIT_LOG.append({"type": "event_received", "event_id": record["id"], "created_at": record["received_at"]})
    return record


@app.get("/api/v1/watch/events")
def list_events(limit: int = 50) -> list[dict]:
    return list(reversed(EVENTS[-limit:]))


@app.get("/api/v1/watch/escalations")
def escalations() -> list[dict]:
    return [event for event in reversed(EVENTS) if event["priority"] in {"P1", "P2"}]


@app.post("/api/v1/voice/calls")
def request_voice_call(request: VoiceCallRequest) -> dict:
    event = next((item for item in EVENTS if item["id"] == request.event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    if event["priority"] != "P1":
        raise HTTPException(status_code=422, detail="voice calls are reserved for P1 events")
    result = voice_provider.place_call(request.to, build_voice_script(event))
    call = {"id": len(CALLS) + 1, "event_id": event["id"], "status": result["status"], "provider": result["provider"], "created_at": datetime.now(timezone.utc).isoformat()}
    CALLS.append(call)
    AUDIT_LOG.append({"type": "voice_call_requested", "call_id": call["id"], "created_at": call["created_at"]})
    return call


@app.get("/api/v1/voice/calls")
def list_voice_calls() -> list[dict]:
    return list(reversed(CALLS))


@app.post("/api/v1/approvals")
def request_approval(request: ApprovalRequest) -> dict:
    event = next((item for item in EVENTS if item["id"] == request.event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    approval = create_approval(len(APPROVALS) + 1, event, request.action)
    APPROVALS.append(approval)
    AUDIT_LOG.append({"type": "approval_requested", "approval_id": approval["id"], "created_at": approval["created_at"]})
    return approval


@app.post("/api/v1/approvals/{approval_id}/decision")
def decide_approval(approval_id: int, request: ApprovalDecisionRequest) -> dict:
    approval = next((item for item in APPROVALS if item["id"] == approval_id), None)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    apply_decision(approval, request.decision)
    AUDIT_LOG.append({"type": "approval_decision", "approval_id": approval_id, "decision": approval["decision"], "created_at": approval["decided_at"]})
    return approval


@app.get("/api/v1/approvals")
def list_approvals() -> list[dict]:
    return list(reversed(APPROVALS))


@app.post("/api/v1/actions")
def request_action(request: ActionRequest) -> dict:
    approval = next((item for item in APPROVALS if item["id"] == request.approval_id), None)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    action = evaluate_action(approval, request.environment)
    action["id"] = len(ACTIONS) + 1
    if action["status"] == ActionStatus.READY.value:
        action["status"] = ActionStatus.EXECUTED.value
        action["executed_at"] = datetime.now(timezone.utc).isoformat()
    ACTIONS.append(action)
    AUDIT_LOG.append({"type": "action_evaluated", "action_id": action["id"], "status": action["status"], "created_at": datetime.now(timezone.utc).isoformat()})
    return action


@app.get("/api/v1/actions")
def list_actions() -> list[dict]:
    return list(reversed(ACTIONS))


@app.get("/api/v1/audit")
def audit_log(limit: int = 100) -> list[dict]:
    return list(reversed(AUDIT_LOG[-limit:]))
