import threading

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..db import session_scope
from ..models import BackOfficeReconciliationRecord, BackOfficeReportRecord
from . import backoffice_agent

router = APIRouter(prefix="/api", tags=["backoffice"])


def reconciliation_dict(record: BackOfficeReconciliationRecord) -> dict:
    return {
        "id": record.id,
        "deal_id": record.deal_id,
        "data_source": record.data_source,
        "match_found": record.match_found,
        "stripe_invoice_id": record.stripe_invoice_id,
        "note": record.note,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def report_dict(record: BackOfficeReportRecord) -> dict:
    return {
        "id": record.id,
        "data_source": record.data_source,
        "deals_closed_count": record.deals_closed_count,
        "deals_matched_count": record.deals_matched_count,
        "deals_unmatched_count": record.deals_unmatched_count,
        "summary": record.summary,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.get("/backoffice/reconciliations")
def list_reconciliations(limit: int = Query(default=50, ge=1, le=200), unmatched_only: bool = False) -> list[dict]:
    with session_scope() as session:
        statement = select(BackOfficeReconciliationRecord)
        if unmatched_only:
            statement = statement.where(BackOfficeReconciliationRecord.match_found.is_(False))
        rows = session.scalars(statement.order_by(BackOfficeReconciliationRecord.id.desc()).limit(limit)).all()
        return [reconciliation_dict(row) for row in rows]


@router.get("/backoffice/reconciliations/{reconciliation_id}")
def get_reconciliation(reconciliation_id: int) -> dict:
    with session_scope() as session:
        record = session.get(BackOfficeReconciliationRecord, reconciliation_id)
        if record is None:
            raise HTTPException(status_code=404, detail="reconciliation not found")
        return reconciliation_dict(record)


@router.get("/backoffice/reports")
def list_reports(limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(select(BackOfficeReportRecord).order_by(BackOfficeReportRecord.id.desc()).limit(limit)).all()
        return [report_dict(row) for row in rows]


@router.get("/backoffice/reports/{report_id}")
def get_report(report_id: int) -> dict:
    with session_scope() as session:
        record = session.get(BackOfficeReportRecord, report_id)
        if record is None:
            raise HTTPException(status_code=404, detail="report not found")
        return report_dict(record)


@router.post("/backoffice/run")
def trigger_backoffice_sweep() -> dict:
    threading.Thread(target=backoffice_agent.run_backoffice_sweep, daemon=True).start()
    return {"triggered": True}
