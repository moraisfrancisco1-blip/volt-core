from types import SimpleNamespace

from sqlalchemy import select

from app.agents import runner
from app.agents.tools import InvestigationJob
from app.db import session_scope
from app.models import AgentInvestigationRecord, EventRecord


class FakeToolUseBlock:
    def __init__(self, name, input, id="toolu_1"):
        self.type = "tool_use"
        self.name = name
        self.input = input
        self.id = id


class FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


def _fake_message(content, stop_reason, input_tokens=111, output_tokens=22):
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens))


def _seed_event(system_id: str) -> int:
    with session_scope() as session:
        event = EventRecord(
            system=system_id, system_id=system_id, system_name=system_id, environment="production",
            level="HIGH", severity="high", priority="P2", recommended_action="call",
            message="Runner probe", status="active",
        )
        session.add(event)
        session.flush()
        return event.id


def _latest_investigation(event_id: int) -> AgentInvestigationRecord:
    with session_scope() as session:
        row = session.scalar(select(AgentInvestigationRecord).where(AgentInvestigationRecord.event_id == event_id).order_by(AgentInvestigationRecord.id.desc()))
        session.expunge(row)
        return row


def test_run_investigation_success_after_one_tool_call(monkeypatch):
    event_id = _seed_event("runner-success-system")
    job = InvestigationJob(event_id=event_id, escalation_id=999, system="runner-success-system", environment="production", priority="P2")

    responses = [
        _fake_message([FakeToolUseBlock("get_incident_event", {})], "tool_use"),
        _fake_message(
            [FakeToolUseBlock("submit_investigation_result", {
                "hypothesis": "The system looks fine, likely a one-off missed call.",
                "recommended_next_step": "Check with the on-call operator manually.",
                "confidence": 0.6,
                "is_known_pattern": False,
            })],
            "tool_use",
        ),
    ]
    calls = []

    def fake_call_model(client, messages):
        calls.append(messages)
        return responses[len(calls) - 1]

    monkeypatch.setattr(runner, "_call_model", fake_call_model)

    runner.run_investigation(job)

    assert len(calls) == 2
    record = _latest_investigation(event_id)
    assert record.status == "completed"
    assert record.hypothesis == "The system looks fine, likely a one-off missed call."
    assert record.recommended_next_step == "Check with the on-call operator manually."
    assert record.confidence == 0.6
    assert record.is_known_pattern is False
    assert record.turns_used == 2
    assert record.input_tokens == 111
    assert record.output_tokens == 22


def test_run_investigation_no_tool_use_is_recorded_as_failed(monkeypatch):
    event_id = _seed_event("runner-no-tool-use-system")
    job = InvestigationJob(event_id=event_id, escalation_id=999, system="runner-no-tool-use-system", environment="production", priority="P2")

    def fake_call_model(client, messages):
        return _fake_message([FakeTextBlock("I don't know what to do.")], "end_turn")

    monkeypatch.setattr(runner, "_call_model", fake_call_model)

    runner.run_investigation(job)

    record = _latest_investigation(event_id)
    assert record.status == "failed"
    assert "end_turn" in record.error


def test_run_investigation_model_exception_is_recorded_as_failed_not_raised(monkeypatch):
    event_id = _seed_event("runner-exception-system")
    job = InvestigationJob(event_id=event_id, escalation_id=999, system="runner-exception-system", environment="production", priority="P2")

    def fake_call_model(client, messages):
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr(runner, "_call_model", fake_call_model)

    runner.run_investigation(job)  # must not raise

    record = _latest_investigation(event_id)
    assert record.status == "failed"
    assert "simulated API failure" in record.error


def test_run_investigation_exceeds_max_turns_is_recorded_as_failed(monkeypatch):
    event_id = _seed_event("runner-max-turns-system")
    job = InvestigationJob(event_id=event_id, escalation_id=999, system="runner-max-turns-system", environment="production", priority="P2")
    monkeypatch.setattr(runner, "MAX_TURNS", 2)

    def fake_call_model(client, messages):
        # Always asks for another (harmless, unknown) tool -- never submits a result.
        return _fake_message([FakeToolUseBlock("get_incident_event", {})], "tool_use")

    monkeypatch.setattr(runner, "_call_model", fake_call_model)

    runner.run_investigation(job)

    record = _latest_investigation(event_id)
    assert record.status == "failed"
    assert "exceeded 2 turns" in record.error
