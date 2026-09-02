from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import finance_runner
from app.agents.stripe_tools import FinanceJob
from app.db import session_scope
from app.models import AgentInvestigationRecord


@pytest.fixture(autouse=True)
def _default_provider_key(monkeypatch):
    # _call_model is always monkeypatched in this file's tests, so the real client is
    # never used -- but run_finance_diagnosis() still calls llm_client.get_client()
    # first, which would raise LLMConfigError with no provider configured at all. A
    # fake Anthropic key keeps that harmless, matching anthropic.Anthropic()'s old
    # lazy-validation behavior these tests already relied on.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key-not-real")


def _tool_use(name, input, id="toolu_1"):
    return {"type": "tool_use", "name": name, "input": input, "id": id}


def _text(text):
    return {"type": "text", "text": text}


def _fake_message(content, stop_reason, input_tokens=77, output_tokens=8):
    return SimpleNamespace(content=content, stop_reason=stop_reason, input_tokens=input_tokens, output_tokens=output_tokens)


def _job(event_id: int, parent_id: int = 42) -> FinanceJob:
    return FinanceJob(
        event_id=event_id, escalation_id=999, system="financerunner-system", environment="production",
        priority="P2", stripe_key_env_var="STRIPE_SECRET_KEY_FINANCERUNNER_TEST", parent_investigation_id=parent_id,
    )


def _latest_finance_diagnosis(event_id: int) -> AgentInvestigationRecord:
    with session_scope() as session:
        row = session.scalar(
            select(AgentInvestigationRecord)
            .where(AgentInvestigationRecord.event_id == event_id, AgentInvestigationRecord.investigation_type == "finance_diagnosis")
            .order_by(AgentInvestigationRecord.id.desc())
        )
        session.expunge(row)
        return row


def test_run_finance_diagnosis_success_after_one_tool_call(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY_FINANCERUNNER_TEST", "fake-key-not-real")
    event_id = 222001
    job = _job(event_id, parent_id=42)

    responses = [
        _fake_message([_tool_use("get_account_balance", {})], "tool_use"),
        _fake_message(
            [_tool_use("submit_investigation_result", {
                "hypothesis": "Balance and recent charges look normal, unlikely to be the cause.",
                "recommended_next_step": "No finance action needed.",
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

    monkeypatch.setattr(finance_runner, "_call_model", fake_call_model)
    monkeypatch.setattr("app.agents.stripe_tools.get_account_balance", lambda job: {"available": [], "pending": []})

    finance_runner.run_finance_diagnosis(job)

    assert len(calls) == 2
    record = _latest_finance_diagnosis(event_id)
    assert record.status == "completed"
    assert record.investigation_type == "finance_diagnosis"
    assert record.parent_investigation_id == 42
    assert record.hypothesis == "Balance and recent charges look normal, unlikely to be the cause."
    assert record.turns_used == 2
    assert record.input_tokens == 77
    assert record.output_tokens == 8


def test_run_finance_diagnosis_fails_fast_without_calling_model_when_credential_unset(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY_FINANCERUNNER_TEST", raising=False)
    event_id = 222002
    job = _job(event_id)

    def spy(client, messages):
        raise AssertionError("_call_model must not be called without the configured Stripe credential")

    monkeypatch.setattr(finance_runner, "_call_model", spy)

    finance_runner.run_finance_diagnosis(job)

    record = _latest_finance_diagnosis(event_id)
    assert record.status == "failed"
    assert "STRIPE_SECRET_KEY_FINANCERUNNER_TEST not configured" in record.error


def test_run_finance_diagnosis_no_tool_use_is_recorded_as_failed(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY_FINANCERUNNER_TEST", "fake-key-not-real")
    event_id = 222003
    job = _job(event_id)

    monkeypatch.setattr(finance_runner, "_call_model", lambda client, messages: _fake_message([_text("Not sure.")], "end_turn"))

    finance_runner.run_finance_diagnosis(job)

    record = _latest_finance_diagnosis(event_id)
    assert record.status == "failed"
    assert "end_turn" in record.error


def test_run_finance_diagnosis_model_exception_is_recorded_as_failed_not_raised(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY_FINANCERUNNER_TEST", "fake-key-not-real")
    event_id = 222004
    job = _job(event_id)

    def fake_call_model(client, messages):
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr(finance_runner, "_call_model", fake_call_model)

    finance_runner.run_finance_diagnosis(job)  # must not raise

    record = _latest_finance_diagnosis(event_id)
    assert record.status == "failed"
    assert "simulated API failure" in record.error


def test_run_finance_diagnosis_exceeds_max_turns_is_recorded_as_failed(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY_FINANCERUNNER_TEST", "fake-key-not-real")
    event_id = 222005
    job = _job(event_id)
    monkeypatch.setattr(finance_runner, "MAX_TURNS", 2)

    monkeypatch.setattr(finance_runner, "_call_model", lambda client, messages: _fake_message([_tool_use("get_account_balance", {})], "tool_use"))
    monkeypatch.setattr("app.agents.stripe_tools.get_account_balance", lambda job: {"available": [], "pending": []})

    finance_runner.run_finance_diagnosis(job)

    record = _latest_finance_diagnosis(event_id)
    assert record.status == "failed"
    assert "exceeded 2 turns" in record.error
