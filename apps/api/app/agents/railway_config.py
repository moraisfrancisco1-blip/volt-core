from __future__ import annotations

import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RailwaySweepTarget:
    project_id: str
    service_id: str
    environment_id: str
    environment: str  # human label ("production"), not the Railway environment UUID


def resolve_railway_service(system: str) -> RailwaySweepTarget | None:
    raw = os.getenv("VOLT_SYSTEM_RAILWAY", "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    entry = payload.get(system)
    if not isinstance(entry, dict):
        return None
    project_id = str(entry.get("projectId") or "").strip()
    service_id = str(entry.get("serviceId") or "").strip()
    environment_id = str(entry.get("environmentId") or "").strip()
    environment = str(entry.get("environment") or "production").strip()
    if not (project_id and service_id and environment_id):
        return None
    return RailwaySweepTarget(project_id, service_id, environment_id, environment)


def sweep_system_ids() -> list[str]:
    raw = os.getenv("VOLT_SYSTEM_RAILWAY", "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    return list(payload.keys())
