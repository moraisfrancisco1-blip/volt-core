from fastapi.testclient import TestClient

from app.agents import sales_agent, resend_client
from app.db import session_scope
from app.main import app
from app.models import SalesLeadRecord, SalesOutreachDraftRecord


def _auth_headers(monkeypatch, key="ci-secret-key"):
    monkeypatch.setenv("VOLT_BOOTSTRAP_CLIENT", "ci-admin")
    monkeypatch.setenv("VOLT_BOOTSTRAP_KEY", key)
    return {"X-Volt-Key": key}


def _seed_lead(**overrides) -> int:
    defaults = dict(lead_type="b2b_partner", status="qualified", name="Zon Installaties BV", email="router-test@example.com", consent_basis="b2b_legitimate_interest")
    defaults.update(overrides)
    with session_scope() as session:
        lead = SalesLeadRecord(**defaults)
        session.add(lead)
        session.flush()
        return lead.id


def _seed_draft(lead_id: int, **overrides) -> int:
    defaults = dict(lead_id=lead_id, subject="Parceria", body="Corpo do email.", status="pending_approval")
    defaults.update(overrides)
    with session_scope() as session:
        draft = SalesOutreachDraftRecord(**defaults)
        session.add(draft)
        session.flush()
        return draft.id


# --- ingestion -----------------------------------------------------------------------------

def test_ingest_lead_without_scope_is_rejected():
    with TestClient(app) as client:
        response = client.post("/api/sales-leads", json={"name": "Jan de Boer", "email": "jan@example.com"})
        assert response.status_code == 401  # no X-Volt-Key at all


def test_ingest_lead_forces_consumer_inbound_lead_type(monkeypatch):
    headers = _auth_headers(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/api/sales-leads", headers=headers,
            json={"name": "Jan de Boer", "email": "jan@example.com", "source": "demo_request", "context": "Pediu demo via site"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["lead_type"] == "consumer_inbound"
        assert payload["consent_basis"] == "inbound_signup"
        assert payload["status"] == "new"


def test_list_and_get_leads(monkeypatch):
    lead_id = _seed_lead()
    with TestClient(app) as client:
        list_response = client.get("/api/sales-leads?lead_type=b2b_partner")
        assert list_response.status_code == 200
        assert any(item["id"] == lead_id for item in list_response.json())

        get_response = client.get(f"/api/sales-leads/{lead_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == lead_id


def test_get_lead_missing_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/sales-leads/999999")
        assert response.status_code == 404


def test_list_leads_rejects_invalid_status():
    with TestClient(app) as client:
        response = client.get("/api/sales-leads?status=not-a-real-status")
        assert response.status_code == 422


# --- prepare-call / sweep trigger -----------------------------------------------------------

def test_prepare_call_without_credentials_does_not_start_a_thread(monkeypatch):
    lead_id = _seed_lead()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def spy(lead_id):
        raise AssertionError("run_call_prep must not be called without a provider")

    monkeypatch.setattr(sales_agent, "run_call_prep", spy)

    with TestClient(app) as client:
        response = client.post(f"/api/sales-leads/{lead_id}/prepare-call")
        assert response.json()["triggered"] is False


def test_prepare_call_missing_lead_returns_404():
    with TestClient(app) as client:
        response = client.post("/api/sales-leads/999999/prepare-call")
        assert response.status_code == 404


def test_trigger_sales_sweep_without_credentials_does_not_start_a_thread(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def spy():
        raise AssertionError("run_sales_sweep must not be called without a provider")

    monkeypatch.setattr(sales_agent, "run_sales_sweep", spy)

    with TestClient(app) as client:
        response = client.post("/api/sales/run")
        assert response.json()["triggered"] is False


# --- outreach drafts / approve-and-send ------------------------------------------------------

def test_list_and_get_drafts():
    lead_id = _seed_lead(email="draft-list-test@example.com")
    draft_id = _seed_draft(lead_id)
    with TestClient(app) as client:
        list_response = client.get("/api/sales-outreach-drafts?status=pending_approval")
        assert list_response.status_code == 200
        assert any(item["id"] == draft_id for item in list_response.json())

        get_response = client.get(f"/api/sales-outreach-drafts/{draft_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == draft_id


def test_approve_and_send_calls_smtp_exactly_once_and_marks_sent(monkeypatch):
    lead_id = _seed_lead(email="approve-send-test@example.com")
    draft_id = _seed_draft(lead_id, subject="Parceria VoltarisOS", body="Corpo real.")
    calls = []
    monkeypatch.setattr(resend_client, "send_email", lambda to, subject, body: calls.append((to, subject, body)) or True)

    with TestClient(app) as client:
        response = client.post(f"/api/sales-outreach-drafts/{draft_id}/approve-and-send")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "approved_sent"
        assert payload["approved_at"] is not None

    assert calls == [("approve-send-test@example.com", "Parceria VoltarisOS", "Corpo real.")]


def test_approve_and_send_marks_send_failed_when_smtp_fails(monkeypatch):
    lead_id = _seed_lead(email="approve-fail-test@example.com")
    draft_id = _seed_draft(lead_id)
    monkeypatch.setattr(resend_client, "send_email", lambda to, subject, body: False)

    with TestClient(app) as client:
        response = client.post(f"/api/sales-outreach-drafts/{draft_id}/approve-and-send")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "send_failed"
        assert payload["error"] is not None


def test_approve_and_send_is_idempotent_against_double_click(monkeypatch):
    lead_id = _seed_lead(email="double-click-test@example.com")
    draft_id = _seed_draft(lead_id)
    calls = []
    monkeypatch.setattr(resend_client, "send_email", lambda to, subject, body: calls.append(1) or True)

    with TestClient(app) as client:
        first = client.post(f"/api/sales-outreach-drafts/{draft_id}/approve-and-send")
        second = client.post(f"/api/sales-outreach-drafts/{draft_id}/approve-and-send")
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["status"] == "approved_sent"
        assert second.json()["status"] == "approved_sent"

    assert len(calls) == 1  # send_email must only ever be called once for this draft


def test_approve_and_send_missing_draft_returns_404():
    with TestClient(app) as client:
        response = client.post("/api/sales-outreach-drafts/999999/approve-and-send")
        assert response.status_code == 404


def test_list_drafts_rejects_invalid_status():
    with TestClient(app) as client:
        response = client.get("/api/sales-outreach-drafts?status=not-a-real-status")
        assert response.status_code == 422
