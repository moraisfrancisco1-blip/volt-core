from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..db import session_scope
from ..models import AgentInvestigationRecord

router = APIRouter(prefix="/api", tags=["investigations"])

VALID_STATUSES = {"pending", "completed", "failed"}


def investigation_dict(record: AgentInvestigationRecord) -> dict:
    return {
        "id": record.id,
        "event_id": record.event_id,
        "escalation_id": record.escalation_id,
        "investigation_type": record.investigation_type,
        "system": record.system,
        "environment": record.environment,
        "priority": record.priority,
        "status": record.status,
        "hypothesis": record.hypothesis,
        "recommended_next_step": record.recommended_next_step,
        "confidence": record.confidence,
        "is_known_pattern": record.is_known_pattern,
        "model": record.model,
        "turns_used": record.turns_used,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "error": record.error,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


@router.get("/investigations")
def list_investigations(
    limit: int = Query(default=50, ge=1, le=200), event_id: int | None = None, status: str | None = None
) -> list[dict]:
    with session_scope() as session:
        statement = select(AgentInvestigationRecord)
        if event_id is not None:
            statement = statement.where(AgentInvestigationRecord.event_id == event_id)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_STATUSES:
                raise HTTPException(status_code=422, detail="invalid investigation status")
            statement = statement.where(AgentInvestigationRecord.status == normalized)
        rows = session.scalars(statement.order_by(AgentInvestigationRecord.id.desc()).limit(limit)).all()
        return [investigation_dict(row) for row in rows]


@router.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: int) -> dict:
    with session_scope() as session:
        record = session.get(AgentInvestigationRecord, investigation_id)
        if record is None:
            raise HTTPException(status_code=404, detail="investigation not found")
        return investigation_dict(record)
