import threading

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from .. import llm_client
from ..db import session_scope
from ..models import MarketIntelligenceReportRecord
from . import market_intelligence

router = APIRouter(prefix="/api", tags=["market-intelligence"])

VALID_STATUSES = {"completed", "failed"}


def report_dict(record: MarketIntelligenceReportRecord) -> dict:
    return {
        "id": record.id,
        "status": record.status,
        "competitors_summary": record.competitors_summary,
        "regulation_summary": record.regulation_summary,
        "price_signals_summary": record.price_signals_summary,
        "industry_news_summary": record.industry_news_summary,
        "model": record.model,
        "turns_used": record.turns_used,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "telegram_sent": record.telegram_sent,
        "error": record.error,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }


@router.get("/market-intelligence-reports")
def list_market_intelligence_reports(
    limit: int = Query(default=50, ge=1, le=200), status: str | None = None,
) -> list[dict]:
    with session_scope() as session:
        statement = select(MarketIntelligenceReportRecord)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_STATUSES:
                raise HTTPException(status_code=422, detail="invalid report status")
            statement = statement.where(MarketIntelligenceReportRecord.status == normalized)
        rows = session.scalars(statement.order_by(MarketIntelligenceReportRecord.id.desc()).limit(limit)).all()
        return [report_dict(row) for row in rows]


@router.post("/market-intelligence-reports/run")
def trigger_market_intelligence_sweep() -> dict:
    # Fires the same run_weekly_intelligence_sweep() the periodic thread already calls
    # on its own schedule -- this just runs it now instead of waiting. Never blocks the
    # request, same "never block the caller" discipline as production_monitor_router's
    # equivalent endpoint.
    if not llm_client.is_configured():
        return {"triggered": False, "reason": "LLM provider (ANTHROPIC_API_KEY/DEEPSEEK_API_KEY/OPENAI_API_KEY) not configured"}
    threading.Thread(target=market_intelligence.run_weekly_intelligence_sweep, daemon=True).start()
    return {"triggered": True}


@router.get("/market-intelligence-reports/{report_id}")
def get_market_intelligence_report(report_id: int) -> dict:
    with session_scope() as session:
        record = session.get(MarketIntelligenceReportRecord, report_id)
        if record is None:
            raise HTTPException(status_code=404, detail="market intelligence report not found")
        return report_dict(record)
