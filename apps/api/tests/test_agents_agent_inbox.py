import pytest
from sqlalchemy import select, update

from app.agents import agent_inbox, code_runner, database_runner, finance_runner, runner
from app.agents.database_tools import DatabaseJob
from app.agents.github_tools import CodeDiagnosisJob
from app.agents.stripe_tools import FinanceJob
from app.agents.tools import InvestigationJob
from app.db import session_scope
from app.models import AgentInboxRecord, AuditRecord


@pytest.fixture(autouse=True)
def _drain_pending_inbox():
    # _claim_next_pending() claims the globally oldest pending row, not scoped to a
    # recipient -- matches production (one worker, one shared table). Other test files
    # (test_agents_runner.py, test_escalations.py) also call post_message and may leave
    # rows pending, so every test here that depends on WHICH row gets claimed needs a
    # clean slate first.
    with session_scope() as session:
        session.execute(update(AgentInboxRecord).where(AgentInboxRecord.status == "pending").values(status="completed"))


def _latest_inbox_row(recipient: str) -> AgentInboxRecord:
    with session_scope() as session:
        row = session.scalar(
            select(AgentInboxRecord).where(AgentInboxRecord.recipient == recipient).order_by(AgentInboxRecord.id.desc())
        )
        session.expunge(row)
        return row


def test_post_message_creates_a_pending_row_with_the_given_fields():
    agent_inbox.post_message(
        sender="volt", recipient="inbox-post-test", message_type="database_diagnosis",
        payload={"event_id": 1, "escalation_id": 2}, content="@inbox-post-test do something",
    )

    row = _latest_inbox_row("inbox-post-test")
    assert row.sender == "volt"
    assert row.message_type == "database_diagnosis"
    assert row.payload == {"event_id": 1, "escalation_id": 2}
    assert row.content == "@inbox-post-test do something"
    assert row.status == "pending"
    assert row.read_at is None
    assert row.completed_at is None


def test_post_message_never_raises_when_the_write_fails(monkeypatch):
    def broken_record(**kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(agent_inbox, "AgentInboxRecord", broken_record)

    with session_scope() as session:
        before = len(session.scalars(select(AuditRecord).where(AuditRecord.type == "agent_inbox_post_failed", AuditRecord.reference_id == "inbox-post-fail-test")).all())

    agent_inbox.post_message(sender="volt", recipient="inbox-post-fail-test", message_type="database_diagnosis", payload={}, content="x")  # must not raise

    with session_scope() as session:
        after = len(session.scalars(select(AuditRecord).where(AuditRecord.type == "agent_inbox_post_failed", AuditRecord.reference_id == "inbox-post-fail-test")).all())
    assert after == before + 1


def test_dispatch_routes_voice_call_failure_to_runner(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "run_investigation", lambda job: calls.append(("runner", job)))

    payload = {"event_id": 1, "escalation_id": 2, "system": "s", "environment": "production", "priority": "P1"}
    agent_inbox._dispatch("voice_call_failure", payload)

    assert len(calls) == 1
    assert calls[0][0] == "runner"
    assert isinstance(calls[0][1], InvestigationJob)
    assert calls[0][1].event_id == 1


def test_dispatch_routes_code_diagnosis_to_code_runner(monkeypatch):
    calls = []
    monkeypatch.setattr(code_runner, "run_code_diagnosis", lambda job: calls.append(("code_runner", job)))

    payload = {"event_id": 1, "escalation_id": 2, "system": "s", "environment": "production", "priority": "P1", "owner": "acme", "repo": "widget", "parent_investigation_id": 1}
    agent_inbox._dispatch("code_diagnosis", payload)

    assert len(calls) == 1
    assert isinstance(calls[0][1], CodeDiagnosisJob)
    assert calls[0][1].owner == "acme"


def test_dispatch_routes_database_diagnosis_to_database_runner(monkeypatch):
    calls = []
    monkeypatch.setattr(database_runner, "run_database_diagnosis", lambda job: calls.append(("database_runner", job)))

    payload = {"event_id": 1, "escalation_id": 2, "system": "s", "environment": "production", "priority": "P1", "parent_investigation_id": 1}
    agent_inbox._dispatch("database_diagnosis", payload)

    assert len(calls) == 1
    assert isinstance(calls[0][1], DatabaseJob)


def test_dispatch_routes_finance_diagnosis_to_finance_runner(monkeypatch):
    calls = []
    monkeypatch.setattr(finance_runner, "run_finance_diagnosis", lambda job: calls.append(("finance_runner", job)))

    payload = {"event_id": 1, "escalation_id": 2, "system": "s", "environment": "production", "priority": "P1", "stripe_key_env_var": "STRIPE_SECRET_KEY_TEST", "parent_investigation_id": 1}
    agent_inbox._dispatch("finance_diagnosis", payload)

    assert len(calls) == 1
    assert isinstance(calls[0][1], FinanceJob)
    assert calls[0][1].stripe_key_env_var == "STRIPE_SECRET_KEY_TEST"


def test_dispatch_raises_type_error_for_unrecognized_message_type():
    with pytest.raises(TypeError):
        agent_inbox._dispatch("not-a-real-message-type", {})


def test_claim_next_pending_returns_none_when_inbox_is_empty():
    assert agent_inbox._claim_next_pending() is None


def test_claim_next_pending_picks_the_oldest_pending_row_and_marks_it_read():
    agent_inbox.post_message(sender="volt", recipient="claim-order-test", message_type="database_diagnosis", payload={"n": 1}, content="first")
    agent_inbox.post_message(sender="volt", recipient="claim-order-test", message_type="database_diagnosis", payload={"n": 2}, content="second")

    claim = agent_inbox._claim_next_pending()
    assert claim is not None
    message_id, message_type, payload = claim
    assert payload["n"] == 1

    with session_scope() as session:
        row = session.get(AgentInboxRecord, message_id)
        assert row.status == "read"
        assert row.read_at is not None


def test_mark_completed_records_success_with_no_error():
    agent_inbox.post_message(sender="volt", recipient="mark-completed-success", message_type="database_diagnosis", payload={}, content="x")
    claim = agent_inbox._claim_next_pending()
    message_id, _message_type, _payload = claim

    agent_inbox._mark_completed(message_id, None)

    with session_scope() as session:
        row = session.get(AgentInboxRecord, message_id)
        assert row.status == "completed"
        assert row.completed_at is not None
        assert row.error is None


def test_mark_completed_records_failure_with_error_and_still_completes():
    agent_inbox.post_message(sender="volt", recipient="mark-completed-failure", message_type="database_diagnosis", payload={}, content="x")
    claim = agent_inbox._claim_next_pending()
    message_id, _message_type, _payload = claim

    agent_inbox._mark_completed(message_id, "RuntimeError: simulated failure")

    with session_scope() as session:
        row = session.get(AgentInboxRecord, message_id)
        assert row.status == "completed"  # never left stuck in "read"
        assert "simulated failure" in row.error


def test_current_message_type_defaults_to_none():
    assert agent_inbox.current_message_type() == agent_inbox._current_message_type


def test_start_agent_inbox_worker_does_nothing_without_any_provider_configured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(agent_inbox, "_started", False)

    agent_inbox.start_agent_inbox_worker()

    assert agent_inbox._started is False


def test_start_agent_inbox_worker_starts_a_thread_when_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(agent_inbox, "_started", False)
    started_threads = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started_threads.append((target, name, daemon))

        def start(self):
            pass  # deliberately never actually run the loop -- no real thread, no network

    monkeypatch.setattr(agent_inbox.threading, "Thread", _FakeThread)

    agent_inbox.start_agent_inbox_worker()

    assert agent_inbox._started is True
    assert len(started_threads) == 1
    assert started_threads[0][1] == "volt-core-agent-worker"
