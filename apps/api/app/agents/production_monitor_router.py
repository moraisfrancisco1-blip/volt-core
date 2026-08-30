from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..db import session_scope
from ..models import MonitoringSweepRecord

router = APIRouter(prefix="/api", tags=["monitoring-sweeps"])

VALID_STATUSES = {"completed", "failed"}


def sweep_dict(record: MonitoringSweepRecord) -> dict:
    return {
        "id": record.id,
        "system": record.system,
        "environment": record.environment,
        "status": record.status,
        "event_action": record.event_action,
        "created_event_id": record.created_event_id,
        "summary": record.summary,
        "model": record.model,
        "turns_used": record.turns_used,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "error": record.error,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


@router.get("/monitoring-sweeps")
def list_monitoring_sweeps(
    limit: int = Query(default=50, ge=1, le=200), system: str | None = None, status: str | None = None,
) -> list[dict]:
    with session_scope() as session:
        statement = select(MonitoringSweepRecord)
        if system:
            statement = statement.where(MonitoringSweepRecord.system == system)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_STATUSES:
                raise HTTPException(status_code=422, detail="invalid sweep status")
            statement = statement.where(MonitoringSweepRecord.status == normalized)
        rows = session.scalars(statement.order_by(MonitoringSweepRecord.id.desc()).limit(limit)).all()
        return [sweep_dict(row) for row in rows]


@router.get("/monitoring-sweeps/{sweep_id}")
def get_monitoring_sweep(sweep_id: int) -> dict:
    with session_scope() as session:
        record = session.get(MonitoringSweepRecord, sweep_id)
        if record is None:
            raise HTTPException(status_code=404, detail="monitoring sweep not found")
        return sweep_dict(record)
