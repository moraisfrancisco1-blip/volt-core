from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import sales_agent
from app.db import session_scope
from app.models import SalesLeadRecord, SalesOutreachDraftRecord


@pytest.fixture(autouse=True)
def _default_provider_key(monkeypatch):
    # _call_model is always monkeypatched in this file's tests, so the real client is
    # never used -- but the module still calls llm_client.get_client() first, which
    # would raise LLMConfigError with no provider configured at all.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key-not-real")


def _tool_response(tool_name, input_dict):
    return SimpleNamespace(
        content=[{"type": "tool_use", "name": tool_name, "input": input_dict, "id": "toolu_1"}],
        stop_reason="tool_use",
        input_tokens=50,
        output_tokens=20,
    )


def _seed_lead(**overrides) -> int:
    defaults = dict(lead_type="consumer_inbound", status="new", name="Jan de Boer", email="jan@example.com", consent_basis="inbound_signup")
    defaults.update(overrides)
    with session_scope() as session:
        lead = SalesLeadRecord(**defaults)
        session.add(lead)
        session.flush()
        return lead.id


def _get_lead(lead_id: int) -> SalesLeadRecord:
    with session_scope() as session:
        row = session.get(SalesLeadRecord, lead_id)
        session.expunge(row)
        return row


def _drafts_for(lead_id: int) -> list[SalesOutreachDraftRecord]:
    with session_scope() as session:
        rows = session.scalars(select(SalesOutreachDraftRecord).where(SalesOutreachDraftRecord.lead_id == lead_id)).all()
        for row in rows:
            session.expunge(row)
        return rows


# --- _b2b_prospects ---------------------------------------------------------------------

def test_b2b_prospects_defaults_to_empty_without_env(monkeypatch):
    monkeypatch.delenv("VOLT_SALES_B2B_PROSPECTS", raising=False)
    assert sales_agent._b2b_prospects() == []


def test_b2b_prospects_reads_valid_json(monkeypatch):
    monkeypatch.setenv("VOLT_SALES_B2B_PROSPECTS", '[{"name": "Zon Installaties BV", "email": "info@zoninstallaties.example"}]')
    prospects = sales_agent._b2b_prospects()
    assert prospects == [{"name": "Zon Installaties BV", "email": "info@zoninstallaties.example"}]


def test_b2b_prospects_falls_back_to_empty_on_malformed_json(monkeypatch):
    monkeypatch.setenv("VOLT_SALES_B2B_PROSPECTS", "not json")
    assert sales_agent._b2b_prospects() == []


def test_b2b_prospects_drops_entries_missing_name_or_email(monkeypatch):
    monkeypatch.setenv("VOLT_SALES_B2B_PROSPECTS", '[{"name": "No Email Co"}, {"email": "no-name@example.com"}, {"name": "Ok Co", "email": "ok@example.com"}]')
    assert sales_agent._b2b_prospects() == [{"name": "Ok Co", "email": "ok@example.com"}]


# --- _sync_b2b_prospects (idempotent) ----------------------------------------------------

def test_sync_b2b_prospects_creates_leads_for_new_prospects(monkeypatch):
    monkeypatch.setenv("VOLT_SALES_B2B_PROSPECTS", '[{"name": "Zon Installaties BV", "email": "sync-test@example.com", "notes": "known installer"}]')

    sales_agent._sync_b2b_prospects()

    with session_scope() as session:
        lead = session.scalar(select(SalesLeadRecord).where(SalesLeadRecord.email == "sync-test@example.com"))
        assert lead is not None
        assert lead.lead_type == "b2b_partner"
        assert lead.status == "new"
        assert lead.consent_basis == "b2b_legitimate_interest"


def test_sync_b2b_prospects_is_idempotent(monkeypatch):
    monkeypatch.setenv("VOLT_SALES_B2B_PROSPECTS", '[{"name": "Zon Installaties BV", "email": "idempotent-test@example.com"}]')

    sales_agent._sync_b2b_prospects()
    sales_agent._sync_b2b_prospects()

    with session_scope() as session:
        count = len(session.scalars(select(SalesLeadRecord).where(SalesLeadRecord.email == "idempotent-test@example.com")).all())
        assert count == 1


# --- _qualify_new_leads -------------------------------------------------------------------

def test_qualify_new_leads_persists_fields_and_marks_qualified(monkeypatch):
    lead_id = _seed_lead(email="qualify-test@example.com")
    monkeypatch.setattr(sales_agent, "_call_model", lambda system, prompt, schema, name: _tool_response(
        sales_agent.SUBMIT_QUALIFICATION_TOOL_NAME,
        {"fit_score": 0.8, "qualification_summary": "Dono de casa com solar, a considerar bateria.", "suggested_next_step": "Agendar demo."},
    ))

    sales_agent._qualify_new_leads()

    lead = _get_lead(lead_id)
    assert lead.status == "qualified"
    assert lead.fit_score == 0.8
    assert lead.qualification_summary == "Dono de casa com solar, a considerar bateria."
    assert lead.suggested_next_step == "Agendar demo."
    assert lead.qualified_at is not None


def test_qualify_new_leads_one_failure_does_not_abort_the_rest(monkeypatch):
    good_id = _seed_lead(email="good-lead@example.com")
    bad_id = _seed_lead(email="bad-lead@example.com")
    calls = []

    def fake_call_model(system, prompt, schema, name):
        calls.append(prompt)
        if "bad-lead" in prompt:
            raise RuntimeError("simulated model failure")
        return _tool_response(sales_agent.SUBMIT_QUALIFICATION_TOOL_NAME, {"fit_score": 0.5, "qualification_summary": "ok", "suggested_next_step": "ok"})

    monkeypatch.setattr(sales_agent, "_call_model", fake_call_model)

    sales_agent._qualify_new_leads()  # must not raise

    assert _get_lead(good_id).status == "qualified"
    assert _get_lead(bad_id).status == "new"  # left untouched, not silently marked qualified


def test_qualify_new_leads_no_tool_use_leaves_lead_new(monkeypatch):
    lead_id = _seed_lead(email="no-tool-use@example.com")
    monkeypatch.setattr(sales_agent, "_call_model", lambda system, prompt, schema, name: SimpleNamespace(
        content=[{"type": "text", "text": "uncertain"}], stop_reason="end_turn", input_tokens=10, output_tokens=5,
    ))

    sales_agent._qualify_new_leads()

    assert _get_lead(lead_id).status == "new"


# --- _generate_pending_outreach_drafts -----------------------------------------------------

def test_generate_outreach_draft_only_for_qualified_b2b_without_existing_draft(monkeypatch):
    b2b_id = _seed_lead(lead_type="b2b_partner", status="qualified", email="b2b-draft-test@example.com", consent_basis="b2b_legitimate_interest", company="Zon BV")
    consumer_id = _seed_lead(lead_type="consumer_inbound", status="qualified", email="consumer-no-draft@example.com")
    monkeypatch.setattr(sales_agent, "_call_model", lambda system, prompt, schema, name: _tool_response(
        sales_agent.SUBMIT_OUTREACH_TOOL_NAME,
        {"subject": "Parceria com o VoltarisOS", "body": "Corpo do email.\n\nSe preferires não receber mais contacto, basta responder a dizer que sim."},
    ))

    sales_agent._generate_pending_outreach_drafts()

    b2b_drafts = _drafts_for(b2b_id)
    assert len(b2b_drafts) == 1
    assert b2b_drafts[0].status == "pending_approval"
    assert "não receber mais contacto" in b2b_drafts[0].body
    assert _drafts_for(consumer_id) == []


def test_generate_outreach_draft_does_not_duplicate_existing_drafts(monkeypatch):
    b2b_id = _seed_lead(lead_type="b2b_partner", status="qualified", email="no-dup-draft@example.com", consent_basis="b2b_legitimate_interest")

    def _forbidden(*a, **k):
        raise AssertionError("must not generate a second draft for a lead that already has one")

    with session_scope() as session:
        session.add(SalesOutreachDraftRecord(lead_id=b2b_id, subject="Existing", body="Existing body", status="pending_approval"))

    monkeypatch.setattr(sales_agent, "_call_model", _forbidden)

    sales_agent._generate_pending_outreach_drafts()  # must not raise / must not call the model

    assert len(_drafts_for(b2b_id)) == 1


# --- run_sales_sweep orchestration ---------------------------------------------------------

def test_run_sales_sweep_never_raises_on_total_failure(monkeypatch):
    def _boom():
        raise RuntimeError("simulated catastrophic failure")

    monkeypatch.setattr(sales_agent, "_sync_b2b_prospects", _boom)

    sales_agent.run_sales_sweep()  # must not raise


# --- run_call_prep ---------------------------------------------------------------------------

def test_run_call_prep_persists_summary_and_sets_scheduled_call_at(monkeypatch):
    lead_id = _seed_lead(status="qualified", qualification_summary="Bom fit.", suggested_next_step="Ligar.", email="call-prep@example.com")
    monkeypatch.setattr(sales_agent, "_call_model", lambda system, prompt, schema, name: _tool_response(
        sales_agent.SUBMIT_CALL_PREP_TOOL_NAME, {"call_prep_summary": "Jan de Boer, já qualificado, cobrir preço e prazo de instalação."},
    ))

    sales_agent.run_call_prep(lead_id)

    lead = _get_lead(lead_id)
    assert lead.call_prep_summary == "Jan de Boer, já qualificado, cobrir preço e prazo de instalação."
    assert lead.scheduled_call_at is not None


def test_run_call_prep_model_exception_is_swallowed_not_raised(monkeypatch):
    lead_id = _seed_lead(email="call-prep-exception@example.com")

    def _boom(system, prompt, schema, name):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(sales_agent, "_call_model", _boom)

    sales_agent.run_call_prep(lead_id)  # must not raise

    assert _get_lead(lead_id).call_prep_summary is None


# --- start_sales_agent ----------------------------------------------------------------------

def test_start_sales_agent_does_nothing_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(sales_agent, "_started", False)

    sales_agent.start_sales_agent()

    assert sales_agent._started is False


def test_start_sales_agent_starts_a_thread_when_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr(sales_agent, "_started", False)
    started_threads = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started_threads.append((target, name, daemon))

        def start(self):
            pass  # deliberately never actually run the loop -- no real thread, no network

    monkeypatch.setattr(sales_agent.threading, "Thread", _FakeThread)

    sales_agent.start_sales_agent()

    assert sales_agent._started is True
    assert len(started_threads) == 1
    assert started_threads[0][1] == "volt-core-sales"
