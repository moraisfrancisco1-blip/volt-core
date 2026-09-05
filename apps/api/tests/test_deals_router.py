from fastapi.testclient import TestClient

from app.agents import deals_agent, resend_client
from app.db import session_scope
from app.main import app
from app.models import DealProposalRecord, DealRecord, SalesLeadRecord


def _seed_lead(**overrides) -> int:
    defaults = dict(lead_type="consumer_inbound", status="qualified", name="Jan de Boer", email="router-deal-test@example.com", consent_basis="inbound_signup")
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


def _seed_proposal(deal_id: int, **overrides) -> int:
    defaults = dict(deal_id=deal_id, price_summary="49.00 EUR/mes", body="Corpo da proposta.", status="pending_approval")
    defaults.update(overrides)
    with session_scope() as session:
        proposal = DealProposalRecord(**defaults)
        session.add(proposal)
        session.flush()
        return proposal.id


# --- deals listing --------------------------------------------------------------------------

def test_list_and_get_deals():
    lead_id = _seed_lead(email="list-deal@example.com")
    deal_id = _seed_deal(lead_id)
    with TestClient(app) as client:
        list_response = client.get("/api/deals?stage=qualified")
        assert list_response.status_code == 200
        assert any(item["id"] == deal_id for item in list_response.json())

        get_response = client.get(f"/api/deals/{deal_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == deal_id
        assert get_response.json()["stale"] is False


def test_get_deal_missing_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/deals/999999")
        assert response.status_code == 404


def test_list_deals_rejects_invalid_stage():
    with TestClient(app) as client:
        response = client.get("/api/deals?stage=not-a-real-stage")
        assert response.status_code == 422


def test_stale_deal_is_flagged(monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(deals_agent, "STALE_DAYS", 7)
    lead_id = _seed_lead(email="stale-deal@example.com")
    with session_scope() as session:
        deal = DealRecord(lead_id=lead_id, stage="negotiating", stage_changed_at=datetime.now(timezone.utc) - timedelta(days=10))
        session.add(deal)
        session.flush()
        deal_id = deal.id

    with TestClient(app) as client:
        response = client.get(f"/api/deals/{deal_id}")
        assert response.json()["stale"] is True


# --- sweep / suggest-close triggers ----------------------------------------------------------

def test_trigger_deals_sweep_without_credentials_does_not_start_a_thread(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def spy():
        raise AssertionError("run_deals_sweep must not be called without a provider")

    monkeypatch.setattr(deals_agent, "run_deals_sweep", spy)

    with TestClient(app) as client:
        response = client.post("/api/deals/run")
        assert response.json()["triggered"] is False


def test_suggest_close_missing_deal_returns_404():
    with TestClient(app) as client:
        response = client.post("/api/deals/999999/suggest-close", json={"note": "algo"})
        assert response.status_code == 404


def test_suggest_close_without_credentials_does_not_start_a_thread(monkeypatch):
    lead_id = _seed_lead(email="suggest-close-no-creds@example.com")
    deal_id = _seed_deal(lead_id)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def spy(deal_id, note):
        raise AssertionError("run_close_suggestion must not be called without a provider")

    monkeypatch.setattr(deals_agent, "run_close_suggestion", spy)

    with TestClient(app) as client:
        response = client.post(f"/api/deals/{deal_id}/suggest-close", json={"note": "algo"})
        assert response.json()["triggered"] is False


# --- confirm-stage: the only path that ever writes a terminal stage --------------------------

def test_confirm_stage_writes_closed_won_and_clears_suggestion():
    lead_id = _seed_lead(email="confirm-won@example.com")
    with session_scope() as session:
        deal = DealRecord(lead_id=lead_id, stage="negotiating", suggested_stage="closed_won", suggested_stage_reason="cliente confirmou")
        session.add(deal)
        session.flush()
        deal_id = deal.id

    with TestClient(app) as client:
        response = client.post(f"/api/deals/{deal_id}/confirm-stage", json={"stage": "closed_won"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["stage"] == "closed_won"
        assert payload["suggested_stage"] is None
        assert payload["suggested_stage_reason"] is None


def test_confirm_stage_lets_human_override_the_suggestion():
    lead_id = _seed_lead(email="confirm-override@example.com")
    with session_scope() as session:
        deal = DealRecord(lead_id=lead_id, stage="negotiating", suggested_stage="closed_won")
        session.add(deal)
        session.flush()
        deal_id = deal.id

    with TestClient(app) as client:
        response = client.post(f"/api/deals/{deal_id}/confirm-stage", json={"stage": "closed_lost"})
        assert response.json()["stage"] == "closed_lost"


def test_confirm_stage_rejects_non_terminal_stage():
    lead_id = _seed_lead(email="confirm-invalid@example.com")
    deal_id = _seed_deal(lead_id)
    with TestClient(app) as client:
        response = client.post(f"/api/deals/{deal_id}/confirm-stage", json={"stage": "negotiating"})
        assert response.status_code == 422


def test_confirm_stage_missing_deal_returns_404():
    with TestClient(app) as client:
        response = client.post("/api/deals/999999/confirm-stage", json={"stage": "closed_won"})
        assert response.status_code == 404


# --- proposals / approve-and-send -------------------------------------------------------------

def test_list_and_get_proposals():
    lead_id = _seed_lead(email="proposal-list@example.com")
    deal_id = _seed_deal(lead_id)
    proposal_id = _seed_proposal(deal_id)
    with TestClient(app) as client:
        list_response = client.get("/api/deal-proposals?status=pending_approval")
        assert list_response.status_code == 200
        assert any(item["id"] == proposal_id for item in list_response.json())

        get_response = client.get(f"/api/deal-proposals/{proposal_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == proposal_id


def test_approve_and_send_calls_resend_once_and_advances_stage_to_negotiating(monkeypatch):
    lead_id = _seed_lead(email="approve-send-deal@example.com")
    deal_id = _seed_deal(lead_id)
    proposal_id = _seed_proposal(deal_id)
    calls = []
    monkeypatch.setattr(resend_client, "send_email", lambda to, subject, body: calls.append((to, subject, body)) or True)

    with TestClient(app) as client:
        response = client.post(f"/api/deal-proposals/{proposal_id}/approve-and-send")
        assert response.status_code == 200
        assert response.json()["status"] == "approved_sent"

    assert len(calls) == 1
    assert calls[0][0] == "approve-send-deal@example.com"
    with session_scope() as session:
        deal = session.get(DealRecord, deal_id)
        assert deal.stage == "negotiating"


def test_approve_and_send_marks_send_failed_and_does_not_advance_stage(monkeypatch):
    lead_id = _seed_lead(email="approve-fail-deal@example.com")
    deal_id = _seed_deal(lead_id)
    proposal_id = _seed_proposal(deal_id)
    monkeypatch.setattr(resend_client, "send_email", lambda to, subject, body: False)

    with TestClient(app) as client:
        response = client.post(f"/api/deal-proposals/{proposal_id}/approve-and-send")
        assert response.json()["status"] == "send_failed"

    with session_scope() as session:
        deal = session.get(DealRecord, deal_id)
        assert deal.stage == "qualified"  # unchanged -- only a successful send advances the pipeline


def test_approve_and_send_is_idempotent_against_double_click(monkeypatch):
    lead_id = _seed_lead(email="double-click-deal@example.com")
    deal_id = _seed_deal(lead_id)
    proposal_id = _seed_proposal(deal_id)
    calls = []
    monkeypatch.setattr(resend_client, "send_email", lambda to, subject, body: calls.append(1) or True)

    with TestClient(app) as client:
        first = client.post(f"/api/deal-proposals/{proposal_id}/approve-and-send")
        second = client.post(f"/api/deal-proposals/{proposal_id}/approve-and-send")
        assert first.json()["status"] == "approved_sent"
        assert second.json()["status"] == "approved_sent"

    assert len(calls) == 1


def test_approve_and_send_missing_proposal_returns_404():
    with TestClient(app) as client:
        response = client.post("/api/deal-proposals/999999/approve-and-send")
        assert response.status_code == 404


def test_list_proposals_rejects_invalid_status():
    with TestClient(app) as client:
        response = client.get("/api/deal-proposals?status=not-a-real-status")
        assert response.status_code == 422
