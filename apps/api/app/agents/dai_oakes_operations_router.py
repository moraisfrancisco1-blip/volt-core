from fastapi import APIRouter, Query
from sqlalchemy import select

from ..db import session_scope
from ..models import DaiOakesOperationsInsightRecord
from . import dai_oakes_operations

router = APIRouter(prefix="/api", tags=["dai-oakes-operations"])


def insight_dict(row: DaiOakesOperationsInsightRecord) -> dict:
    return {"id": row.id, "kind": row.kind, "severity": row.severity, "message": row.message,
            "snapshot_id": row.snapshot_id, "created_at": row.created_at.isoformat() if row.created_at else None}


@router.get("/dai-oakes-operations-insights")
def list_insights(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(select(DaiOakesOperationsInsightRecord).order_by(DaiOakesOperationsInsightRecord.id.desc()).limit(limit)).all()
        return [insight_dict(r) for r in rows]


@router.post("/dai-oakes-operations/run")
def run_insights() -> dict:
    # Deterministic and local: reads stored snapshots only, so it is safe (and free) to run
    # synchronously on demand -- no LLM key needed, no thread.
    return dai_oakes_operations.run_operations_insights()
