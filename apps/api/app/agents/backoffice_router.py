import json
import threading

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..db import session_scope
from ..models import AuditRecord, BackOfficeReconciliationRecord, BackOfficeReportRecord, DaiOakesPaymentRecord
from . import backoffice_agent

router = APIRouter(prefix="/api", tags=["backoffice"])

_PAID_STATUSES = {"paid", "succeeded"}


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


def _dai_oakes_payment_dict(record: DaiOakesPaymentRecord) -> dict:
    return {
        "id": record.id,
        "external_id": record.external_id,
        "status": record.status,
        "amount": record.amount,
        "amount_paid": record.amount_paid,
        "currency": record.currency,
        "due_date": record.due_date,
        "paid_at": record.paid_at,
        "source": "dai_oakes_real",
        "synced_at": record.synced_at.isoformat() if record.synced_at else None,
    }


@router.get("/backoffice/dai-oakes-payments")
def list_dai_oakes_payments(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    # Real Dai Oakes data, deliberately never joined against VoltarisOS's deals/leads --
    # they are two unrelated businesses. Every row is explicitly source: "dai_oakes_real"
    # so the frontend can never present it next to VoltarisOS sandbox data unlabeled.
    with session_scope() as session:
        rows = session.scalars(select(DaiOakesPaymentRecord).order_by(DaiOakesPaymentRecord.id.desc()).limit(limit)).all()
        return [_dai_oakes_payment_dict(row) for row in rows]


@router.get("/backoffice/payment-control-summary")
def get_payment_control_summary() -> dict:
    with session_scope() as session:
        rows = session.scalars(select(DaiOakesPaymentRecord)).all()
        # A security incident takes priority over any other status: as long as the most
        # recent Dai Oakes sync audit entry is the incident type, this stays flagged even
        # if payments were synced successfully before it -- a human has to look at this,
        # not have it silently clear on the next successful sweep.
        latest_audit = session.scalar(
            select(AuditRecord).where(AuditRecord.type.like("backoffice_dai_oakes_%") | AuditRecord.type.like("dai_oakes_payment_sync_%")).order_by(AuditRecord.id.desc())
        )
        security_incident = latest_audit is not None and latest_audit.type == "backoffice_dai_oakes_security_incident_failed"

        field_shapes: dict | None = None
        if security_incident:
            source = "dai_oakes_real"
            # Field NAMES (and, below, aggregate shape facts) only, never values --
            # backoffice_agent already enforces that guarantee when it writes the audit
            # detail; this just surfaces it on the dashboard instead of requiring the
            # authenticated /api/v1/audit endpoint to see what triggered the incident.
            # Falls back to the older generic wording for any pre-existing incident row
            # written before detail became JSON.
            note = "Incidente de segurança: resposta da Dai Oakes continha um campo inesperado -- revisão humana necessária antes de continuar a sincronizar."
            try:
                incident_detail = json.loads(latest_audit.detail or "")
                fields = incident_detail["unexpected_fields"]
                entries_affected = incident_detail["entries_affected"]
                note = (
                    f"Incidente de segurança: {entries_affected} registo(s) da resposta da Dai Oakes "
                    f"continham campo(s) inesperado(s) ({', '.join(fields)}) -- revisão humana necessária "
                    "antes de continuar a sincronizar."
                )
                field_shapes = incident_detail.get("unexpected_field_shapes") or None
            except (TypeError, ValueError, KeyError):
                pass
        elif not rows and latest_audit is not None and latest_audit.type == "dai_oakes_payment_sync_skipped":
            source = "no_source_configured"
            note = "sem dados financeiros ainda (VOLT_CORE_SERVICE_KEY_DAIOAKES não configurada)"
        elif not rows and latest_audit is not None and latest_audit.type in ("backoffice_dai_oakes_sync_failed", "dai_oakes_payment_sync_failed"):
            source = "dai_oakes_unavailable"
            note = f"Dai Oakes indisponível neste momento -- não foi possível verificar pagamentos ({latest_audit.detail})." if latest_audit.detail else "Dai Oakes indisponível neste momento -- não foi possível verificar pagamentos."
        elif not rows:
            source = "no_source_configured"
            note = "sem dados financeiros ainda"
        else:
            source = "dai_oakes_real"
            note = None

        paid = sum(1 for r in rows if (r.status or "").lower() in _PAID_STATUSES)
        return {
            "source": source,
            "security_incident": security_incident,
            "note": note,
            "field_shapes": field_shapes,
            "total": len(rows),
            "paid": paid,
            "pending": len(rows) - paid,
        }
