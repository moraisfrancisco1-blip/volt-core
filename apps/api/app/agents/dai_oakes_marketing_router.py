import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from .. import llm_client
from ..db import session_scope
from ..models import AuditRecord, DaiOakesMarketingContentRecord
from . import dai_oakes_marketing

router = APIRouter(prefix="/api", tags=["dai-oakes-marketing"])

VALID_FORMATS = {"instagram_post", "facebook_post", "blog_post"}
VALID_STATUSES = {"pending_approval", "approved"}


def content_dict(content: DaiOakesMarketingContentRecord) -> dict:
    return {
        "id": content.id,
        "format": content.format,
        "title": content.title,
        "body": content.body,
        "source_facts": content.source_facts,
        "status": content.status,
        "model": content.model,
        "created_at": content.created_at.isoformat() if content.created_at else None,
        "approved_at": content.approved_at.isoformat() if content.approved_at else None,
    }


@router.get("/dai-oakes-marketing-content")
def list_dai_oakes_marketing_content(
    limit: int = Query(default=50, ge=1, le=200), format: str | None = None, status: str | None = None,
) -> list[dict]:
    with session_scope() as session:
        statement = select(DaiOakesMarketingContentRecord)
        if format:
            if format not in VALID_FORMATS:
                raise HTTPException(status_code=422, detail="invalid format")
            statement = statement.where(DaiOakesMarketingContentRecord.format == format)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_STATUSES:
                raise HTTPException(status_code=422, detail="invalid status")
            statement = statement.where(DaiOakesMarketingContentRecord.status == normalized)
        rows = session.scalars(statement.order_by(DaiOakesMarketingContentRecord.id.desc()).limit(limit)).all()
        return [content_dict(row) for row in rows]


@router.get("/dai-oakes-marketing-content/{content_id}")
def get_dai_oakes_marketing_content(content_id: int) -> dict:
    with session_scope() as session:
        content = session.get(DaiOakesMarketingContentRecord, content_id)
        if content is None:
            raise HTTPException(status_code=404, detail="dai oakes marketing content not found")
        return content_dict(content)


@router.post("/dai-oakes-marketing-content/{content_id}/approve")
def approve_dai_oakes_marketing_content(content_id: int) -> dict:
    # This is the ONLY thing "approve" does anywhere in this router: flip a status and
    # stamp a timestamp. There is no publish call here, to any network, ever -- real
    # publishing to a social channel remains a manual step outside this system, same as
    # marketing_router.py's equivalent endpoint for VoltarisOS.
    with session_scope() as session:
        content = session.get(DaiOakesMarketingContentRecord, content_id)
        if content is None:
            raise HTTPException(status_code=404, detail="dai oakes marketing content not found")
        if content.status != "pending_approval":
            return content_dict(content)
        content.status = "approved"
        content.approved_at = datetime.now(timezone.utc)
        session.add(AuditRecord(type="dai_oakes_marketing_content_approved", reference_id=str(content_id)))
        return content_dict(content)


@router.post("/dai-oakes-marketing/run")
def trigger_dai_oakes_marketing_sweep() -> dict:
    if not llm_client.is_configured():
        return {"triggered": False, "reason": "LLM provider (ANTHROPIC_API_KEY/DEEPSEEK_API_KEY/OPENAI_API_KEY) not configured"}
    threading.Thread(target=dai_oakes_marketing.run_marketing_sweep, daemon=True).start()
    return {"triggered": True}
