from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="VOLT CORE", version="0.2.0")

SYSTEMS = {}
EVENTS = []


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

    record = {
        "id": len(EVENTS) + 1,
        "system": event.system,
        "level": event.level.upper(),
        "message": event.message,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    EVENTS.append(record)
    return record


@app.get("/api/v1/watch/events")
def list_events(limit: int = 50) -> list[dict]:
    return list(reversed(EVENTS[-limit:]))
