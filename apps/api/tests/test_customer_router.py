from fastapi.testclient import TestClient

from app.agents import customer_agent, resend_client
from app.db import session_scope
from app.main import app
from app.models import CustomerQueryPatternRecord, CustomerQueryRecord, CustomerResponseDraftRecord


def _auth_headers(monkeypatch, key="ci-secret-key"):
    monkeypatch.setenv("VOLT_BOOTSTRAP_CLIENT", "ci-admin")
    monkeypatch.setenv("VOLT_BOOTSTRAP_KEY", key)
    return {"X-Volt-Key": key}


def _seed_query(**overrides) -> int:
    defaults = dict(source="manual_test", question="Como funciona o carregamento de EV?", status="new")
    defaults.update(overrides)
    with session_scope() as session:
        query = CustomerQueryRecord(**defaults)
        session.add(query)
        session.flush()
        return query.id


def _seed_draft(query_id: int, **overrides) -> int:
    defaults = dict(query_id=query_id, subject="Re: a sua pergunta", body="Resposta com factos reais.", status="pending_approval")
    defaults.update(overrides)
    with session_scope() as session:
        draft = CustomerResponseDraftRecord(**defaults)
        session.add(draft)
        session.flush()
        return draft.id


# --- ingestion -----------------------------------------------------------------------------

def test_ingest_query_without_scope_is_rejected():
    with TestClient(app) as client:
        response = client.post("/api/customer-queries", json={"question": "Como funciona?"})
        assert response.status_code == 401  # no X-Volt-Key at all


def test_ingest_query_defaults_source_to_manual_test(monkeypatch):
    headers = _auth_headers(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/api/customer-queries", headers=headers,
            json={"customer_name": "Jan de Boer", "customer_email": "Jan@Example.com", "question": "Como funciona o carregamento?"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["source"] == "manual_test"
        assert payload["status"] == "new"
        assert payload["customer_email"] == "jan@example.com"  # normalized


def test_ingest_query_accepts_explicit_source(monkeypatch):
    headers = _auth_headers(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/api/customer-queries", headers=headers,
            json={"question": "pergunta", "source": "explicit_test_case"},
        )
        assert response.json()["source"] == "explicit_test_case"


# --- listing / detail ------------------------------------------------------------------------

def test_list_and_get_query():
    query_id = _seed_query(question="list-and-get test")

    with TestClient(app) as client:
        list_response = client.get("/api/customer-queries")
        assert list_response.status_code == 200
        assert any(item["id"] == query_id for item in list_response.json())

        get_response = client.get(f"/api/customer-queries/{query_id}")
        assert get_response.status_code == 200
        assert get_response.json()["question"] == "list-and-get test"


def test_get_query_missing_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/customer-queries/999999")
        assert response.status_code == 404


def test_list_queries_rejects_invalid_status():
    with TestClient(app) as client:
        response = client.get("/api/customer-queries?status=not-a-real-status")
        assert response.status_code == 422


def test_list_queries_filters_by_status():
    simple_id = _seed_query(question="filtro simples", status="simple", classification="simple")
    sensitive_id = _seed_query(question="filtro sensível", status="sensitive_escalated", classification="sensitive", sensitive_reason="reclamação/queixa")

    with TestClient(app) as client:
        response = client.get("/api/customer-queries?status=sensitive_escalated")
        ids = {item["id"] for item in response.json()}
        assert sensitive_id in ids
        assert simple_id not in ids


# --- sweep trigger ---------------------------------------------------------------------------

def test_trigger_customer_sweep_without_credentials_does_not_start_a_thread(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def spy():
        raise AssertionError("run_customer_sweep must not be called without a provider")

    monkeypatch.setattr(customer_agent, "run_customer_sweep", spy)

    with TestClient(app) as client:
        response = client.post("/api/customer/run")
        assert response.json()["triggered"] is False


# --- drafts / approve-and-send -- the only path that ever sends a response -----------------

def test_list_and_get_draft():
    query_id = _seed_query(question="draft list test", status="simple", classification="simple", customer_email="draft-list@example.com")
    draft_id = _seed_draft(query_id)

    with TestClient(app) as client:
        list_response = client.get("/api/customer-response-drafts?status=pending_approval")
        assert list_response.status_code == 200
        assert any(item["id"] == draft_id for item in list_response.json())

        get_response = client.get(f"/api/customer-response-drafts/{draft_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == draft_id


def test_approve_and_send_calls_resend_once(monkeypatch):
    query_id = _seed_query(question="approve-send test", status="simple", classification="simple", customer_email="approve-send@example.com")
    draft_id = _seed_draft(query_id)
    calls = []
    monkeypatch.setattr(resend_client, "send_email", lambda to, subject, body: calls.append((to, subject, body)) or True)

    with TestClient(app) as client:
        response = client.post(f"/api/customer-response-drafts/{draft_id}/approve-and-send")
        assert response.status_code == 200
        assert response.json()["status"] == "approved_sent"

    assert len(calls) == 1
    assert calls[0][0] == "approve-send@example.com"


def test_approve_and_send_marks_failed_without_customer_email(monkeypatch):
    query_id = _seed_query(question="no email test", status="simple", classification="simple", customer_email=None)
    draft_id = _seed_draft(query_id)

    def _forbidden(to, subject, body):
        raise AssertionError("must not attempt to send without a customer email")

    monkeypatch.setattr(resend_client, "send_email", _forbidden)

    with TestClient(app) as client:
        response = client.post(f"/api/customer-response-drafts/{draft_id}/approve-and-send")
        assert response.json()["status"] == "send_failed"
        assert "email" in response.json()["error"]


def test_approve_and_send_is_idempotent_against_double_click(monkeypatch):
    query_id = _seed_query(question="double click test", status="simple", classification="simple", customer_email="double-click@example.com")
    draft_id = _seed_draft(query_id)
    calls = []
    monkeypatch.setattr(resend_client, "send_email", lambda to, subject, body: calls.append(1) or True)

    with TestClient(app) as client:
        first = client.post(f"/api/customer-response-drafts/{draft_id}/approve-and-send")
        second = client.post(f"/api/customer-response-drafts/{draft_id}/approve-and-send")
        assert first.json()["status"] == "approved_sent"
        assert second.json()["status"] == "approved_sent"

    assert len(calls) == 1


def test_approve_and_send_missing_draft_returns_404():
    with TestClient(app) as client:
        response = client.post("/api/customer-response-drafts/999999/approve-and-send")
        assert response.status_code == 404


def test_list_drafts_rejects_invalid_status():
    with TestClient(app) as client:
        response = client.get("/api/customer-response-drafts?status=not-a-real-status")
        assert response.status_code == 422


# --- patterns ------------------------------------------------------------------------------

def test_list_query_patterns():
    with session_scope() as session:
        session.add(CustomerQueryPatternRecord(normalized_question="pattern router test unique", occurrence_count=3, example_question="Pattern router test unique?"))

    with TestClient(app) as client:
        response = client.get("/api/customer-query-patterns")
        assert response.status_code == 200
        assert any(item["occurrence_count"] == 3 and item["example_question"] == "Pattern router test unique?" for item in response.json())
