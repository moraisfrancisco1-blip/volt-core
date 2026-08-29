from datetime import datetime, timezone
from enum import Enum
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="VOLT CORE", version="0.3.0")

SYSTEMS = {}
EVENTS = []


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


LEVEL_PRIORITY = {
    "CRITICAL": Priority.P1,
    "ERROR": Priority.P2,
    "WARNING": Priority.P3,
    "INFO": Priority.P4,
}

ACTION_BY_PRIORITY = {
    Priority.P1: "call",
    Priority.P2: "approval",
    Priority.P3: "notify",
    Priority.P4: "digest",
}


class SystemRegistration(BaseModel):
    name: str
    environment: str = "production"


class WatchEvent(BaseModel):
    system: str
    level: str
    message: str


@app.get("/health")
def health() -> dict:
    return {"status": "online", "service": "volt-core"}


@app.get("/api/v1/status")
def status() -> dict:
    return {
        "core": "online",
        "mode": "observe",
        "production_write": False,
        "systems": len(SYSTEMS),
        "events": len(EVENTS),
    }


@app.post("/api/v1/systems")
def register_system(system: SystemRegistration) -> dict:
    SYSTEMS[system.name] = {
        "name": system.name,
        "environment": system.environment,
        "status": "connected",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
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
    action = ACTION_BY_PRIORITY[priority]
    record = {
        "id": len(EVENTS) + 1,
        "system": event.system,
        "level": normalized_level,
        "priority": priority.value,
        "recommended_action": action,
        "message": event.message,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    EVENTS.append(record)
    return record


@app.get("/api/v1/watch/events")
def list_events(limit: int = 50) -> list[dict]:
    return list(reversed(EVENTS[-limit:]))


@app.get("/api/v1/watch/escalations")
def escalations() -> list[dict]:
    return [event for event in reversed(EVENTS) if event["priority"] in {"P1", "P2"}]
