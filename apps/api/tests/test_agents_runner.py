from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import repo_config, runner, stripe_config
from app.agents.tools import InvestigationJob
from app.db import session_scope
from app.models import AgentInboxRecord, AgentInvestigationRecord, AuditRecord, EventRecord


@pytest.fixture(autouse=True)
def _default_provider_key(monkeypatch):
    # _call_model is always monkeypatched in this file's tests, so the real client is
    # never used -- but run_investigation() still calls llm_client.get_client() first,
    # which would raise LLMConfigError with no provider configured at all. A fake
    # Anthropic key keeps that harmless, matching anthropic.Anthropic()'s old
    # lazy-validation behavior these tests already relied on.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key-not-real")


def _tool_use(name, input, id="toolu_1"):
    return {"type": "tool_use", "name": name, "input": input, "id": id}


def _text(text):
    return {"type": "text", "text": text}


def _fake_message(content, stop_reason, input_tokens=111, output_tokens=22):
    return SimpleNamespace(content=content, stop_reason=stop_reason, input_tokens=input_tokens, output_tokens=output_tokens)


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


def _inbox_rows_for_event(event_id: int) -> list[AgentInboxRecord]:
    with session_scope() as session:
        rows = session.scalars(select(AgentInboxRecord).where(AgentInboxRecord.sender == "volt")).all()
        matching = [row for row in rows if (row.payload or {}).get("event_id") == event_id]
        for row in matching:
            session.expunge(row)
        return matching


def test_run_investigation_success_after_one_tool_call(monkeypatch):
    event_id = _seed_event("runner-success-system")
    job = InvestigationJob(event_id=event_id, escalation_id=999, system="runner-success-system", environment="production", priority="P2")

    responses = [
        _fake_message([_tool_use("get_incident_event", {})], "tool_use"),
        _fake_message(
            [_tool_use("submit_investigation_result", {
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


def test_call_tool_handler_drops_arguments_the_handler_does_not_accept():
    # Reproduces a real production crash: DeepSeek called get_incident_event (a
    # zero-parameter tool per its own schema) with an unsolicited "limit" argument,
    # and get_incident_event(job) has no **kwargs to absorb it.
    def get_incident_event(job):
        return {"job_event_id": job.event_id}

    job = InvestigationJob(event_id=1, escalation_id=2, system="s", environment="production", priority="P1")
    result = runner._call_tool_handler(get_incident_event, job, {"limit": 20})

    assert result == {"job_event_id": 1}


def test_call_tool_handler_still_passes_through_arguments_the_handler_does_accept():
    def get_recent_system_events(job, limit=20):
        return {"limit_used": limit}

    job = InvestigationJob(event_id=1, escalation_id=2, system="s", environment="production", priority="P1")
    result = runner._call_tool_handler(get_recent_system_events, job, {"limit": 5})

    assert result == {"limit_used": 5}


def test_run_investigation_survives_a_tool_call_with_an_unexpected_argument(monkeypatch):
    event_id = _seed_event("runner-unexpected-tool-arg-system")
    job = InvestigationJob(event_id=event_id, escalation_id=999, system="runner-unexpected-tool-arg-system", environment="production", priority="P2")

    responses = [
        # get_incident_event's schema takes no parameters, but the model calls it with
        # one anyway -- must not crash the whole investigation.
        _fake_message([_tool_use("get_incident_event", {"limit": 20})], "tool_use"),
        _submit_response(is_known_pattern=True),
    ]
    calls = []

    def fake_call_model(client, messages):
        calls.append(messages)
        return responses[len(calls) - 1]

    monkeypatch.setattr(runner, "_call_model", fake_call_model)

    runner.run_investigation(job)

    record = _latest_investigation(event_id)
    assert record.status == "completed"


def test_run_investigation_no_tool_use_is_recorded_as_failed(monkeypatch):
    event_id = _seed_event("runner-no-tool-use-system")
    job = InvestigationJob(event_id=event_id, escalation_id=999, system="runner-no-tool-use-system", environment="production", priority="P2")

    def fake_call_model(client, messages):
        return _fake_message([_text("I don't know what to do.")], "end_turn")

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
        return _fake_message([_tool_use("get_incident_event", {})], "tool_use")

    monkeypatch.setattr(runner, "_call_model", fake_call_model)

    runner.run_investigation(job)

    record = _latest_investigation(event_id)
    assert record.status == "failed"
    assert "exceeded 2 turns" in record.error


def _submit_response(is_known_pattern: bool):
    return _fake_message(
        [_tool_use("submit_investigation_result", {
            "hypothesis": "probe hypothesis", "recommended_next_step": "probe next step",
            "confidence": 0.5, "is_known_pattern": is_known_pattern,
        })],
        "tool_use",
    )


def test_unknown_pattern_investigation_chains_to_code_diagnosis(monkeypatch):
    monkeypatch.setattr(repo_config, "resolve_repo", lambda system: ("acme", "widget"))
    monkeypatch.setattr(stripe_config, "resolve_stripe_key_env_var", lambda system: "STRIPE_SECRET_KEY_TEST")
    event_id = _seed_event("runner-chain-unknown-system")
    job = InvestigationJob(event_id=event_id, escalation_id=999, system="runner-chain-unknown-system", environment="production", priority="P2")

    monkeypatch.setattr(runner, "_call_model", lambda client, messages: _submit_response(is_known_pattern=False))

    runner.run_investigation(job)

    parent = _latest_investigation(event_id)
    assert parent.investigation_type == "voice_call_failure"
    # All three follow-ups fire independently for a novel incident: Dev/Debug (repo
    # mapping resolved), Database (no mapping to resolve, always fires), and Finance
    # (Stripe mapping resolved).
    rows = _inbox_rows_for_event(event_id)
    assert len(rows) == 3
    code_rows = [r for r in rows if r.message_type == "code_diagnosis"]
    database_rows = [r for r in rows if r.message_type == "database_diagnosis"]
    finance_rows = [r for r in rows if r.message_type == "finance_diagnosis"]
    assert len(code_rows) == 1
    assert len(database_rows) == 1
    assert len(finance_rows) == 1
    assert code_rows[0].recipient == "dev_debug"
    assert code_rows[0].payload["owner"] == "acme"
    assert code_rows[0].payload["repo"] == "widget"
    assert code_rows[0].payload["parent_investigation_id"] == parent.id
    assert database_rows[0].recipient == "database"
    assert database_rows[0].payload["parent_investigation_id"] == parent.id
    assert finance_rows[0].recipient == "finance"
    assert finance_rows[0].payload["stripe_key_env_var"] == "STRIPE_SECRET_KEY_TEST"
    assert finance_rows[0].payload["parent_investigation_id"] == parent.id


def test_known_pattern_investigation_does_not_chain(monkeypatch):
    monkeypatch.setattr(repo_config, "resolve_repo", lambda system: ("acme", "widget"))
    event_id = _seed_event("runner-chain-known-system")
    job = InvestigationJob(event_id=event_id, escalation_id=999, system="runner-chain-known-system", environment="production", priority="P2")

    monkeypatch.setattr(runner, "_call_model", lambda client, messages: _submit_response(is_known_pattern=True))

    runner.run_investigation(job)

    assert _inbox_rows_for_event(event_id) == []


def test_unknown_pattern_without_repo_mapping_skips_chain_and_audits(monkeypatch):
    monkeypatch.setattr(repo_config, "resolve_repo", lambda system: None)
    monkeypatch.setattr(stripe_config, "resolve_stripe_key_env_var", lambda system: "STRIPE_SECRET_KEY_TEST")
    event_id = _seed_event("runner-chain-no-mapping-system")
    job = InvestigationJob(event_id=event_id, escalation_id=999, system="runner-chain-no-mapping-system", environment="production", priority="P2")

    with session_scope() as session:
        before = len(session.scalars(select(AuditRecord).where(AuditRecord.type == "investigation_chain_skipped_no_repo_mapping", AuditRecord.reference_id == str(event_id))).all())

    monkeypatch.setattr(runner, "_call_model", lambda client, messages: _submit_response(is_known_pattern=False))

    runner.run_investigation(job)

    # Dev/Debug skips (no repo mapping), but the database chain has no mapping to
    # resolve and fires regardless, and the finance chain fires because its own
    # (independent) Stripe mapping resolves fine.
    rows = _inbox_rows_for_event(event_id)
    assert len(rows) == 2
    assert any(r.message_type == "database_diagnosis" for r in rows)
    assert any(r.message_type == "finance_diagnosis" for r in rows)
    with session_scope() as session:
        after = len(session.scalars(select(AuditRecord).where(AuditRecord.type == "investigation_chain_skipped_no_repo_mapping", AuditRecord.reference_id == str(event_id))).all())
    assert after == before + 1


def test_unknown_pattern_without_stripe_mapping_skips_finance_chain_and_audits(monkeypatch):
    monkeypatch.setattr(repo_config, "resolve_repo", lambda system: ("acme", "widget"))
    monkeypatch.setattr(stripe_config, "resolve_stripe_key_env_var", lambda system: None)
    event_id = _seed_event("runner-chain-no-stripe-mapping-system")
    job = InvestigationJob(event_id=event_id, escalation_id=999, system="runner-chain-no-stripe-mapping-system", environment="production", priority="P2")

    with session_scope() as session:
        before = len(session.scalars(select(AuditRecord).where(AuditRecord.type == "investigation_chain_skipped_no_stripe_mapping", AuditRecord.reference_id == str(event_id))).all())

    monkeypatch.setattr(runner, "_call_model", lambda client, messages: _submit_response(is_known_pattern=False))

    runner.run_investigation(job)

    # Finance skips (no Stripe mapping), but Dev/Debug (repo mapping resolved) and
    # Database (no mapping to resolve) still fire -- the finance chain's own failure
    # mode never blocks the others.
    rows = _inbox_rows_for_event(event_id)
    assert len(rows) == 2
    assert any(r.message_type == "code_diagnosis" for r in rows)
    assert any(r.message_type == "database_diagnosis" for r in rows)
    assert not any(r.message_type == "finance_diagnosis" for r in rows)
    with session_scope() as session:
        after = len(session.scalars(select(AuditRecord).where(AuditRecord.type == "investigation_chain_skipped_no_stripe_mapping", AuditRecord.reference_id == str(event_id))).all())
    assert after == before + 1
