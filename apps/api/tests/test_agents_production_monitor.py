from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import production_monitor, railway_tools
from app.agents.railway_tools import ProductionSweepJob
from app.db import session_scope
from app.models import EscalationRecord, EventRecord, MonitoringSweepRecord


@pytest.fixture(autouse=True)
def _default_provider_key(monkeypatch):
    # _call_model is always monkeypatched in this file's run_system_sweep-level tests,
    # so the real client is never used -- but run_system_sweep() still calls
    # llm_client.get_client() first, which would raise LLMConfigError with no provider
    # configured at all. A fake Anthropic key keeps that harmless, matching
    # anthropic.Anthropic()'s old lazy-validation behavior these tests already relied
    # on. The run_sweep()/start_production_monitor() gate tests below delenv this (and
    # the other 2 provider keys) themselves to test the "not configured" path.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key-not-real")


def _tool_use(name, input, id="toolu_1"):
    return {"type": "tool_use", "name": name, "input": input, "id": id}


def _text(text):
    return {"type": "text", "text": text}


def _fake_message(content, stop_reason, input_tokens=55, output_tokens=11):
    return SimpleNamespace(content=content, stop_reason=stop_reason, input_tokens=input_tokens, output_tokens=output_tokens)


def _job(system: str) -> ProductionSweepJob:
    return ProductionSweepJob(system=system, environment="production", project_id="p1", service_id="s1", environment_id="e1")


def _latest_sweep(system: str) -> MonitoringSweepRecord:
    with session_scope() as session:
        row = session.scalar(select(MonitoringSweepRecord).where(MonitoringSweepRecord.system == system).order_by(MonitoringSweepRecord.id.desc()))
        session.expunge(row)
        return row


def _no_network_railway_calls(monkeypatch):
    # No sweep test should ever attempt a real Railway API call -- route the tool
    # handlers' own network seam to a benign canned response instead.
    monkeypatch.setattr(railway_tools, "_railway_request", lambda query, variables: {"data": {"metrics": [], "deployments": {"edges": []}}})


def test_run_system_sweep_finds_nothing_creates_no_event(monkeypatch):
    _no_network_railway_calls(monkeypatch)
    responses = [
        _fake_message([_tool_use("get_service_http_metrics", {})], "tool_use"),
        _fake_message([_tool_use("submit_sweep_result", {"summary": "Nothing concerning."})], "tool_use"),
    ]
    calls = []

    def fake_call_model(client, messages):
        calls.append(messages)
        return responses[len(calls) - 1]

    monkeypatch.setattr(production_monitor, "_call_model", fake_call_model)

    production_monitor.run_system_sweep(_job("prodmon-clean-sweep"))

    assert len(calls) == 2
    sweep = _latest_sweep("prodmon-clean-sweep")
    assert sweep.status == "completed"
    assert sweep.event_action == "none"
    assert sweep.created_event_id is None
    assert sweep.summary == "Nothing concerning."


def test_run_system_sweep_raises_alert_creates_event(monkeypatch):
    _no_network_railway_calls(monkeypatch)
    responses = [
        _fake_message([_tool_use("get_service_http_metrics", {})], "tool_use"),
        _fake_message([_tool_use("raise_monitoring_alert", {
            "severity": "high", "category": "error_rate", "title": "Elevated errors", "message": "5xx rate sustained at 15% over 6h",
        })], "tool_use"),
        _fake_message([_tool_use("submit_sweep_result", {"summary": "Raised an alert for elevated error rate."})], "tool_use"),
    ]
    calls = []

    def fake_call_model(client, messages):
        calls.append(messages)
        return responses[len(calls) - 1]

    monkeypatch.setattr(production_monitor, "_call_model", fake_call_model)

    production_monitor.run_system_sweep(_job("prodmon-alert-sweep"))

    sweep = _latest_sweep("prodmon-alert-sweep")
    assert sweep.status == "completed"
    assert sweep.event_action == "created"
    assert sweep.created_event_id is not None

    with session_scope() as session:
        event = session.get(EventRecord, sweep.created_event_id)
        assert event.event_type == "railway_error_rate"
        assert event.priority == "P2"
        escalation = session.scalar(select(EscalationRecord).where(EscalationRecord.event_id == event.id))
        assert escalation is not None
        assert escalation.action == "call"


def test_run_system_sweep_deduped_alert_is_recorded_as_deduped(monkeypatch):
    _no_network_railway_calls(monkeypatch)
    from app.agents.monitoring_alerts import raise_monitoring_alert
    raise_monitoring_alert(_job("prodmon-already-open"), severity="medium", category="latency", title="Slow", message="already open")

    responses = [
        _fake_message([_tool_use("raise_monitoring_alert", {
            "severity": "medium", "category": "latency", "title": "Still slow", "message": "still elevated",
        })], "tool_use"),
        _fake_message([_tool_use("submit_sweep_result", {"summary": "Already alerted, still ongoing."})], "tool_use"),
    ]
    calls = []

    def fake_call_model(client, messages):
        calls.append(messages)
        return responses[len(calls) - 1]

    monkeypatch.setattr(production_monitor, "_call_model", fake_call_model)

    production_monitor.run_system_sweep(_job("prodmon-already-open"))

    sweep = _latest_sweep("prodmon-already-open")
    assert sweep.event_action == "deduped"


def test_run_system_sweep_no_tool_use_is_recorded_as_failed(monkeypatch):
    monkeypatch.setattr(production_monitor, "_call_model", lambda client, messages: _fake_message([_text("uncertain")], "end_turn"))
    production_monitor.run_system_sweep(_job("prodmon-no-tool-use"))
    sweep = _latest_sweep("prodmon-no-tool-use")
    assert sweep.status == "failed"
    assert "end_turn" in sweep.error


def test_run_system_sweep_model_exception_is_recorded_as_failed_not_raised(monkeypatch):
    def fake_call_model(client, messages):
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr(production_monitor, "_call_model", fake_call_model)
    production_monitor.run_system_sweep(_job("prodmon-exception"))  # must not raise
    sweep = _latest_sweep("prodmon-exception")
    assert sweep.status == "failed"
    assert "simulated API failure" in sweep.error


def test_run_system_sweep_exceeds_max_turns_is_recorded_as_failed(monkeypatch):
    monkeypatch.setattr(production_monitor, "MAX_TURNS", 2)
    monkeypatch.setattr(production_monitor, "_call_model", lambda client, messages: _fake_message([_tool_use("get_recent_deployments", {})], "tool_use"))
    _no_network_railway_calls(monkeypatch)

    production_monitor.run_system_sweep(_job("prodmon-max-turns"))

    sweep = _latest_sweep("prodmon-max-turns")
    assert sweep.status == "failed"
    assert "exceeded 2 turns" in sweep.error


def test_run_sweep_without_credentials_never_calls_model(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("RAILWAY_TOKEN", "fake-token")
    monkeypatch.setenv("VOLT_SYSTEM_RAILWAY", '{"prodmon-gated-system": {"projectId": "p", "serviceId": "s", "environmentId": "e"}}')

    def spy(client, messages):
        raise AssertionError("_call_model must not be called without ANTHROPIC_API_KEY")

    monkeypatch.setattr(production_monitor, "_call_model", spy)

    production_monitor.run_sweep()  # must not raise, must not call the model


def test_run_sweep_skips_systems_without_a_railway_mapping(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setenv("RAILWAY_TOKEN", "fake-token")
    monkeypatch.setenv("VOLT_SYSTEM_RAILWAY", '{"prodmon-unmapped": {"projectId": "", "serviceId": "", "environmentId": ""}}')

    def spy(client, messages):
        raise AssertionError("_call_model must not be called for an unmapped system")

    monkeypatch.setattr(production_monitor, "_call_model", spy)

    production_monitor.run_sweep()  # must not raise


def test_run_sweep_one_system_failure_does_not_abort_the_rest(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setenv("RAILWAY_TOKEN", "fake-token")
    monkeypatch.setenv("VOLT_SYSTEM_RAILWAY", (
        '{"prodmon-multi-a": {"projectId": "p", "serviceId": "s", "environmentId": "e"}, '
        '"prodmon-multi-b": {"projectId": "p", "serviceId": "s", "environmentId": "e"}}'
    ))
    calls = []

    def fake_run_system_sweep(job):
        calls.append(job.system)
        if job.system == "prodmon-multi-a":
            raise RuntimeError("boom")

    monkeypatch.setattr(production_monitor, "run_system_sweep", fake_run_system_sweep)

    production_monitor.run_sweep()  # must not raise despite one system failing

    assert set(calls) == {"prodmon-multi-a", "prodmon-multi-b"}


def test_start_production_monitor_does_nothing_without_both_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("RAILWAY_TOKEN", "fake-token")
    monkeypatch.setattr(production_monitor, "_started", False)

    production_monitor.start_production_monitor()

    assert production_monitor._started is False


def test_start_production_monitor_starts_a_thread_when_both_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setenv("RAILWAY_TOKEN", "fake-token")
    monkeypatch.setattr(production_monitor, "_started", False)
    started_threads = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started_threads.append((target, name, daemon))

        def start(self):
            pass  # deliberately never actually run the loop -- no real thread, no network

    monkeypatch.setattr(production_monitor.threading, "Thread", _FakeThread)

    production_monitor.start_production_monitor()

    assert production_monitor._started is True
    assert len(started_threads) == 1
    assert started_threads[0][1] == "volt-core-production-monitor"
