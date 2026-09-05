from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import deals_agent, stripe_config, stripe_tools
from app.db import session_scope
from app.models import DealProposalRecord, DealRecord, SalesLeadRecord, SalesOutreachDraftRecord


@pytest.fixture(autouse=True)
def _default_provider_key(monkeypatch):
    # _call_model is always monkeypatched in this file's tests, so the real client is
    # never used -- but the module still calls llm_client.get_client() first, which
    # would raise LLMConfigError with no provider configured at all.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key-not-real")


def _tool_response(tool_name, input_dict):
    return SimpleNamespace(
        content=[{"type": "tool_use", "name": tool_name, "input": input_dict, "id": "toolu_1"}],
        stop_reason="tool_use", input_tokens=50, output_tokens=20,
    )


def _seed_lead(**overrides) -> int:
    defaults = dict(lead_type="consumer_inbound", status="qualified", name="Jan de Boer", email="jan@example.com", consent_basis="inbound_signup")
    defaults.update(overrides)
    with session_scope() as session:
        lead = SalesLeadRecord(**defaults)
        session.add(lead)
        session.flush()
        return lead.id


def _seed_deal(lead_id: int, **overrides) -> int:
    defaults = dict(lead_id=lead_id, stage="qualified")
    defaults.update(overrides)
    with session_scope() as session:
        deal = DealRecord(**defaults)
        session.add(deal)
        session.flush()
        return deal.id


def _get_deal(deal_id: int) -> DealRecord:
    with session_scope() as session:
        row = session.get(DealRecord, deal_id)
        session.expunge(row)
        return row


def _proposals_for(deal_id: int) -> list[DealProposalRecord]:
    with session_scope() as session:
        rows = session.scalars(select(DealProposalRecord).where(DealProposalRecord.deal_id == deal_id)).all()
        for row in rows:
            session.expunge(row)
        return rows


def _no_stripe(monkeypatch):
    monkeypatch.setattr(stripe_config, "resolve_stripe_key_env_var", lambda system: None)


# --- _price_catalog_text ------------------------------------------------------------------

def test_price_catalog_text_without_stripe_mapping(monkeypatch):
    _no_stripe(monkeypatch)
    text = deals_agent._price_catalog_text()
    assert "sem chave Stripe configurada" in text


def test_price_catalog_text_with_no_active_prices(monkeypatch):
    monkeypatch.setattr(stripe_config, "resolve_stripe_key_env_var", lambda system: "STRIPE_SECRET_KEY_VOLTARISOS")
    monkeypatch.setattr(stripe_tools, "list_active_prices", lambda key, limit=20: {"prices": []})
    text = deals_agent._price_catalog_text()
    assert "nenhum preço ativo" in text


def test_price_catalog_text_formats_real_prices(monkeypatch):
    monkeypatch.setattr(stripe_config, "resolve_stripe_key_env_var", lambda system: "STRIPE_SECRET_KEY_VOLTARISOS")
    monkeypatch.setattr(stripe_tools, "list_active_prices", lambda key, limit=20: {"prices": [
        {"id": "price_1", "unit_amount": 4900, "currency": "eur", "recurring_interval": "month", "nickname": None, "product_name": "VoltarisOS Home", "product_id": "prod_1"},
    ]})
    text = deals_agent._price_catalog_text()
    assert "VoltarisOS Home" in text
    assert "49.00 EUR/month" in text


# --- _sync_deals_from_sales ----------------------------------------------------------------

def test_sync_creates_deal_for_qualified_consumer_lead():
    lead_id = _seed_lead(lead_type="consumer_inbound", status="qualified", email="sync-consumer@example.com")
    deals_agent._sync_deals_from_sales()
    with session_scope() as session:
        deal = session.scalar(select(DealRecord).where(DealRecord.lead_id == lead_id))
        assert deal is not None
        assert deal.stage == "qualified"


def test_sync_skips_b2b_lead_without_sent_outreach():
    lead_id = _seed_lead(lead_type="b2b_partner", status="qualified", email="no-outreach@example.com", consent_basis="b2b_legitimate_interest")
    deals_agent._sync_deals_from_sales()
    with session_scope() as session:
        assert session.scalar(select(DealRecord).where(DealRecord.lead_id == lead_id)) is None


def test_sync_creates_deal_for_b2b_lead_with_sent_outreach():
    lead_id = _seed_lead(lead_type="b2b_partner", status="qualified", email="contacted-b2b@example.com", consent_basis="b2b_legitimate_interest")
    with session_scope() as session:
        session.add(SalesOutreachDraftRecord(lead_id=lead_id, subject="s", body="b", status="approved_sent"))
    deals_agent._sync_deals_from_sales()
    with session_scope() as session:
        assert session.scalar(select(DealRecord).where(DealRecord.lead_id == lead_id)) is not None


def test_sync_is_idempotent():
    lead_id = _seed_lead(email="idempotent-deal@example.com")
    deals_agent._sync_deals_from_sales()
    deals_agent._sync_deals_from_sales()
    with session_scope() as session:
        count = len(session.scalars(select(DealRecord).where(DealRecord.lead_id == lead_id)).all())
        assert count == 1


# --- _prepare_proposals_for_qualified_deals -------------------------------------------------

def test_prepare_proposal_uses_real_price_and_advances_stage(monkeypatch):
    lead_id = _seed_lead(email="proposal-real-price@example.com")
    deal_id = _seed_deal(lead_id)
    monkeypatch.setattr(deals_agent, "_price_catalog_text", lambda: "VoltarisOS Home: 49.00 EUR/month (price id: price_1)")
    monkeypatch.setattr(deals_agent, "_call_model", lambda system, prompt, schema, name: _tool_response(
        deals_agent.SUBMIT_PROPOSAL_TOOL_NAME,
        {"price_summary": "VoltarisOS Home a 49.00 EUR/mes (price_1)", "body": "Proposta completa..."},
    ))

    deals_agent._prepare_proposals_for_qualified_deals()

    proposals = _proposals_for(deal_id)
    assert len(proposals) == 1
    assert "49.00" in proposals[0].price_summary
    assert proposals[0].status == "pending_approval"
    deal = _get_deal(deal_id)
    assert deal.stage == "proposal_prepared"


def test_prepare_proposal_falls_back_to_confirm_with_francisco_without_stripe(monkeypatch):
    lead_id = _seed_lead(email="proposal-no-price@example.com")
    deal_id = _seed_deal(lead_id)
    _no_stripe(monkeypatch)
    monkeypatch.setattr(deals_agent, "_call_model", lambda system, prompt, schema, name: _tool_response(
        deals_agent.SUBMIT_PROPOSAL_TOOL_NAME,
        {"price_summary": deals_agent._NO_PRICE_TEXT, "body": "Proposta sem preço definido, a confirmar."},
    ))

    deals_agent._prepare_proposals_for_qualified_deals()

    proposals = _proposals_for(deal_id)
    assert proposals[0].price_summary == "confirmar preço com o Francisco"


def test_prepare_proposal_skips_deals_that_already_have_one(monkeypatch):
    lead_id = _seed_lead(email="no-dup-proposal@example.com")
    deal_id = _seed_deal(lead_id)
    with session_scope() as session:
        session.add(DealProposalRecord(deal_id=deal_id, price_summary="x", body="x", status="pending_approval"))

    def _forbidden(*a, **k):
        raise AssertionError("must not generate a second proposal for a deal that already has one")

    monkeypatch.setattr(deals_agent, "_call_model", _forbidden)

    deals_agent._prepare_proposals_for_qualified_deals()  # must not raise

    assert len(_proposals_for(deal_id)) == 1


def test_prepare_proposal_one_failure_does_not_abort_the_rest(monkeypatch):
    good_lead = _seed_lead(email="good-deal@example.com")
    bad_lead = _seed_lead(email="bad-deal@example.com")
    good_deal_id = _seed_deal(good_lead)
    bad_deal_id = _seed_deal(bad_lead)
    monkeypatch.setattr(deals_agent, "_price_catalog_text", lambda: "[nenhum preço ativo encontrado na Stripe]")

    def fake_call_model(system, prompt, schema, name):
        if f"deal_id={bad_deal_id}" in prompt or "bad-deal" in prompt:
            raise RuntimeError("simulated failure")
        return _tool_response(deals_agent.SUBMIT_PROPOSAL_TOOL_NAME, {"price_summary": deals_agent._NO_PRICE_TEXT, "body": "ok"})

    monkeypatch.setattr(deals_agent, "_call_model", fake_call_model)

    deals_agent._prepare_proposals_for_qualified_deals()  # must not raise

    assert _get_deal(good_deal_id).stage == "proposal_prepared"
    assert _get_deal(bad_deal_id).stage == "qualified"  # left untouched


# --- run_close_suggestion -------------------------------------------------------------------

def test_run_close_suggestion_writes_suggestion_never_touches_stage(monkeypatch):
    lead_id = _seed_lead(email="close-suggestion@example.com")
    deal_id = _seed_deal(lead_id, stage="negotiating")
    monkeypatch.setattr(deals_agent, "_call_model", lambda system, prompt, schema, name: _tool_response(
        deals_agent.SUBMIT_CLOSE_SUGGESTION_TOOL_NAME,
        {"suggested_stage": "closed_won", "reason": "Cliente confirmou por email que vai avançar."},
    ))

    deals_agent.run_close_suggestion(deal_id, "cliente confirmou por email")

    deal = _get_deal(deal_id)
    assert deal.suggested_stage == "closed_won"
    assert "confirmou" in deal.suggested_stage_reason
    assert deal.stage == "negotiating"  # unchanged -- only a human confirms a real stage change


def test_run_close_suggestion_model_exception_is_swallowed(monkeypatch):
    lead_id = _seed_lead(email="close-suggestion-fail@example.com")
    deal_id = _seed_deal(lead_id)

    def _boom(system, prompt, schema, name):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(deals_agent, "_call_model", _boom)

    deals_agent.run_close_suggestion(deal_id, "nota qualquer")  # must not raise

    deal = _get_deal(deal_id)
    assert deal.suggested_stage is None


# --- run_deals_sweep / start_deals_agent -----------------------------------------------------

def test_run_deals_sweep_never_raises_on_total_failure(monkeypatch):
    def _boom():
        raise RuntimeError("simulated catastrophic failure")

    monkeypatch.setattr(deals_agent, "_sync_deals_from_sales", _boom)

    deals_agent.run_deals_sweep()  # must not raise


def test_start_deals_agent_does_nothing_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(deals_agent, "_started", False)

    deals_agent.start_deals_agent()

    assert deals_agent._started is False


def test_start_deals_agent_starts_a_thread_when_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr(deals_agent, "_started", False)
    started_threads = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started_threads.append((target, name, daemon))

        def start(self):
            pass  # deliberately never actually run the loop -- no real thread, no network

    monkeypatch.setattr(deals_agent.threading, "Thread", _FakeThread)

    deals_agent.start_deals_agent()

    assert deals_agent._started is True
    assert len(started_threads) == 1
    assert started_threads[0][1] == "volt-core-deals"
