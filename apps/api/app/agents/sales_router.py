import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import llm_client
from ..auth import Principal, authenticate, require_scope
from ..db import session_scope
from ..models import AuditRecord, SalesLeadRecord, SalesOutreachDraftRecord
from . import resend_client, sales_agent

router = APIRouter(prefix="/api", tags=["sales"])

VALID_LEAD_STATUSES = {"new", "qualified", "dismissed"}
VALID_DRAFT_STATUSES = {"pending_approval", "approved_sent", "send_failed"}


class SalesLeadIngestion(BaseModel):
    # No lead_type field on purpose -- this endpoint is for VoltarisOS's own inbound
    # signup flow (demo requests, waitlist, trial starts) only. lead_type is always
    # forced to "consumer_inbound" server-side; a caller cannot claim any other consent
    # basis through this payload. B2B partner leads only ever come from the fixed,
    # human-maintained VOLT_SALES_B2B_PROSPECTS list, never through this endpoint.
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=255)
    source: str | None = Field(default=None, max_length=120)
    context: str | None = None


def lead_dict(lead: SalesLeadRecord) -> dict:
    return {
        "id": lead.id,
        "lead_type": lead.lead_type,
        "status": lead.status,
        "source": lead.source,
        "name": lead.name,
        "email": lead.email,
        "company": lead.company,
        "context": lead.context,
        "consent_basis": lead.consent_basis,
        "fit_score": lead.fit_score,
        "qualification_summary": lead.qualification_summary,
        "suggested_next_step": lead.suggested_next_step,
        "scheduled_call_at": lead.scheduled_call_at.isoformat() if lead.scheduled_call_at else None,
        "call_prep_summary": lead.call_prep_summary,
        "model": lead.model,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "qualified_at": lead.qualified_at.isoformat() if lead.qualified_at else None,
    }


def draft_dict(draft: SalesOutreachDraftRecord) -> dict:
    return {
        "id": draft.id,
        "lead_id": draft.lead_id,
        "subject": draft.subject,
        "body": draft.body,
        "status": draft.status,
        "model": draft.model,
        "error": draft.error,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "approved_at": draft.approved_at.isoformat() if draft.approved_at else None,
    }


@router.post("/sales-leads", dependencies=[Depends(require_scope("sales:write"))])
def ingest_sales_lead(payload: SalesLeadIngestion, principal: Principal = Depends(authenticate)) -> dict:
    with session_scope() as session:
        lead = SalesLeadRecord(
            lead_type="consumer_inbound",
            status="new",
            source=payload.source or "voltarisos_inbound",
            name=payload.name,
            email=payload.email.strip().lower(),
            context=payload.context,
            consent_basis="inbound_signup",
        )
        session.add(lead)
        session.flush()
        session.add(AuditRecord(type="sales_lead_ingested", reference_id=str(lead.id), detail=f"via {principal.name}"))
        return lead_dict(lead)


@router.get("/sales-leads")
def list_sales_leads(
    limit: int = Query(default=50, ge=1, le=200), lead_type: str | None = None, status: str | None = None,
) -> list[dict]:
    with session_scope() as session:
        statement = select(SalesLeadRecord)
        if lead_type:
            statement = statement.where(SalesLeadRecord.lead_type == lead_type)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_LEAD_STATUSES:
                raise HTTPException(status_code=422, detail="invalid lead status")
            statement = statement.where(SalesLeadRecord.status == normalized)
        rows = session.scalars(statement.order_by(SalesLeadRecord.id.desc()).limit(limit)).all()
        return [lead_dict(row) for row in rows]


@router.get("/sales-leads/{lead_id}")
def get_sales_lead(lead_id: int) -> dict:
    with session_scope() as session:
        lead = session.get(SalesLeadRecord, lead_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="sales lead not found")
        return lead_dict(lead)


@router.post("/sales-leads/{lead_id}/prepare-call")
def prepare_call(lead_id: int) -> dict:
    with session_scope() as session:
        if session.get(SalesLeadRecord, lead_id) is None:
            raise HTTPException(status_code=404, detail="sales lead not found")
    if not llm_client.is_configured():
        return {"triggered": False, "reason": "LLM provider (ANTHROPIC_API_KEY/DEEPSEEK_API_KEY/OPENAI_API_KEY) not configured"}
    threading.Thread(target=sales_agent.run_call_prep, args=(lead_id,), daemon=True).start()
    return {"triggered": True}


@router.post("/sales/run")
def trigger_sales_sweep() -> dict:
    if not llm_client.is_configured():
        return {"triggered": False, "reason": "LLM provider (ANTHROPIC_API_KEY/DEEPSEEK_API_KEY/OPENAI_API_KEY) not configured"}
    threading.Thread(target=sales_agent.run_sales_sweep, daemon=True).start()
    return {"triggered": True}


@router.get("/sales-outreach-drafts")
def list_sales_outreach_drafts(limit: int = Query(default=50, ge=1, le=200), status: str | None = None) -> list[dict]:
    with session_scope() as session:
        statement = select(SalesOutreachDraftRecord)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_DRAFT_STATUSES:
                raise HTTPException(status_code=422, detail="invalid draft status")
            statement = statement.where(SalesOutreachDraftRecord.status == normalized)
        rows = session.scalars(statement.order_by(SalesOutreachDraftRecord.id.desc()).limit(limit)).all()
        return [draft_dict(row) for row in rows]


@router.get("/sales-outreach-drafts/{draft_id}")
def get_sales_outreach_draft(draft_id: int) -> dict:
    with session_scope() as session:
        draft = session.get(SalesOutreachDraftRecord, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="sales outreach draft not found")
        return draft_dict(draft)


@router.post("/sales-outreach-drafts/{draft_id}/approve-and-send")
def approve_and_send_outreach_draft(draft_id: int) -> dict:
    # The ONLY place in the whole app that ever calls resend_client.send_email -- reached
    # only by an explicit human click on the dashboard's "Aprovar e Enviar" button, never
    # from the agent's own sweep. Re-checking status here (not just trusting the UI) is
    # what makes a double-click harmless instead of a double-send.
    with session_scope() as session:
        draft = session.get(SalesOutreachDraftRecord, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="sales outreach draft not found")
        if draft.status != "pending_approval":
            return draft_dict(draft)
        lead = session.get(SalesLeadRecord, draft.lead_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="sales lead for this draft not found")

        sent = resend_client.send_email(lead.email, draft.subject, draft.body)
        draft.status = "approved_sent" if sent else "send_failed"
        draft.approved_at = datetime.now(timezone.utc)
        if not sent:
            draft.error = "Resend send failed or not configured -- check RESEND_API_KEY/RESEND_FROM"
        session.add(AuditRecord(type="sales_outreach_approved_and_sent" if sent else "sales_outreach_send_failed", reference_id=str(draft_id)))
        return draft_dict(draft)
