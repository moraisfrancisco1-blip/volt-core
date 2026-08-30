import queue

from sqlalchemy import select

from app.agents import code_runner, dispatcher, runner
from app.agents.github_tools import CodeDiagnosisJob
from app.agents.tools import InvestigationJob
from app.db import session_scope
from app.escalations import _retry_or_escalate
from app.models import AuditRecord, EscalationRecord, EventRecord


def _seed_event_and_escalation(system_id: str, *, priority: str, action: str, call_attempts: int) -> tuple[int, int]:
    with session_scope() as session:
        event = EventRecord(
            system=system_id, system_id=system_id, system_name=system_id, environment="production",
            level="HIGH", severity="high", priority=priority, recommended_action=action,
            message="Dispatcher probe", status="active",
        )
        session.add(event)
        session.flush()
        escalation = EscalationRecord(event_id=event.id, system=system_id, priority=priority, action=action, status="calling", call_attempts=call_attempts)
        session.add(escalation)
        session.flush()
        return event.id, escalation.id


def test_enqueue_investigation_puts_a_well_formed_job(monkeypatch):
    fresh_queue: "queue.Queue" = queue.Queue(maxsize=10)
    monkeypatch.setattr(dispatcher, "_queue", fresh_queue)

    dispatcher.enqueue_investigation(event_id=1, escalation_id=2, system="dispatcher-sys", environment="production", priority="P1")

    job = fresh_queue.get_nowait()
    assert job.event_id == 1
    assert job.escalation_id == 2
    assert job.system == "dispatcher-sys"
    assert job.environment == "production"
    assert job.priority == "P1"


def test_enqueue_investigation_full_queue_writes_audit_record_and_does_not_raise(monkeypatch):
    full_queue: "queue.Queue" = queue.Queue(maxsize=1)
    full_queue.put_nowait("occupying-the-only-slot")
    monkeypatch.setattr(dispatcher, "_queue", full_queue)

    with session_scope() as session:
        before = len(session.scalars(select(AuditRecord).where(AuditRecord.type == "investigation_enqueue_failed", AuditRecord.reference_id == "42")).all())

    dispatcher.enqueue_investigation(event_id=42, escalation_id=43, system="dispatcher-full", environment="production", priority="P1")

    with session_scope() as session:
        after = len(session.scalars(select(AuditRecord).where(AuditRecord.type == "investigation_enqueue_failed", AuditRecord.reference_id == "42")).all())
    assert after == before + 1


def test_p4_escalation_never_enqueues_an_investigation(monkeypatch):
    fresh_queue: "queue.Queue" = queue.Queue(maxsize=10)
    monkeypatch.setattr(dispatcher, "_queue", fresh_queue)
    event_id, escalation_id = _seed_event_and_escalation("dispatcher-p4", priority="P4", action="digest", call_attempts=0)

    with session_scope() as session:
        session_event = session.get(EventRecord, event_id)
        session_escalation = session.get(EscalationRecord, escalation_id)
        _retry_or_escalate(session, session_event, session_escalation)

    assert fresh_queue.empty()


def test_second_failure_at_same_priority_does_not_enqueue_again(monkeypatch):
    fresh_queue: "queue.Queue" = queue.Queue(maxsize=10)
    monkeypatch.setattr(dispatcher, "_queue", fresh_queue)
    # call_attempts=2 means this is a retry after an already-investigated first failure.
    event_id, escalation_id = _seed_event_and_escalation("dispatcher-retry", priority="P2", action="call", call_attempts=2)

    with session_scope() as session:
        session_event = session.get(EventRecord, event_id)
        session_escalation = session.get(EscalationRecord, escalation_id)
        _retry_or_escalate(session, session_event, session_escalation)

    assert fresh_queue.empty()


def test_first_failure_at_p1_p2_or_p3_enqueues_exactly_once(monkeypatch):
    fresh_queue: "queue.Queue" = queue.Queue(maxsize=10)
    monkeypatch.setattr(dispatcher, "_queue", fresh_queue)
    event_id, escalation_id = _seed_event_and_escalation("dispatcher-first-failure", priority="P3", action="call", call_attempts=1)

    with session_scope() as session:
        session_event = session.get(EventRecord, event_id)
        session_escalation = session.get(EscalationRecord, escalation_id)
        _retry_or_escalate(session, session_event, session_escalation)

    assert fresh_queue.qsize() == 1
    job = fresh_queue.get_nowait()
    assert job.event_id == event_id
    assert job.escalation_id == escalation_id


def test_start_investigation_worker_does_nothing_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(dispatcher, "_started", False)

    dispatcher.start_investigation_worker()

    assert dispatcher._started is False


def test_start_investigation_worker_starts_a_thread_when_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(dispatcher, "_started", False)
    started_threads = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started_threads.append((target, name, daemon))

        def start(self):
            pass  # deliberately never actually run the loop -- no real thread, no network

    monkeypatch.setattr(dispatcher.threading, "Thread", _FakeThread)

    dispatcher.start_investigation_worker()

    assert dispatcher._started is True
    assert len(started_threads) == 1
    assert started_threads[0][1] == "volt-core-jarvis"


def test_enqueue_code_diagnosis_puts_a_well_formed_job(monkeypatch):
    fresh_queue: "queue.Queue" = queue.Queue(maxsize=10)
    monkeypatch.setattr(dispatcher, "_queue", fresh_queue)

    dispatcher.enqueue_code_diagnosis(event_id=1, escalation_id=2, system="dispatcher-sys", environment="production", priority="P2", owner="acme", repo="widget", parent_investigation_id=7)

    job = fresh_queue.get_nowait()
    assert isinstance(job, CodeDiagnosisJob)
    assert job.owner == "acme"
    assert job.repo == "widget"
    assert job.parent_investigation_id == 7


def test_enqueue_code_diagnosis_full_queue_writes_audit_record_and_does_not_raise(monkeypatch):
    full_queue: "queue.Queue" = queue.Queue(maxsize=1)
    full_queue.put_nowait("occupying-the-only-slot")
    monkeypatch.setattr(dispatcher, "_queue", full_queue)

    with session_scope() as session:
        before = len(session.scalars(select(AuditRecord).where(AuditRecord.type == "investigation_enqueue_failed", AuditRecord.reference_id == "84")).all())

    dispatcher.enqueue_code_diagnosis(event_id=84, escalation_id=85, system="dispatcher-full-code", environment="production", priority="P2", owner="acme", repo="widget", parent_investigation_id=7)

    with session_scope() as session:
        after = len(session.scalars(select(AuditRecord).where(AuditRecord.type == "investigation_enqueue_failed", AuditRecord.reference_id == "84")).all())
    assert after == before + 1


def test_dispatch_routes_investigation_job_to_runner(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "run_investigation", lambda job: calls.append(("runner", job)))
    monkeypatch.setattr(code_runner, "run_code_diagnosis", lambda job: calls.append(("code_runner", job)))

    job = InvestigationJob(event_id=1, escalation_id=2, system="s", environment="production", priority="P1")
    dispatcher._dispatch(job)

    assert calls == [("runner", job)]


def test_dispatch_routes_code_diagnosis_job_to_code_runner(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "run_investigation", lambda job: calls.append(("runner", job)))
    monkeypatch.setattr(code_runner, "run_code_diagnosis", lambda job: calls.append(("code_runner", job)))

    job = CodeDiagnosisJob(event_id=1, escalation_id=2, system="s", environment="production", priority="P1", owner="acme", repo="widget", parent_investigation_id=1)
    dispatcher._dispatch(job)

    assert calls == [("code_runner", job)]
