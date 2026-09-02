from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import database_runner
from app.agents.database_tools import DatabaseJob
from app.db import session_scope
from app.models import AgentInvestigationRecord


@pytest.fixture(autouse=True)
def _default_provider_key(monkeypatch):
    # _call_model is always monkeypatched in this file's tests, so the real client is
    # never used -- but run_database_diagnosis() still calls llm_client.get_client()
    # first, which would raise LLMConfigError with no provider configured at all. A
    # fake Anthropic key keeps that harmless, matching anthropic.Anthropic()'s old
    # lazy-validation behavior these tests already relied on.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key-not-real")


def _tool_use(name, input, id="toolu_1"):
    return {"type": "tool_use", "name": name, "input": input, "id": id}


def _text(text):
    return {"type": "text", "text": text}


def _fake_message(content, stop_reason, input_tokens=55, output_tokens=6):
    return SimpleNamespace(content=content, stop_reason=stop_reason, input_tokens=input_tokens, output_tokens=output_tokens)


def test_call_tool_handler_drops_arguments_the_handler_does_not_accept():
    def get_backup_status(job):
        return {"job_event_id": job.event_id}

    job = DatabaseJob(event_id=1, escalation_id=2, system="s", environment="production", priority="P1", parent_investigation_id=1)
    result = database_runner._call_tool_handler(get_backup_status, job, {"limit": 20})

    assert result == {"job_event_id": 1}


def _job(event_id: int, parent_id: int = 42) -> DatabaseJob:
    return DatabaseJob(event_id=event_id, escalation_id=999, system="dbrunner-system", environment="production", priority="P2", parent_investigation_id=parent_id)


def _latest_database_diagnosis(event_id: int) -> AgentInvestigationRecord:
    with session_scope() as session:
        row = session.scalar(
            select(AgentInvestigationRecord)
            .where(AgentInvestigationRecord.event_id == event_id, AgentInvestigationRecord.investigation_type == "database_diagnosis")
            .order_by(AgentInvestigationRecord.id.desc())
        )
        session.expunge(row)
        return row


def test_run_database_diagnosis_success_after_one_tool_call(monkeypatch):
    event_id = 111001
    job = _job(event_id, parent_id=42)

    responses = [
        _fake_message([_tool_use("get_connection_health", {})], "tool_use"),
        _fake_message(
            [_tool_use("submit_investigation_result", {
                "hypothesis": "Connections look healthy, unlikely to be the cause.",
                "recommended_next_step": "No database action needed.",
                "confidence": 0.5,
                "is_known_pattern": False,
            })],
            "tool_use",
        ),
    ]
    calls = []

    def fake_call_model(client, messages):
        calls.append(messages)
        return responses[len(calls) - 1]

    monkeypatch.setattr(database_runner, "_call_model", fake_call_model)
    monkeypatch.setattr(
        "app.agents.database_tools.get_connection_health",
        lambda job, **kwargs: {"current_connections": 3, "max_connections": 100},
    )

    database_runner.run_database_diagnosis(job)

    assert len(calls) == 2
    record = _latest_database_diagnosis(event_id)
    assert record.status == "completed"
    assert record.investigation_type == "database_diagnosis"
    assert record.parent_investigation_id == 42
    assert record.hypothesis == "Connections look healthy, unlikely to be the cause."
    assert record.turns_used == 2
    assert record.input_tokens == 55
    assert record.output_tokens == 6


def test_run_database_diagnosis_no_tool_use_is_recorded_as_failed(monkeypatch):
    event_id = 111002
    job = _job(event_id)

    monkeypatch.setattr(database_runner, "_call_model", lambda client, messages: _fake_message([_text("Not sure.")], "end_turn"))

    database_runner.run_database_diagnosis(job)

    record = _latest_database_diagnosis(event_id)
    assert record.status == "failed"
    assert "end_turn" in record.error


def test_run_database_diagnosis_model_exception_is_recorded_as_failed_not_raised(monkeypatch):
    event_id = 111003
    job = _job(event_id)

    def fake_call_model(client, messages):
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr(database_runner, "_call_model", fake_call_model)

    database_runner.run_database_diagnosis(job)  # must not raise

    record = _latest_database_diagnosis(event_id)
    assert record.status == "failed"
    assert "simulated API failure" in record.error


def test_run_database_diagnosis_exceeds_max_turns_is_recorded_as_failed(monkeypatch):
    event_id = 111004
    job = _job(event_id)
    monkeypatch.setattr(database_runner, "MAX_TURNS", 2)

    monkeypatch.setattr(database_runner, "_call_model", lambda client, messages: _fake_message([_tool_use("get_running_queries", {})], "tool_use"))
    monkeypatch.setattr("app.agents.database_tools.get_running_queries", lambda job, **kwargs: {"queries": []})

    database_runner.run_database_diagnosis(job)

    record = _latest_database_diagnosis(event_id)
    assert record.status == "failed"
    assert "exceeded 2 turns" in record.error


# No test for "fails fast without a required credential": unlike Dev/Debug's
# GITHUB_TOKEN gate, this agent has no required credential -- its core tools use the
# app's existing DATABASE_URL connection, and get_backup_status degrades gracefully
# on its own when RAILWAY_TOKEN/VOLT_DB_RAILWAY_* are absent (see test_agents_database_tools.py).
