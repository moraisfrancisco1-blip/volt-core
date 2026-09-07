from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import customer_agent
from app.db import session_scope
from app.models import AuditRecord, CustomerQueryPatternRecord, CustomerQueryRecord, CustomerResponseDraftRecord


@pytest.fixture(autouse=True)
def _default_provider_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key-not-real")


def _tool_response(tool_name, input_dict):
    return SimpleNamespace(
        content=[{"type": "tool_use", "name": tool_name, "input": input_dict, "id": "toolu_1"}],
        stop_reason="tool_use", input_tokens=50, output_tokens=20,
    )


def _seed_query(**overrides) -> int:
    defaults = dict(source="manual_test", question="Como funciona o carregamento inteligente de EV?", status="new")
    defaults.update(overrides)
    with session_scope() as session:
        query = CustomerQueryRecord(**defaults)
        session.add(query)
        session.flush()
        return query.id


def _get_query(query_id: int) -> CustomerQueryRecord:
    with session_scope() as session:
        row = session.get(CustomerQueryRecord, query_id)
        session.expunge(row)
        return row


def _drafts_for(query_id: int) -> list[CustomerResponseDraftRecord]:
    with session_scope() as session:
        rows = session.scalars(select(CustomerResponseDraftRecord).where(CustomerResponseDraftRecord.query_id == query_id)).all()
        for row in rows:
            session.expunge(row)
        return rows


# --- _keyword_sensitive_reason -- the fail-safe gate before any model is ever called -----

@pytest.mark.parametrize("text,expected_reason_substring", [
    ("Quero reclamar do vosso serviço!", "reclama"),
    ("Peço o reembolso imediato.", "reembolso"),
    ("Quero cancelar a minha subscrição.", "reembolso"),
    ("Isto é inaceitável, estou furioso!!!", "frustra"),
    ("Cheira a queimado perto da bateria, pode ser perigoso?", "segurança"),
    ("I want to complain about this.", "reclama"),
    ("This feels unsafe, there was a shock.", "segurança"),
    ("Ik wil een klacht indienen.", "reclama"),
])
def test_keyword_sensitive_reason_catches_known_signals(text, expected_reason_substring):
    reason = customer_agent._keyword_sensitive_reason(text)
    assert reason is not None
    assert expected_reason_substring in reason


def test_keyword_sensitive_reason_none_for_ordinary_question():
    assert customer_agent._keyword_sensitive_reason("Como funciona o carregamento inteligente de EV?") is None


# --- _triage_new_queries: keyword hit never reaches the model ----------------------------

def test_triage_keyword_hit_escalates_without_calling_model(monkeypatch):
    query_id = _seed_query(question="Quero reclamar, isto é inaceitável!")

    def _forbidden(*a, **k):
        raise AssertionError("keyword-flagged sensitive query must never reach the model")

    monkeypatch.setattr(customer_agent, "_call_model", _forbidden)

    customer_agent._triage_new_queries()

    query = _get_query(query_id)
    assert query.status == "sensitive_escalated"
    assert query.classification == "sensitive"
    assert query.triaged_at is not None
    assert _drafts_for(query_id) == []


def test_triage_simple_question_via_model_marks_simple(monkeypatch):
    query_id = _seed_query(question="Qual é o consumo médio de um carregador EV?")
    monkeypatch.setattr(customer_agent, "_call_model", lambda system, prompt, schema, name: _tool_response(
        customer_agent.SUBMIT_TRIAGE_TOOL_NAME, {"classification": "simple"},
    ))

    customer_agent._triage_new_queries()

    query = _get_query(query_id)
    assert query.status == "simple"
    assert query.classification == "simple"


def test_triage_model_sensitive_classification_escalates(monkeypatch):
    query_id = _seed_query(question="O sistema parece estranho hoje")
    monkeypatch.setattr(customer_agent, "_call_model", lambda system, prompt, schema, name: _tool_response(
        customer_agent.SUBMIT_TRIAGE_TOOL_NAME, {"classification": "sensitive", "sensitive_reason": "tom ambíguo, melhor rever"},
    ))

    customer_agent._triage_new_queries()

    query = _get_query(query_id)
    assert query.status == "sensitive_escalated"
    assert query.sensitive_reason == "tom ambíguo, melhor rever"


def test_triage_unexpected_classification_value_fails_safe_to_sensitive(monkeypatch):
    query_id = _seed_query(question="pergunta qualquer")
    monkeypatch.setattr(customer_agent, "_call_model", lambda system, prompt, schema, name: _tool_response(
        customer_agent.SUBMIT_TRIAGE_TOOL_NAME, {"classification": "unknown_value"},
    ))

    customer_agent._triage_new_queries()

    assert _get_query(query_id).status == "sensitive_escalated"


def test_triage_model_failure_fails_safe_to_sensitive_not_stuck_unreviewed(monkeypatch):
    query_id = _seed_query(question="pergunta qualquer")
    monkeypatch.setattr(customer_agent, "_call_model", lambda system, prompt, schema, name: SimpleNamespace(
        content=[{"type": "text", "text": "uncertain"}], stop_reason="end_turn", input_tokens=10, output_tokens=5,
    ))

    customer_agent._triage_new_queries()

    query = _get_query(query_id)
    assert query.status == "sensitive_escalated"
    assert "rever manualmente" in query.sensitive_reason


def test_triage_model_exception_fails_safe_via_audit_not_silent(monkeypatch):
    query_id = _seed_query(question="pergunta qualquer")

    def _boom(system, prompt, schema, name):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(customer_agent, "_call_model", _boom)

    customer_agent._triage_new_queries()  # must not raise

    with session_scope() as session:
        audit = session.scalar(select(AuditRecord).where(AuditRecord.type == "customer_query_triage_failed", AuditRecord.reference_id == str(query_id)))
        assert audit is not None
    # Left as "new" (not silently marked simple) since the exception aborted before any status write.
    assert _get_query(query_id).status == "new"


def test_triage_one_failure_does_not_abort_the_rest(monkeypatch):
    good_id = _seed_query(question="Como funciona o carregamento?")
    bad_id = _seed_query(question="outra pergunta qualquer")
    calls = []

    def fake_call_model(system, prompt, schema, name):
        calls.append(prompt)
        if str(bad_id) in prompt or "outra pergunta" in prompt:
            raise RuntimeError("simulated model failure")
        return _tool_response(customer_agent.SUBMIT_TRIAGE_TOOL_NAME, {"classification": "simple"})

    monkeypatch.setattr(customer_agent, "_call_model", fake_call_model)

    customer_agent._triage_new_queries()  # must not raise

    assert _get_query(good_id).status == "simple"


# --- _generate_pending_response_drafts ----------------------------------------------------

def test_generate_draft_only_for_simple_queries(monkeypatch):
    simple_id = _seed_query(question="Pergunta simples", status="simple", classification="simple")
    sensitive_id = _seed_query(question="Reclamação", status="sensitive_escalated", classification="sensitive", sensitive_reason="reclamação/queixa")
    monkeypatch.setattr(customer_agent, "_fetch_product_facts", lambda: ("### README.md\nO VoltarisOS suporta carregamento inteligente de EV.", ["README.md"]))
    monkeypatch.setattr(customer_agent, "_call_model", lambda system, prompt, schema, name: _tool_response(
        customer_agent.SUBMIT_RESPONSE_TOOL_NAME, {"subject": "Re: a sua pergunta", "body": "Resposta com factos reais."},
    ))

    customer_agent._generate_pending_response_drafts()

    simple_drafts = _drafts_for(simple_id)
    assert len(simple_drafts) == 1
    assert simple_drafts[0].status == "pending_approval"
    assert _drafts_for(sensitive_id) == []


def test_generate_draft_does_not_duplicate_existing_drafts(monkeypatch):
    query_id = _seed_query(question="Pergunta já respondida", status="simple", classification="simple")

    def _forbidden(*a, **k):
        raise AssertionError("must not generate a second draft for a query that already has one")

    with session_scope() as session:
        session.add(CustomerResponseDraftRecord(query_id=query_id, subject="Existing", body="Existing body", status="pending_approval"))

    monkeypatch.setattr(customer_agent, "_call_model", _forbidden)

    customer_agent._generate_pending_response_drafts()  # must not raise / must not call the model

    assert len(_drafts_for(query_id)) == 1


def test_generate_draft_marks_uncertain_facts_explicitly(monkeypatch):
    query_id = _seed_query(question="Qual o preço exato do plano Pro?", status="simple", classification="simple")
    monkeypatch.setattr(customer_agent, "_fetch_product_facts", lambda: (customer_agent._NO_FACTS_TEXT, []))
    monkeypatch.setattr(customer_agent, "_call_model", lambda system, prompt, schema, name: _tool_response(
        customer_agent.SUBMIT_RESPONSE_TOOL_NAME,
        {"subject": "Re: preço", "body": f"Não tenho a certeza sobre o preço exato -- {customer_agent._UNCERTAIN_MARKER}."},
    ))

    customer_agent._generate_pending_response_drafts()

    draft = _drafts_for(query_id)[0]
    assert customer_agent._UNCERTAIN_MARKER in draft.body


def test_generate_draft_one_failure_does_not_abort_the_rest(monkeypatch):
    good_id = _seed_query(question="pergunta boa", status="simple", classification="simple")
    bad_id = _seed_query(question="pergunta má", status="simple", classification="simple")
    monkeypatch.setattr(customer_agent, "_fetch_product_facts", lambda: ("facts", ["README.md"]))

    def fake_call_model(system, prompt, schema, name):
        if "pergunta má" in prompt:
            raise RuntimeError("simulated failure")
        return _tool_response(customer_agent.SUBMIT_RESPONSE_TOOL_NAME, {"subject": "Re:", "body": "ok"})

    monkeypatch.setattr(customer_agent, "_call_model", fake_call_model)

    customer_agent._generate_pending_response_drafts()  # must not raise

    assert len(_drafts_for(good_id)) == 1
    assert len(_drafts_for(bad_id)) == 0


# --- _detect_repeated_patterns -- literal repeat detection, no invented metric -----------

def test_detect_repeated_patterns_flags_near_identical_questions():
    unique = "Qual e a garantia unica do painel solar zzzpattern123"
    _seed_query(question=unique)
    _seed_query(question=unique.upper() + "???")
    _seed_query(question="Uma pergunta completamente diferente sobre baterias zzzpattern123")

    customer_agent._detect_repeated_patterns()

    with session_scope() as session:
        pattern = session.scalar(select(CustomerQueryPatternRecord).where(CustomerQueryPatternRecord.normalized_question == customer_agent._normalize_question(unique)))
        assert pattern is not None
        assert pattern.occurrence_count == 2


def test_detect_repeated_patterns_ignores_single_occurrences():
    _seed_query(question="Pergunta única sem repetição nenhuma aqui")

    customer_agent._detect_repeated_patterns()

    with session_scope() as session:
        pattern = session.scalar(select(CustomerQueryPatternRecord).where(CustomerQueryPatternRecord.normalized_question == customer_agent._normalize_question("Pergunta única sem repetição nenhuma aqui")))
        assert pattern is None


# --- run_customer_sweep orchestration ------------------------------------------------------

def test_run_customer_sweep_never_raises_on_total_failure(monkeypatch):
    def _boom():
        raise RuntimeError("simulated catastrophic failure")

    monkeypatch.setattr(customer_agent, "_triage_new_queries", _boom)

    customer_agent.run_customer_sweep()  # must not raise

    with session_scope() as session:
        audit = session.scalar(select(AuditRecord).where(AuditRecord.type == "customer_sweep_failed").order_by(AuditRecord.id.desc()))
        assert audit is not None


# --- start_customer_agent -------------------------------------------------------------------

def test_start_customer_agent_does_nothing_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(customer_agent, "_started", False)

    customer_agent.start_customer_agent()

    assert customer_agent._started is False


def test_start_customer_agent_starts_a_thread_when_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr(customer_agent, "_started", False)
    started_threads = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started_threads.append((target, name, daemon))

        def start(self):
            pass

    monkeypatch.setattr(customer_agent.threading, "Thread", _FakeThread)

    customer_agent.start_customer_agent()

    assert customer_agent._started is True
    assert len(started_threads) == 1
    assert started_threads[0][1] == "volt-core-customer"
