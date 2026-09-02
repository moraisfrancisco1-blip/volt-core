from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import select

from ..db import session_scope
from ..models import AgentInvestigationRecord, MonitoringSweepRecord
from . import agent_inbox, production_monitor

router = APIRouter(prefix="/api", tags=["agent-status"])

# Mirrors the investigation_type value each reactive agent's runner persists.
_INVESTIGATION_AGENTS = [
    ("volt", "voice_call_failure"),
    ("dev_debug", "code_diagnosis"),
    ("database", "database_diagnosis"),
    ("finance", "finance_diagnosis"),
]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@router.get("/agents/status")
def agents_status() -> list[dict]:
    current = agent_inbox.current_message_type()
    with session_scope() as session:
        results = []
        for agent_id, investigation_type in _INVESTIGATION_AGENTS:
            latest = session.scalar(
                select(AgentInvestigationRecord)
                .where(AgentInvestigationRecord.investigation_type == investigation_type)
                .order_by(AgentInvestigationRecord.id.desc())
            )
            if current == investigation_type:
                state = "working"
            elif latest is not None and latest.status == "failed":
                state = "error"
            else:
                state = "idle"
            results.append({
                "agent": agent_id,
                "state": state,
                "last_activity_at": _iso(latest.completed_at or latest.created_at) if latest else None,
                "last_status": latest.status if latest else None,
            })

        sweep_latest = session.scalar(select(MonitoringSweepRecord).order_by(MonitoringSweepRecord.id.desc()))
        if production_monitor.is_sweep_in_progress():
            sweep_state = "working"
        elif sweep_latest is not None and sweep_latest.status == "failed":
            sweep_state = "error"
        else:
            sweep_state = "idle"
        results.append({
            "agent": "production_monitor",
            "state": sweep_state,
            "last_activity_at": _iso(sweep_latest.completed_at or sweep_latest.created_at) if sweep_latest else None,
            "last_status": sweep_latest.status if sweep_latest else None,
        })

        return results
