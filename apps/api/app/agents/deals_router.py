import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import llm_client
from ..db import session_scope
from ..models import AuditRecord, DealProposalRecord, DealRecord, SalesLeadRecord
from . import deals_agent, resend_client

router = APIRouter(prefix="/api", tags=["deals"])

VALID_STAGES = {"qualified", "proposal_prepared", "negotiating", "closed_won", "closed_lost"}
CLOSED_STAGES = {"closed_won", "closed_lost"}
VALID_PROPOSAL_STATUSES = {"pending_approval", "approved_sent", "send_failed"}


class SuggestCloseRequest(BaseModel):
    note: str = Field(min_length=1)


class ConfirmStageRequest(BaseModel):
    stage: str


def deal_dict(deal: DealRecord) -> dict:
    # SQLite (used in tests) doesn't round-trip tzinfo on DateTime(timezone=True)
    # columns the way Postgres (production) does -- normalize to UTC before
    # subtracting so this comparison never raises regardless of backend.
    stage_changed_at = deal.stage_changed_at
    if stage_changed_at is not None and stage_changed_at.tzinfo is None:
        stage_changed_at = stage_changed_at.replace(tzinfo=timezone.utc)
    stale = deal.stage not in CLOSED_STAGES and stage_changed_at is not None and (datetime.now(timezone.utc) - stage_changed_at).days > deals_agent.STALE_DAYS
    return {
        "id": deal.id,
        "lead_id": deal.lead_id,
        "stage": deal.stage,
        "suggested_stage": deal.suggested_stage,
        "suggested_stage_reason": deal.suggested_stage_reason,
        "stage_changed_at": deal.stage_changed_at.isoformat() if deal.stage_changed_at else None,
        "stale": stale,
        "model": deal.model,
        "created_at": deal.created_at.isoformat() if deal.created_at else None,
    }


def proposal_dict(proposal: DealProposalRecord) -> dict:
    return {
        "id": proposal.id,
        "deal_id": proposal.deal_id,
        "price_summary": proposal.price_summary,
        "body": proposal.body,
        "status": proposal.status,
        "model": proposal.model,
        "error": proposal.error,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        "approved_at": proposal.approved_at.isoformat() if proposal.approved_at else None,
    }


@router.get("/deals")
def list_deals(limit: int = Query(default=50, ge=1, le=200), stage: str | None = None) -> list[dict]:
    with session_scope() as session:
        statement = select(DealRecord)
        if stage:
            normalized = stage.strip().lower()
            if normalized not in VALID_STAGES:
                raise HTTPException(status_code=422, detail="invalid deal stage")
            statement = statement.where(DealRecord.stage == normalized)
        rows = session.scalars(statement.order_by(DealRecord.id.desc()).limit(limit)).all()
        return [deal_dict(row) for row in rows]


@router.get("/deals/{deal_id}")
def get_deal(deal_id: int) -> dict:
    with session_scope() as session:
        deal = session.get(DealRecord, deal_id)
        if deal is None:
            raise HTTPException(status_code=404, detail="deal not found")
        return deal_dict(deal)


@router.post("/deals/run")
def trigger_deals_sweep() -> dict:
    if not llm_client.is_configured():
        return {"triggered": False, "reason": "LLM provider (ANTHROPIC_API_KEY/DEEPSEEK_API_KEY/OPENAI_API_KEY) not configured"}
    threading.Thread(target=deals_agent.run_deals_sweep, daemon=True).start()
    return {"triggered": True}


@router.post("/deals/{deal_id}/suggest-close")
def suggest_close(deal_id: int, payload: SuggestCloseRequest) -> dict:
    with session_scope() as session:
        if session.get(DealRecord, deal_id) is None:
            raise HTTPException(status_code=404, detail="deal not found")
    if not llm_client.is_configured():
        return {"triggered": False, "reason": "LLM provider (ANTHROPIC_API_KEY/DEEPSEEK_API_KEY/OPENAI_API_KEY) not configured"}
    threading.Thread(target=deals_agent.run_close_suggestion, args=(deal_id, payload.note), daemon=True).start()
    return {"triggered": True}


@router.post("/deals/{deal_id}/confirm-stage")
def confirm_stage(deal_id: int, payload: ConfirmStageRequest) -> dict:
    # The ONLY place in the whole app that ever writes a terminal stage -- reached only
    # by an explicit human action on the dashboard. Takes the human-specified stage, not
    # a blind copy of suggested_stage, so a person can override the agent's suggestion.
    normalized = payload.stage.strip().lower()
    if normalized not in CLOSED_STAGES:
        raise HTTPException(status_code=422, detail="stage must be closed_won or closed_lost")
    with session_scope() as session:
        deal = session.get(DealRecord, deal_id)
        if deal is None:
            raise HTTPException(status_code=404, detail="deal not found")
        deal.stage = normalized
        deal.stage_changed_at = datetime.now(timezone.utc)
        deal.suggested_stage = None
        deal.suggested_stage_reason = None
        session.add(AuditRecord(type="deal_stage_confirmed", reference_id=str(deal_id), detail=normalized))
        return deal_dict(deal)


@router.get("/deal-proposals")
def list_deal_proposals(limit: int = Query(default=50, ge=1, le=200), status: str | None = None) -> list[dict]:
    with session_scope() as session:
        statement = select(DealProposalRecord)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_PROPOSAL_STATUSES:
                raise HTTPException(status_code=422, detail="invalid proposal status")
            statement = statement.where(DealProposalRecord.status == normalized)
        rows = session.scalars(statement.order_by(DealProposalRecord.id.desc()).limit(limit)).all()
        return [proposal_dict(row) for row in rows]


@router.get("/deal-proposals/{proposal_id}")
def get_deal_proposal(proposal_id: int) -> dict:
    with session_scope() as session:
        proposal = session.get(DealProposalRecord, proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="deal proposal not found")
        return proposal_dict(proposal)


@router.post("/deal-proposals/{proposal_id}/approve-and-send")
def approve_and_send_proposal(proposal_id: int) -> dict:
    # The ONLY place in the whole app that ever calls resend_client.send_email for a
    # deal proposal -- reached only by an explicit human click on the dashboard's
    # "Aprovar e Enviar" button, never from the agent's own sweep. Re-checking status
    # here (not just trusting the UI) is what makes a double-click harmless instead of
    # a double-send.
    with session_scope() as session:
        proposal = session.get(DealProposalRecord, proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="deal proposal not found")
        if proposal.status != "pending_approval":
            return proposal_dict(proposal)
        deal = session.get(DealRecord, proposal.deal_id)
        if deal is None:
            raise HTTPException(status_code=404, detail="deal for this proposal not found")
        lead = session.get(SalesLeadRecord, deal.lead_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="sales lead for this deal not found")

        sent = resend_client.send_email(lead.email, "Proposta comercial VoltarisOS", proposal.body)
        proposal.status = "approved_sent" if sent else "send_failed"
        proposal.approved_at = datetime.now(timezone.utc)
        if sent:
            deal.stage = "negotiating"
            deal.stage_changed_at = datetime.now(timezone.utc)
        else:
            proposal.error = "Resend send failed or not configured -- check RESEND_API_KEY/RESEND_FROM"
        session.add(AuditRecord(type="deal_proposal_approved_and_sent" if sent else "deal_proposal_send_failed", reference_id=str(proposal_id)))
        return proposal_dict(proposal)
