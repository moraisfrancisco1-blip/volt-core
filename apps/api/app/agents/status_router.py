from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import select

from ..db import session_scope
from ..models import AgentInvestigationRecord, AuditRecord, DealProposalRecord, DealRecord, MarketIntelligenceReportRecord, MonitoringSweepRecord, SalesLeadRecord, SalesOutreachDraftRecord
from . import agent_inbox, deals_agent, market_intelligence, production_monitor, sales_agent

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

        report_latest = session.scalar(select(MarketIntelligenceReportRecord).order_by(MarketIntelligenceReportRecord.id.desc()))
        if market_intelligence.is_sweep_in_progress():
            report_state = "working"
        elif report_latest is not None and report_latest.status == "failed":
            report_state = "error"
        else:
            report_state = "idle"
        results.append({
            "agent": "market_intelligence",
            "state": report_state,
            "last_activity_at": _iso(report_latest.completed_at or report_latest.created_at) if report_latest else None,
            "last_status": report_latest.status if report_latest else None,
        })

        # Sales has no single "last sweep" record (it processes many leads/drafts per
        # sweep, each failure logged and isolated individually) -- state instead reads
        # the most recent sales_* audit entry, and last_activity_at reads whichever of
        # leads/drafts was touched most recently.
        sales_audit_latest = session.scalar(
            select(AuditRecord).where(AuditRecord.type.like("sales_%")).order_by(AuditRecord.id.desc())
        )
        lead_latest = session.scalar(select(SalesLeadRecord).order_by(SalesLeadRecord.id.desc()))
        draft_latest = session.scalar(select(SalesOutreachDraftRecord).order_by(SalesOutreachDraftRecord.id.desc()))
        lead_activity = (lead_latest.qualified_at or lead_latest.created_at) if lead_latest else None
        draft_activity = draft_latest.created_at if draft_latest else None
        sales_activity = max((t for t in (lead_activity, draft_activity) if t is not None), default=None)
        if sales_agent.is_sweep_in_progress():
            sales_state = "working"
        elif sales_audit_latest is not None and sales_audit_latest.type.endswith("_failed"):
            sales_state = "error"
        else:
            sales_state = "idle"
        results.append({
            "agent": "sales",
            "state": sales_state,
            "last_activity_at": _iso(sales_activity),
            "last_status": "failed" if sales_state == "error" else ("completed" if sales_activity else None),
        })

        # Deals mirrors Sales' audit-based status (many deals/proposals touched per
        # sweep, no single "last sweep" record).
        deals_audit_latest = session.scalar(
            select(AuditRecord).where(AuditRecord.type.like("deal%")).order_by(AuditRecord.id.desc())
        )
        deal_latest = session.scalar(select(DealRecord).order_by(DealRecord.id.desc()))
        proposal_latest = session.scalar(select(DealProposalRecord).order_by(DealProposalRecord.id.desc()))
        deal_activity = deal_latest.stage_changed_at if deal_latest else None
        proposal_activity = proposal_latest.created_at if proposal_latest else None
        deals_activity = max((t for t in (deal_activity, proposal_activity) if t is not None), default=None)
        if deals_agent.is_sweep_in_progress():
            deals_state = "working"
        elif deals_audit_latest is not None and deals_audit_latest.type.endswith("_failed"):
            deals_state = "error"
        else:
            deals_state = "idle"
        results.append({
            "agent": "deals",
            "state": deals_state,
            "last_activity_at": _iso(deals_activity),
            "last_status": "failed" if deals_state == "error" else ("completed" if deals_activity else None),
        })

        return results
