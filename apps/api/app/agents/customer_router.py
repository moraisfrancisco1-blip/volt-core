import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import llm_client
from ..auth import Principal, authenticate, require_scope
from ..db import session_scope
from ..models import AuditRecord, CustomerQueryPatternRecord, CustomerQueryRecord, CustomerResponseDraftRecord
from . import customer_agent, resend_client

router = APIRouter(prefix="/api", tags=["customer"])

VALID_QUERY_STATUSES = {"new", "simple", "sensitive_escalated"}
VALID_DRAFT_STATUSES = {"pending_approval", "approved_sent", "send_failed"}


class CustomerQueryIngestion(BaseModel):
    # source defaults to "manual_test" -- there is no real support channel connected to
    # VOLT CORE yet, so every query ingested through this endpoint is understood to be a
    # human-entered test case (via the bootstrap key) proving the mechanism, not live
    # traffic from a real channel this system doesn't have.
    customer_name: str | None = Field(default=None, max_length=160)
    customer_email: str | None = Field(default=None, max_length=255)
    question: str = Field(min_length=1)
    source: str | None = Field(default=None, max_length=64)


def query_dict(query: CustomerQueryRecord) -> dict:
    return {
        "id": query.id,
        "source": query.source,
        "customer_name": query.customer_name,
        "customer_email": query.customer_email,
        "question": query.question,
        "classification": query.classification,
        "sensitive_reason": query.sensitive_reason,
        "status": query.status,
        "created_at": query.created_at.isoformat() if query.created_at else None,
        "triaged_at": query.triaged_at.isoformat() if query.triaged_at else None,
    }


def draft_dict(draft: CustomerResponseDraftRecord) -> dict:
    return {
        "id": draft.id,
        "query_id": draft.query_id,
        "subject": draft.subject,
        "body": draft.body,
        "status": draft.status,
        "model": draft.model,
        "error": draft.error,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "approved_at": draft.approved_at.isoformat() if draft.approved_at else None,
    }


def pattern_dict(pattern: CustomerQueryPatternRecord) -> dict:
    return {
        "id": pattern.id,
        "example_question": pattern.example_question,
        "occurrence_count": pattern.occurrence_count,
        "first_seen_at": pattern.first_seen_at.isoformat() if pattern.first_seen_at else None,
        "last_seen_at": pattern.last_seen_at.isoformat() if pattern.last_seen_at else None,
    }


@router.post("/customer-queries", dependencies=[Depends(require_scope("customer:write"))])
def ingest_customer_query(payload: CustomerQueryIngestion, principal: Principal = Depends(authenticate)) -> dict:
    with session_scope() as session:
        query = CustomerQueryRecord(
            source=payload.source or "manual_test",
            customer_name=payload.customer_name,
            customer_email=payload.customer_email.strip().lower() if payload.customer_email else None,
            question=payload.question,
            status="new",
        )
        session.add(query)
        session.flush()
        session.add(AuditRecord(type="customer_query_ingested", reference_id=str(query.id), detail=f"via {principal.name}"))
        return query_dict(query)


@router.get("/customer-queries")
def list_customer_queries(limit: int = Query(default=50, ge=1, le=200), status: str | None = None) -> list[dict]:
    with session_scope() as session:
        statement = select(CustomerQueryRecord)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_QUERY_STATUSES:
                raise HTTPException(status_code=422, detail="invalid query status")
            statement = statement.where(CustomerQueryRecord.status == normalized)
        rows = session.scalars(statement.order_by(CustomerQueryRecord.id.desc()).limit(limit)).all()
        return [query_dict(row) for row in rows]


@router.get("/customer-queries/{query_id}")
def get_customer_query(query_id: int) -> dict:
    with session_scope() as session:
        query = session.get(CustomerQueryRecord, query_id)
        if query is None:
            raise HTTPException(status_code=404, detail="customer query not found")
        return query_dict(query)


@router.post("/customer/run")
def trigger_customer_sweep() -> dict:
    if not llm_client.is_configured():
        return {"triggered": False, "reason": "LLM provider (ANTHROPIC_API_KEY/DEEPSEEK_API_KEY/OPENAI_API_KEY) not configured"}
    threading.Thread(target=customer_agent.run_customer_sweep, daemon=True).start()
    return {"triggered": True}


@router.get("/customer-response-drafts")
def list_customer_response_drafts(limit: int = Query(default=50, ge=1, le=200), status: str | None = None) -> list[dict]:
    with session_scope() as session:
        statement = select(CustomerResponseDraftRecord)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_DRAFT_STATUSES:
                raise HTTPException(status_code=422, detail="invalid draft status")
            statement = statement.where(CustomerResponseDraftRecord.status == normalized)
        rows = session.scalars(statement.order_by(CustomerResponseDraftRecord.id.desc()).limit(limit)).all()
        return [draft_dict(row) for row in rows]


@router.get("/customer-response-drafts/{draft_id}")
def get_customer_response_draft(draft_id: int) -> dict:
    with session_scope() as session:
        draft = session.get(CustomerResponseDraftRecord, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="customer response draft not found")
        return draft_dict(draft)


@router.post("/customer-response-drafts/{draft_id}/approve-and-send")
def approve_and_send_response_draft(draft_id: int) -> dict:
    # The ONLY place in the whole app that ever sends a customer response -- reached
    # only by an explicit human click on the dashboard's "Aprovar e Enviar" button,
    # never from the agent's own sweep. Re-checking status here (not just trusting the
    # UI) is what makes a double-click harmless instead of a double-send.
    with session_scope() as session:
        draft = session.get(CustomerResponseDraftRecord, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="customer response draft not found")
        if draft.status != "pending_approval":
            return draft_dict(draft)
        query = session.get(CustomerQueryRecord, draft.query_id)
        if query is None:
            raise HTTPException(status_code=404, detail="customer query for this draft not found")
        if not query.customer_email:
            draft.status = "send_failed"
            draft.error = "sem email de contacto associado a este pedido"
            draft.approved_at = datetime.now(timezone.utc)
            session.add(AuditRecord(type="customer_response_send_failed", reference_id=str(draft_id), detail="no customer_email"))
            return draft_dict(draft)

        sent = resend_client.send_email(query.customer_email, draft.subject, draft.body)
        draft.status = "approved_sent" if sent else "send_failed"
        draft.approved_at = datetime.now(timezone.utc)
        if not sent:
            draft.error = "Resend send failed or not configured -- check RESEND_API_KEY/RESEND_FROM"
        session.add(AuditRecord(type="customer_response_approved_and_sent" if sent else "customer_response_send_failed", reference_id=str(draft_id)))
        return draft_dict(draft)


@router.get("/customer-query-patterns")
def list_customer_query_patterns(limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(
            select(CustomerQueryPatternRecord).order_by(CustomerQueryPatternRecord.occurrence_count.desc()).limit(limit)
        ).all()
        return [pattern_dict(row) for row in rows]
