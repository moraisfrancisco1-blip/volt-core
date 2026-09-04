from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import code_runner, sandbox
from app.agents.github_tools import CodeDiagnosisJob
from app.db import session_scope
from app.models import AgentInvestigationRecord, EventRecord


@pytest.fixture(autouse=True)
def _default_provider_key(monkeypatch):
    # _call_model is always monkeypatched in this file's tests, so the real client is
    # never used -- but run_code_diagnosis() still calls llm_client.get_client() first,
    # which would raise LLMConfigError with no provider configured at all. A fake
    # Anthropic key keeps that harmless, matching anthropic.Anthropic()'s old
    # lazy-validation behavior these tests already relied on.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key-not-real")


def _tool_use(name, input, id="toolu_1"):
    return {"type": "tool_use", "name": name, "input": input, "id": id}


def _text(text):
    return {"type": "text", "text": text}


def _fake_message(content, stop_reason, input_tokens=333, output_tokens=44):
    return SimpleNamespace(content=content, stop_reason=stop_reason, input_tokens=input_tokens, output_tokens=output_tokens)


def test_call_tool_handler_drops_arguments_the_handler_does_not_accept():
    def list_repo_files(job):
        return {"job_event_id": job.event_id}

    job = CodeDiagnosisJob(event_id=1, escalation_id=2, system="s", environment="production", priority="P1", owner="acme", repo="widget", parent_investigation_id=1)
    result = code_runner._call_tool_handler(list_repo_files, job, {"limit": 20})

    assert result == {"job_event_id": 1}


def _seed_event_and_parent(system_id: str) -> tuple[int, int]:
    with session_scope() as session:
        event = EventRecord(
            system=system_id, system_id=system_id, system_name=system_id, environment="production",
            level="HIGH", severity="high", priority="P2", recommended_action="call",
            message="Code runner probe", status="active",
        )
        session.add(event)
        session.flush()
        parent = AgentInvestigationRecord(
            event_id=event.id, escalation_id=999, investigation_type="voice_call_failure",
            system=system_id, environment="production", priority="P2", status="completed",
            hypothesis="Unclear from VOLT CORE data alone", is_known_pattern=False,
        )
        session.add(parent)
        session.flush()
        return event.id, parent.id


def _latest_code_diagnosis(event_id: int) -> AgentInvestigationRecord:
    with session_scope() as session:
        row = session.scalar(
            select(AgentInvestigationRecord)
            .where(AgentInvestigationRecord.event_id == event_id, AgentInvestigationRecord.investigation_type == "code_diagnosis")
            .order_by(AgentInvestigationRecord.id.desc())
        )
        session.expunge(row)
        return row


def _job(event_id: int, parent_id: int, system: str) -> CodeDiagnosisJob:
    return CodeDiagnosisJob(event_id=event_id, escalation_id=999, system=system, environment="production", priority="P2", owner="acme", repo="widget", parent_investigation_id=parent_id)


def test_run_code_diagnosis_success_after_one_tool_call(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    event_id, parent_id = _seed_event_and_parent("coderunner-success-system")
    job = _job(event_id, parent_id, "coderunner-success-system")

    responses = [
        _fake_message([_tool_use("get_prior_investigation", {})], "tool_use"),
        _fake_message(
            [_tool_use("submit_investigation_result", {
                "hypothesis": "A recent change to the retry backoff looks like the cause.",
                "recommended_next_step": "Review commit abc123 in backend/retry.py.",
                "confidence": 0.7,
                "is_known_pattern": False,
            })],
            "tool_use",
        ),
    ]
    calls = []

    def fake_call_model(client, messages):
        calls.append(messages)
        return responses[len(calls) - 1]

    monkeypatch.setattr(code_runner, "_call_model", fake_call_model)

    code_runner.run_code_diagnosis(job)

    assert len(calls) == 2
    record = _latest_code_diagnosis(event_id)
    assert record.status == "completed"
    assert record.investigation_type == "code_diagnosis"
    assert record.parent_investigation_id == parent_id
    assert record.repo_owner == "acme"
    assert record.repo_name == "widget"
    assert record.hypothesis == "A recent change to the retry backoff looks like the cause."
    assert record.turns_used == 2
    assert record.input_tokens == 333
    assert record.output_tokens == 44


def test_run_code_diagnosis_with_proposed_files_runs_the_sandbox(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    event_id, parent_id = _seed_event_and_parent("coderunner-sandbox-system")
    job = _job(event_id, parent_id, "coderunner-sandbox-system")
    proposed_files = [{"file_path": "app/models.py", "new_content": "x = 1\n"}]

    monkeypatch.setattr(
        code_runner, "_call_model",
        lambda client, messages: _fake_message(
            [_tool_use("submit_investigation_result", {
                "hypothesis": "Off-by-one in the retry counter.",
                "recommended_next_step": "Apply the attached fix.",
                "confidence": 0.8,
                "is_known_pattern": False,
                "proposed_files": proposed_files,
            })],
            "tool_use",
        ),
    )
    sandbox_calls = []

    def fake_run_sandboxed_fix(owner, repo, files, timeout_seconds):
        sandbox_calls.append((owner, repo, files, timeout_seconds))
        return {"status": "passed", "output": "1 passed", "install_output": None, "network_isolated": True, "ran_at": "2026-09-04T00:00:00+00:00"}

    monkeypatch.setattr(sandbox, "run_sandboxed_fix", fake_run_sandboxed_fix)

    code_runner.run_code_diagnosis(job)

    assert len(sandbox_calls) == 1
    assert sandbox_calls[0][0] == "acme"
    assert sandbox_calls[0][1] == "widget"
    assert sandbox_calls[0][2] == proposed_files

    record = _latest_code_diagnosis(event_id)
    assert record.status == "completed"
    assert record.proposed_files == proposed_files
    assert record.sandbox_status == "passed"
    assert record.sandbox_output == "1 passed"
    assert record.sandbox_network_isolated is True
    assert record.sandbox_ran_at is not None


def test_run_code_diagnosis_without_proposed_files_never_runs_the_sandbox(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    event_id, parent_id = _seed_event_and_parent("coderunner-no-sandbox-system")
    job = _job(event_id, parent_id, "coderunner-no-sandbox-system")

    monkeypatch.setattr(
        code_runner, "_call_model",
        lambda client, messages: _fake_message(
            [_tool_use("submit_investigation_result", {
                "hypothesis": "Diagnosis only, no fix proposed.",
                "recommended_next_step": "Review manually.",
                "confidence": 0.5,
                "is_known_pattern": False,
            })],
            "tool_use",
        ),
    )

    def _forbidden(*a, **k):
        raise AssertionError("run_sandboxed_fix must not be called without proposed_files")

    monkeypatch.setattr(sandbox, "run_sandboxed_fix", _forbidden)

    code_runner.run_code_diagnosis(job)

    record = _latest_code_diagnosis(event_id)
    assert record.status == "completed"
    assert record.proposed_files is None
    assert record.sandbox_status == "not_attempted"
    assert record.sandbox_output is None
    assert record.sandbox_network_isolated is None
    assert record.sandbox_ran_at is None


def test_run_code_diagnosis_without_github_token_fails_fast_without_calling_model(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    event_id, parent_id = _seed_event_and_parent("coderunner-no-token-system")
    job = _job(event_id, parent_id, "coderunner-no-token-system")

    def spy(client, messages):
        raise AssertionError("_call_model must not be called without GITHUB_TOKEN")

    monkeypatch.setattr(code_runner, "_call_model", spy)

    code_runner.run_code_diagnosis(job)

    record = _latest_code_diagnosis(event_id)
    assert record.status == "failed"
    assert "GITHUB_TOKEN not configured" in record.error


def test_run_code_diagnosis_no_tool_use_is_recorded_as_failed(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    event_id, parent_id = _seed_event_and_parent("coderunner-no-tool-use-system")
    job = _job(event_id, parent_id, "coderunner-no-tool-use-system")

    monkeypatch.setattr(code_runner, "_call_model", lambda client, messages: _fake_message([_text("Not sure.")], "end_turn"))

    code_runner.run_code_diagnosis(job)

    record = _latest_code_diagnosis(event_id)
    assert record.status == "failed"
    assert "end_turn" in record.error


def test_run_code_diagnosis_model_exception_is_recorded_as_failed_not_raised(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    event_id, parent_id = _seed_event_and_parent("coderunner-exception-system")
    job = _job(event_id, parent_id, "coderunner-exception-system")

    def fake_call_model(client, messages):
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr(code_runner, "_call_model", fake_call_model)

    code_runner.run_code_diagnosis(job)  # must not raise

    record = _latest_code_diagnosis(event_id)
    assert record.status == "failed"
    assert "simulated API failure" in record.error


def test_run_code_diagnosis_exceeds_max_turns_is_recorded_as_failed(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    event_id, parent_id = _seed_event_and_parent("coderunner-max-turns-system")
    job = _job(event_id, parent_id, "coderunner-max-turns-system")
    monkeypatch.setattr(code_runner, "MAX_TURNS", 2)

    monkeypatch.setattr(code_runner, "_call_model", lambda client, messages: _fake_message([_tool_use("get_prior_investigation", {})], "tool_use"))

    code_runner.run_code_diagnosis(job)

    record = _latest_code_diagnosis(event_id)
    assert record.status == "failed"
    assert "exceeded 2 turns" in record.error
