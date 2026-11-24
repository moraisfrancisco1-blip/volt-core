from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from .. import usage_ledger
from ..db import session_scope
from ..models import DailyBriefingRecord, OutputAuditFindingRecord
from . import approvals_rollup, chief_of_staff, output_auditor

router = APIRouter(prefix="/api/governance", tags=["governance"])


@router.get("/usage")
def usage(days: int = Query(default=1, ge=1, le=90)) -> dict:
    return usage_ledger.usage_report(days=days)


@router.get("/approvals")
def approvals() -> dict:
    return approvals_rollup.pending_approvals()


@router.get("/audit-findings")
def audit_findings(status: str = "open", limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    if status not in {"open", "dismissed"}:
        raise HTTPException(status_code=422, detail="invalid status")
    with session_scope() as session:
        rows = session.scalars(select(OutputAuditFindingRecord).where(OutputAuditFindingRecord.status == status).order_by(OutputAuditFindingRecord.id.desc()).limit(limit)).all()
        return [{"id": r.id, "source": r.source, "source_id": r.source_id, "rule": r.rule, "severity": r.severity, "excerpt": r.excerpt, "status": r.status,
                 "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


@router.post("/audit-findings/{finding_id}/dismiss")
def dismiss_finding(finding_id: int) -> dict:
    # Bookkeeping only: marks a finding as reviewed by a human. Changes nothing about the draft.
    with session_scope() as session:
        row = session.get(OutputAuditFindingRecord, finding_id)
        if row is None:
            raise HTTPException(status_code=404, detail="finding not found")
        row.status = "dismissed"
        return {"id": row.id, "status": row.status}


@router.post("/audit/run")
def run_audit() -> dict:
    return output_auditor.run_output_audit()


@router.post("/daily-cycle")
def daily_cycle() -> dict:
    return chief_of_staff.start_daily_cycle()


@router.get("/briefings")
def briefings(limit: int = Query(default=7, ge=1, le=60)) -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(select(DailyBriefingRecord).order_by(DailyBriefingRecord.id.desc()).limit(limit)).all()
        return [{"id": r.id, "summary": r.summary, "attention_count": r.attention_count, "data": r.data,
                 "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
