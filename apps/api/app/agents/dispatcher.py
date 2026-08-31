from __future__ import annotations

import os
import queue
import threading

from ..db import session_scope
from ..models import AuditRecord
from .database_tools import DatabaseJob
from .github_tools import CodeDiagnosisJob
from .stripe_tools import FinanceJob
from .tools import InvestigationJob

_queue: "queue.Queue[InvestigationJob | CodeDiagnosisJob | DatabaseJob | FinanceJob]" = queue.Queue(maxsize=int(os.getenv("VOLT_AGENT_QUEUE_MAXSIZE", "50")))
_started = False
_lock = threading.Lock()
_current_job_type: str | None = None


def enqueue_investigation(*, event_id: int, escalation_id: int, system: str, environment: str, priority: str) -> None:
    job = InvestigationJob(event_id=event_id, escalation_id=escalation_id, system=system, environment=environment, priority=priority)
    try:
        _queue.put_nowait(job)
    except Exception as exc:
        # Best-effort: a full queue or any other enqueue failure must never propagate
        # back into the escalation state machine that called this.
        with session_scope() as session:
            session.add(AuditRecord(type="investigation_enqueue_failed", reference_id=str(event_id), detail=str(exc)[:500]))


def enqueue_code_diagnosis(*, event_id: int, escalation_id: int, system: str, environment: str, priority: str, owner: str, repo: str, parent_investigation_id: int) -> None:
    job = CodeDiagnosisJob(
        event_id=event_id, escalation_id=escalation_id, system=system, environment=environment,
        priority=priority, owner=owner, repo=repo, parent_investigation_id=parent_investigation_id,
    )
    try:
        _queue.put_nowait(job)
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="investigation_enqueue_failed", reference_id=str(event_id), detail=str(exc)[:500]))


def enqueue_database_diagnosis(*, event_id: int, escalation_id: int, system: str, environment: str, priority: str, parent_investigation_id: int) -> None:
    job = DatabaseJob(
        event_id=event_id, escalation_id=escalation_id, system=system, environment=environment,
        priority=priority, parent_investigation_id=parent_investigation_id,
    )
    try:
        _queue.put_nowait(job)
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="investigation_enqueue_failed", reference_id=str(event_id), detail=str(exc)[:500]))


def enqueue_finance_diagnosis(*, event_id: int, escalation_id: int, system: str, environment: str, priority: str, stripe_key_env_var: str, parent_investigation_id: int) -> None:
    job = FinanceJob(
        event_id=event_id, escalation_id=escalation_id, system=system, environment=environment,
        priority=priority, stripe_key_env_var=stripe_key_env_var, parent_investigation_id=parent_investigation_id,
    )
    try:
        _queue.put_nowait(job)
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="investigation_enqueue_failed", reference_id=str(event_id), detail=str(exc)[:500]))


def _dispatch(job: InvestigationJob | CodeDiagnosisJob | DatabaseJob | FinanceJob) -> None:
    if isinstance(job, CodeDiagnosisJob):
        from . import code_runner
        code_runner.run_code_diagnosis(job)
    elif isinstance(job, DatabaseJob):
        from . import database_runner
        database_runner.run_database_diagnosis(job)
    elif isinstance(job, FinanceJob):
        from . import finance_runner
        finance_runner.run_finance_diagnosis(job)
    elif isinstance(job, InvestigationJob):
        from . import runner
        runner.run_investigation(job)
    else:
        raise TypeError(f"unroutable job type: {type(job).__name__}")


def _job_investigation_type(job: InvestigationJob | CodeDiagnosisJob | DatabaseJob | FinanceJob) -> str:
    # Mirrors the investigation_type values each runner persists -- kept in sync
    # manually since there's no shared enum backing them.
    if isinstance(job, CodeDiagnosisJob):
        return "code_diagnosis"
    if isinstance(job, DatabaseJob):
        return "database_diagnosis"
    if isinstance(job, FinanceJob):
        return "finance_diagnosis"
    return "voice_call_failure"  # InvestigationJob


def current_job_type() -> str | None:
    # The dashboard's only signal that an agent is actively working right now --
    # no persisted job history captures this, since every runner only writes a
    # record once it's done (success or failure), never a "pending" placeholder.
    return _current_job_type


def _worker_loop() -> None:
    global _current_job_type
    while True:
        job = _queue.get()
        _current_job_type = _job_investigation_type(job)
        try:
            _dispatch(job)
        except Exception as exc:
            print(f"[volt-agent] investigation failure: {type(exc).__name__}: {exc}")
        finally:
            _current_job_type = None
            _queue.task_done()


def start_investigation_worker() -> None:
    global _started
    # Mirrors monitoring.py's start_monitoring(): only run the background worker when
    # there's actually something for it to do. Without a key, jobs still enqueue fine
    # (harmless, bounded by VOLT_AGENT_QUEUE_MAXSIZE) but nothing ever consumes them --
    # this specifically keeps every existing test that exercises the escalation/voice
    # flow (and therefore calls enqueue_investigation) from spinning up a thread that
    # would try to construct a real Anthropic client in the background.
    if _started or not os.getenv("ANTHROPIC_API_KEY"):
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_worker_loop, name="volt-core-agent-worker", daemon=True).start()
        _started = True
