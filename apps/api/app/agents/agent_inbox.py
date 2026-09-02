from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from .. import llm_client
from ..db import session_scope
from ..models import AgentInboxRecord, AuditRecord

_wake_event = threading.Event()
_started = False
_lock = threading.Lock()
_current_message_type: str | None = None
_POLL_FALLBACK_SECONDS = float(os.getenv("VOLT_AGENT_INBOX_POLL_SECONDS", "5"))


def post_message(session=None, *, sender: str, recipient: str, message_type: str, payload: dict[str, Any], content: str) -> None:
    # Best-effort: a DB write failure here must never propagate back into the
    # escalation state machine or the investigation runner that called this --
    # mirrors dispatcher.py's enqueue_* try/except-into-AuditRecord discipline.
    #
    # `session` is optional: callers that already hold an open session_scope (e.g.
    # escalations.py's _retry_or_escalate/trigger_manual_investigation) must pass it
    # in and reuse it -- opening a second, independent session_scope here while the
    # caller's transaction is still open deadlocks SQLite ("database is locked") and
    # is unsafe under concurrent writers on Postgres too. Callers with no ambient
    # session (runner.py's _maybe_chain_to_* helpers, called after their own
    # session_scope block has already closed) omit it and get a self-contained write.
    try:
        record = AgentInboxRecord(sender=sender, recipient=recipient, message_type=message_type, payload=payload, content=content, status="pending")
        if session is not None:
            session.add(record)
            session.flush()
        else:
            with session_scope() as s:
                s.add(record)
        _wake_event.set()  # best-effort -- if the caller's own transaction hasn't
        # committed yet, the poll fallback in _worker_loop picks the row up shortly after
    except Exception as exc:
        # Always a fresh, independent session for the audit fallback -- the primary
        # write's session may be poisoned/aborted by whatever just failed on it.
        with session_scope() as s:
            s.add(AuditRecord(type="agent_inbox_post_failed", reference_id=recipient, detail=str(exc)[:500]))


def _dispatch(message_type: str, payload: dict[str, Any]) -> None:
    if message_type == "code_diagnosis":
        from . import code_runner
        from .github_tools import CodeDiagnosisJob
        code_runner.run_code_diagnosis(CodeDiagnosisJob(**payload))
    elif message_type == "database_diagnosis":
        from . import database_runner
        from .database_tools import DatabaseJob
        database_runner.run_database_diagnosis(DatabaseJob(**payload))
    elif message_type == "finance_diagnosis":
        from . import finance_runner
        from .stripe_tools import FinanceJob
        finance_runner.run_finance_diagnosis(FinanceJob(**payload))
    elif message_type == "voice_call_failure":
        from . import runner
        from .tools import InvestigationJob
        runner.run_investigation(InvestigationJob(**payload))
    else:
        raise TypeError(f"unroutable message_type: {message_type}")


def current_message_type() -> str | None:
    # The dashboard's only signal that an agent is actively working right now --
    # same role as dispatcher.current_job_type() before it.
    return _current_message_type


def _claim_next_pending() -> tuple[int, str, dict[str, Any]] | None:
    with session_scope() as session:
        row = session.scalar(
            select(AgentInboxRecord)
            .where(AgentInboxRecord.status == "pending")
            .order_by(AgentInboxRecord.id.asc())
            .limit(1)
        )
        if row is None:
            return None
        row.status = "read"
        row.read_at = datetime.now(timezone.utc)
        return row.id, row.message_type, dict(row.payload or {})


def _mark_completed(message_id: int, error: str | None) -> None:
    with session_scope() as session:
        row = session.get(AgentInboxRecord, message_id)
        if row is None:
            return
        row.status = "completed"
        row.completed_at = datetime.now(timezone.utc)
        if error:
            row.error = error[:2000]


def _worker_loop() -> None:
    global _current_message_type
    while True:
        claim = _claim_next_pending()
        if claim is None:
            _wake_event.wait(timeout=_POLL_FALLBACK_SECONDS)
            _wake_event.clear()
            continue
        message_id, message_type, payload = claim
        _current_message_type = message_type
        error: str | None = None
        try:
            _dispatch(message_type, payload)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            print(f"[volt-agent] inbox dispatch failure: {error}")
        finally:
            _current_message_type = None
            _mark_completed(message_id, error)


def start_agent_inbox_worker() -> None:
    global _started
    # Mirrors dispatcher.start_investigation_worker(): only run the background worker
    # when there's actually something for it to do. Without a provider configured,
    # messages still post fine but nothing ever consumes them -- keeps every existing
    # test that exercises the escalation/voice flow (and therefore calls post_message)
    # from spinning up a thread that would try to construct a real LLM client in the
    # background.
    if _started or not llm_client.is_configured():
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_worker_loop, name="volt-core-agent-worker", daemon=True).start()
        _started = True
