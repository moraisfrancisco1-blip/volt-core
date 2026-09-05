import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from .. import llm_client
from ..db import session_scope
from ..models import AuditRecord, MarketingContentRecord
from . import marketing_agent

router = APIRouter(prefix="/api", tags=["marketing"])

VALID_CONTENT_TYPES = {"blog_post", "social_post"}
VALID_AUDIENCES = {"consumer", "b2b_partner", "both"}
VALID_STATUSES = {"pending_approval", "approved"}


def content_dict(content: MarketingContentRecord) -> dict:
    return {
        "id": content.id,
        "content_type": content.content_type,
        "format": content.format,
        "audience": content.audience,
        "parent_content_id": content.parent_content_id,
        "title": content.title,
        "body": content.body,
        "source_facts": content.source_facts,
        "status": content.status,
        "model": content.model,
        "created_at": content.created_at.isoformat() if content.created_at else None,
        "approved_at": content.approved_at.isoformat() if content.approved_at else None,
    }


@router.get("/marketing-content")
def list_marketing_content(
    limit: int = Query(default=50, ge=1, le=200), content_type: str | None = None,
    audience: str | None = None, status: str | None = None,
) -> list[dict]:
    with session_scope() as session:
        statement = select(MarketingContentRecord)
        if content_type:
            if content_type not in VALID_CONTENT_TYPES:
                raise HTTPException(status_code=422, detail="invalid content_type")
            statement = statement.where(MarketingContentRecord.content_type == content_type)
        if audience:
            if audience not in VALID_AUDIENCES:
                raise HTTPException(status_code=422, detail="invalid audience")
            statement = statement.where(MarketingContentRecord.audience == audience)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_STATUSES:
                raise HTTPException(status_code=422, detail="invalid status")
            statement = statement.where(MarketingContentRecord.status == normalized)
        rows = session.scalars(statement.order_by(MarketingContentRecord.id.desc()).limit(limit)).all()
        return [content_dict(row) for row in rows]


@router.get("/marketing-content/{content_id}")
def get_marketing_content(content_id: int) -> dict:
    with session_scope() as session:
        content = session.get(MarketingContentRecord, content_id)
        if content is None:
            raise HTTPException(status_code=404, detail="marketing content not found")
        return content_dict(content)


@router.post("/marketing-content/{content_id}/repurpose")
def repurpose_content(content_id: int) -> dict:
    with session_scope() as session:
        if session.get(MarketingContentRecord, content_id) is None:
            raise HTTPException(status_code=404, detail="marketing content not found")
    if not llm_client.is_configured():
        return {"triggered": False, "reason": "LLM provider (ANTHROPIC_API_KEY/DEEPSEEK_API_KEY/OPENAI_API_KEY) not configured"}
    threading.Thread(target=marketing_agent.run_repurpose_content, args=(content_id,), daemon=True).start()
    return {"triggered": True}


@router.post("/marketing-content/{content_id}/approve")
def approve_content(content_id: int) -> dict:
    # This is the ONLY thing "approve" does anywhere in this router: flip a status and
    # stamp a timestamp. There is no publish call here, to any network, ever -- real
    # publishing to a social channel remains a manual step outside this system.
    with session_scope() as session:
        content = session.get(MarketingContentRecord, content_id)
        if content is None:
            raise HTTPException(status_code=404, detail="marketing content not found")
        if content.status != "pending_approval":
            return content_dict(content)
        content.status = "approved"
        content.approved_at = datetime.now(timezone.utc)
        session.add(AuditRecord(type="marketing_content_approved", reference_id=str(content_id)))
        return content_dict(content)


@router.post("/marketing/run")
def trigger_marketing_sweep() -> dict:
    if not llm_client.is_configured():
        return {"triggered": False, "reason": "LLM provider (ANTHROPIC_API_KEY/DEEPSEEK_API_KEY/OPENAI_API_KEY) not configured"}
    threading.Thread(target=marketing_agent.run_marketing_sweep, daemon=True).start()
    return {"triggered": True}


@router.get("/marketing/performance")
def marketing_performance() -> dict:
    # No analytics source is wired up anywhere in volt-core -- this stays a fixed,
    # explicit statement rather than ever inventing a number. Ready to report real
    # data later without changing this route's contract.
    return {"summary": "sem dados de performance ainda"}
