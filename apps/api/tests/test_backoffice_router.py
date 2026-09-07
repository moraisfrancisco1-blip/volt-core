from fastapi.testclient import TestClient

from app.db import session_scope
from app.main import app
from app.models import AuditRecord, BackOfficeReconciliationRecord, BackOfficeReportRecord, DaiOakesPaymentRecord, DealRecord, SalesLeadRecord


def _seed_lead(**overrides) -> int:
    defaults = dict(lead_type="tenant_signup", status="qualified", name="Router Test", email="backoffice-router-test@example.com", consent_basis="existing_customer_tenant")
    defaults.update(overrides)
    with session_scope() as session:
        lead = SalesLeadRecord(**defaults)
        session.add(lead)
        session.flush()
        return lead.id


def _seed_deal(lead_id: int, **overrides) -> int:
    defaults = dict(lead_id=lead_id, stage="closed_won")
    defaults.update(overrides)
    with session_scope() as session:
        deal = DealRecord(**defaults)
        session.add(deal)
        session.flush()
        return deal.id


def _seed_reconciliation(deal_id: int, **overrides) -> int:
    defaults = dict(deal_id=deal_id, data_source="no_source_configured", match_found=False, note="sem dados financeiros ainda")
    defaults.update(overrides)
    with session_scope() as session:
        record = BackOfficeReconciliationRecord(**defaults)
        session.add(record)
        session.flush()
        return record.id


def _seed_report(**overrides) -> int:
    defaults = dict(data_source="no_source_configured", deals_closed_count=0, deals_matched_count=0, deals_unmatched_count=0, summary="sem deals fechados")
    defaults.update(overrides)
    with session_scope() as session:
        record = BackOfficeReportRecord(**defaults)
        session.add(record)
        session.flush()
        return record.id


def test_list_and_get_reconciliation():
    lead_id = _seed_lead(email="list-reconciliation@example.com")
    deal_id = _seed_deal(lead_id)
    reconciliation_id = _seed_reconciliation(deal_id)

    with TestClient(app) as client:
        list_response = client.get("/api/backoffice/reconciliations")
        assert list_response.status_code == 200
        assert any(item["id"] == reconciliation_id for item in list_response.json())

        get_response = client.get(f"/api/backoffice/reconciliations/{reconciliation_id}")
        assert get_response.status_code == 200
        assert get_response.json()["deal_id"] == deal_id


def test_get_reconciliation_missing_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/backoffice/reconciliations/999999")
        assert response.status_code == 404


def test_list_reconciliations_unmatched_only_filter():
    lead_id = _seed_lead(email="unmatched-filter@example.com")
    deal_id_matched = _seed_deal(lead_id, stage="closed_won")
    lead_id2 = _seed_lead(email="unmatched-filter-2@example.com")
    deal_id_unmatched = _seed_deal(lead_id2, stage="closed_won")
    _seed_reconciliation(deal_id_matched, match_found=True, stripe_invoice_id="in_1", data_source="stripe_sandbox", note="matched")
    _seed_reconciliation(deal_id_unmatched, match_found=False, note="unmatched")

    with TestClient(app) as client:
        response = client.get("/api/backoffice/reconciliations?unmatched_only=true")
        ids = {item["deal_id"] for item in response.json()}
        assert deal_id_unmatched in ids
        assert deal_id_matched not in ids


def test_list_and_get_report():
    report_id = _seed_report(summary="teste de relatório")

    with TestClient(app) as client:
        list_response = client.get("/api/backoffice/reports")
        assert list_response.status_code == 200
        assert any(item["id"] == report_id for item in list_response.json())

        get_response = client.get(f"/api/backoffice/reports/{report_id}")
        assert get_response.status_code == 200
        assert get_response.json()["summary"] == "teste de relatório"


def test_get_report_missing_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/backoffice/reports/999999")
        assert response.status_code == 404


def test_trigger_backoffice_sweep_always_starts_no_llm_gate(monkeypatch):
    # Unlike Sales/Deals/Marketing, Back Office has no LLM dependency (like Operations)
    # -- the trigger must never be gated on any LLM provider credentials.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(app) as client:
        response = client.post("/api/backoffice/run")
        assert response.status_code == 200
        assert response.json()["triggered"] is True


# --- Dai Oakes Payment Control -- real data, always source-labeled, never mixed in ---------

def _seed_dai_oakes_payment(**overrides) -> int:
    defaults = dict(external_id="pc_router_test", status="paid", amount=10.0, amount_paid=10.0, currency="eur")
    defaults.update(overrides)
    with session_scope() as session:
        record = DaiOakesPaymentRecord(**defaults)
        session.add(record)
        session.flush()
        return record.id


def test_list_dai_oakes_payments_always_labels_source():
    _seed_dai_oakes_payment(external_id="pc_label_test")

    with TestClient(app) as client:
        response = client.get("/api/backoffice/dai-oakes-payments")
        assert response.status_code == 200
        match = next(item for item in response.json() if item["external_id"] == "pc_label_test")
        assert match["source"] == "dai_oakes_real"


def test_payment_control_summary_with_no_data_says_so():
    with session_scope() as session:
        session.query(DaiOakesPaymentRecord).delete()
        session.query(AuditRecord).filter(AuditRecord.type.like("dai_oakes%") | AuditRecord.type.like("backoffice_dai_oakes%")).delete(synchronize_session=False)

    with TestClient(app) as client:
        response = client.get("/api/backoffice/payment-control-summary")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 0
        assert payload["security_incident"] is False


def test_payment_control_summary_counts_paid_vs_pending():
    with session_scope() as session:
        session.query(DaiOakesPaymentRecord).delete()
    _seed_dai_oakes_payment(external_id="pc_summary_paid", status="paid")
    _seed_dai_oakes_payment(external_id="pc_summary_pending", status="pending")

    with TestClient(app) as client:
        response = client.get("/api/backoffice/payment-control-summary")
        payload = response.json()
        assert payload["total"] == 2
        assert payload["paid"] == 1
        assert payload["pending"] == 1
        assert payload["source"] == "dai_oakes_real"


def test_payment_control_summary_flags_security_incident_and_it_takes_priority():
    with session_scope() as session:
        session.query(DaiOakesPaymentRecord).delete()
        session.add(AuditRecord(type="backoffice_dai_oakes_security_incident_failed", detail="unexpected field(s): clientName"))

    with TestClient(app) as client:
        response = client.get("/api/backoffice/payment-control-summary")
        payload = response.json()
        assert payload["security_incident"] is True
        assert "revisão humana" in payload["note"]
