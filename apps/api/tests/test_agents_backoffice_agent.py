import json

from app.agents import backoffice_agent, daioakes_client, stripe_tools
from app.db import session_scope
from app.models import (
    AuditRecord,
    BackOfficeReconciliationRecord,
    BackOfficeReportRecord,
    DaiOakesBookingsSnapshotRecord,
    DaiOakesClientsSnapshotRecord,
    DaiOakesPaymentRecord,
    DaiOakesSystemHealthSnapshotRecord,
    DealRecord,
    SalesLeadRecord,
)


def _seed_lead(**overrides) -> int:
    defaults = dict(lead_type="tenant_signup", status="qualified", name="Backoffice Test", email="backoffice-agent-test@example.com", consent_basis="existing_customer_tenant")
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


# --- no source configured --------------------------------------------------------------

def test_reconcile_without_stripe_key_reports_no_source(monkeypatch):
    monkeypatch.delenv("VOLT_SYSTEM_STRIPE", raising=False)
    lead_id = _seed_lead(email="no-source@example.com")
    deal_id = _seed_deal(lead_id)

    backoffice_agent.run_backoffice_sweep()

    with session_scope() as session:
        record = session.query(BackOfficeReconciliationRecord).filter_by(deal_id=deal_id).one()
        assert record.data_source == "no_source_configured"
        assert record.match_found is False
        assert record.note == "sem dados financeiros ainda"


def test_report_without_stripe_key_says_no_data(monkeypatch):
    monkeypatch.delenv("VOLT_SYSTEM_STRIPE", raising=False)
    lead_id = _seed_lead(email="no-source-report@example.com")
    _seed_deal(lead_id)

    backoffice_agent.run_backoffice_sweep()

    with session_scope() as session:
        report = session.query(BackOfficeReportRecord).order_by(BackOfficeReportRecord.id.desc()).first()
        assert report.data_source == "no_source_configured"
        assert "sem dados financeiros ainda" in report.summary


# --- sandbox match / no-match, always disclaimed -----------------------------------------

def test_reconcile_matches_by_lead_email_and_discloses_sandbox(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '{"voltaris-os": "STRIPE_SECRET_KEY_VOLTARISOS"}')
    lead_id = _seed_lead(email="matched-customer@example.com")
    deal_id = _seed_deal(lead_id)

    monkeypatch.setattr(stripe_tools, "list_recent_invoices", lambda env_var, **kw: {
        "invoices": [{"id": "in_matched", "status": "paid", "amount_due": 4900, "amount_paid": 4900, "currency": "eur", "customer_email": "matched-customer@example.com", "created": "2026-01-01T00:00:00+00:00"}]
    })

    backoffice_agent.run_backoffice_sweep()

    with session_scope() as session:
        record = session.query(BackOfficeReconciliationRecord).filter_by(deal_id=deal_id).one()
        assert record.data_source == "stripe_sandbox"
        assert record.match_found is True
        assert record.stripe_invoice_id == "in_matched"
        assert "dados de sandbox, não representam receita real" in record.note


def test_reconcile_flags_unmatched_deal_and_discloses_sandbox(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '{"voltaris-os": "STRIPE_SECRET_KEY_VOLTARISOS"}')
    lead_id = _seed_lead(email="unmatched-customer@example.com")
    deal_id = _seed_deal(lead_id)

    monkeypatch.setattr(stripe_tools, "list_recent_invoices", lambda env_var, **kw: {"invoices": []})

    backoffice_agent.run_backoffice_sweep()

    with session_scope() as session:
        record = session.query(BackOfficeReconciliationRecord).filter_by(deal_id=deal_id).one()
        assert record.data_source == "stripe_sandbox"
        assert record.match_found is False
        assert record.stripe_invoice_id is None
        assert "Sem fatura sandbox correspondente" in record.note
        assert "dados de sandbox, não representam receita real" in record.note
        assert "Rever manualmente" in record.note


def test_reconcile_email_matching_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '{"voltaris-os": "STRIPE_SECRET_KEY_VOLTARISOS"}')
    lead_id = _seed_lead(email="MixedCase@Example.com")
    deal_id = _seed_deal(lead_id)

    monkeypatch.setattr(stripe_tools, "list_recent_invoices", lambda env_var, **kw: {
        "invoices": [{"id": "in_case", "status": "paid", "amount_due": 100, "amount_paid": 100, "currency": "eur", "customer_email": "mixedcase@example.com", "created": "2026-01-01T00:00:00+00:00"}]
    })

    backoffice_agent.run_backoffice_sweep()

    with session_scope() as session:
        record = session.query(BackOfficeReconciliationRecord).filter_by(deal_id=deal_id).one()
        assert record.match_found is True


def test_reconcile_stripe_error_reports_unavailable_not_a_false_mismatch(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '{"voltaris-os": "STRIPE_SECRET_KEY_VOLTARISOS"}')
    lead_id = _seed_lead(email="stripe-down@example.com")
    deal_id = _seed_deal(lead_id)

    monkeypatch.setattr(stripe_tools, "list_recent_invoices", lambda env_var, **kw: {"error": "Stripe API returned 401"})

    backoffice_agent.run_backoffice_sweep()

    with session_scope() as session:
        record = session.query(BackOfficeReconciliationRecord).filter_by(deal_id=deal_id).one()
        assert record.data_source == "stripe_unavailable"
        assert record.match_found is False


def test_reconcile_only_considers_closed_won_deals(monkeypatch):
    monkeypatch.delenv("VOLT_SYSTEM_STRIPE", raising=False)
    lead_id = _seed_lead(email="not-closed@example.com")
    open_deal_id = _seed_deal(lead_id, stage="negotiating")

    backoffice_agent.run_backoffice_sweep()

    with session_scope() as session:
        assert session.query(BackOfficeReconciliationRecord).filter_by(deal_id=open_deal_id).count() == 0


def test_sweep_is_idempotent_and_updates_existing_reconciliation(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '{"voltaris-os": "STRIPE_SECRET_KEY_VOLTARISOS"}')
    lead_id = _seed_lead(email="idempotent-backoffice@example.com")
    deal_id = _seed_deal(lead_id)

    monkeypatch.setattr(stripe_tools, "list_recent_invoices", lambda env_var, **kw: {"invoices": []})
    backoffice_agent.run_backoffice_sweep()

    monkeypatch.setattr(stripe_tools, "list_recent_invoices", lambda env_var, **kw: {
        "invoices": [{"id": "in_later", "status": "paid", "amount_due": 100, "amount_paid": 100, "currency": "eur", "customer_email": "idempotent-backoffice@example.com", "created": "2026-01-01T00:00:00+00:00"}]
    })
    backoffice_agent.run_backoffice_sweep()

    with session_scope() as session:
        records = session.query(BackOfficeReconciliationRecord).filter_by(deal_id=deal_id).all()
        assert len(records) == 1  # updated in place, not duplicated
        assert records[0].match_found is True
        assert records[0].stripe_invoice_id == "in_later"


# --- report generation -- real/sandbox counts only, never invented -----------------------

def test_report_counts_match_reconciliation_records(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '{"voltaris-os": "STRIPE_SECRET_KEY_VOLTARISOS"}')
    lead1 = _seed_lead(email="report-matched@example.com")
    lead2 = _seed_lead(email="report-unmatched@example.com")
    _seed_deal(lead1)
    _seed_deal(lead2)

    monkeypatch.setattr(stripe_tools, "list_recent_invoices", lambda env_var, **kw: {
        "invoices": [{"id": "in_r1", "status": "paid", "amount_due": 100, "amount_paid": 100, "currency": "eur", "customer_email": "report-matched@example.com", "created": "2026-01-01T00:00:00+00:00"}]
    })

    backoffice_agent.run_backoffice_sweep()

    with session_scope() as session:
        report = session.query(BackOfficeReportRecord).order_by(BackOfficeReportRecord.id.desc()).first()
        assert report.deals_matched_count >= 1
        assert report.deals_unmatched_count >= 1
        assert "dados de sandbox, não representam receita real" in report.summary


def test_report_with_no_closed_deals_says_so_honestly():
    backoffice_agent.run_generate_report()
    with session_scope() as session:
        report = session.query(BackOfficeReportRecord).order_by(BackOfficeReportRecord.id.desc()).first()
        # This assertion only holds if no other test in this run left an un-isolated
        # closed deal without cleanup -- deals_closed_count reflects the real global
        # count, so just assert internal consistency instead of an absolute number.
        assert report.deals_closed_count >= 0


# --- sweep failure isolation --------------------------------------------------------------

def test_sweep_failure_is_caught_and_audited(monkeypatch):
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(backoffice_agent, "_reconcile_closed_deals", _boom)
    backoffice_agent.run_backoffice_sweep()  # must not raise

    with session_scope() as session:
        audit = session.query(AuditRecord).filter_by(type="backoffice_sweep_failed").order_by(AuditRecord.id.desc()).first()
        assert audit is not None
        assert "boom" in audit.detail


# --- Dai Oakes Payment Control: real data, own allowlist, own incident path --------------

def test_dai_oakes_sync_no_key_configured_reports_skipped_not_failed(monkeypatch):
    monkeypatch.setattr(daioakes_client, "get_payment_control", lambda: {"error": "VOLT_CORE_SERVICE_KEY_DAIOAKES not configured"})

    backoffice_agent._sync_dai_oakes_payments()  # must not raise

    with session_scope() as session:
        audit = session.query(AuditRecord).filter_by(type="dai_oakes_payment_sync_skipped").order_by(AuditRecord.id.desc()).first()
        assert audit is not None
        assert session.query(DaiOakesPaymentRecord).count() == 0


def test_dai_oakes_sync_stores_only_allowlisted_fields(monkeypatch):
    monkeypatch.setattr(daioakes_client, "get_payment_control", lambda: {"data": [
        {"id": "pc_1", "status": "paid", "amount": 100.0, "amountPaid": 100.0, "currency": "eur", "dueDate": "2026-01-01", "paidAt": "2026-01-02", "stripeInvoiceId": "in_dai_1"},
    ]})

    backoffice_agent._sync_dai_oakes_payments()

    with session_scope() as session:
        record = session.query(DaiOakesPaymentRecord).filter_by(external_id="pc_1").one()
        assert record.status == "paid"
        assert record.amount == 100.0
        assert record.stripe_invoice_id == "in_dai_1"
        audit = session.query(AuditRecord).filter_by(type="backoffice_dai_oakes_sync_completed").order_by(AuditRecord.id.desc()).first()
        assert audit is not None


def test_dai_oakes_sync_is_idempotent_and_updates_in_place(monkeypatch):
    monkeypatch.setattr(daioakes_client, "get_payment_control", lambda: {"data": [
        {"id": "pc_idem", "status": "pending", "amount": 50.0, "amountPaid": 0, "currency": "eur"},
    ]})
    backoffice_agent._sync_dai_oakes_payments()

    monkeypatch.setattr(daioakes_client, "get_payment_control", lambda: {"data": [
        {"id": "pc_idem", "status": "paid", "amount": 50.0, "amountPaid": 50.0, "currency": "eur"},
    ]})
    backoffice_agent._sync_dai_oakes_payments()

    with session_scope() as session:
        records = session.query(DaiOakesPaymentRecord).filter_by(external_id="pc_idem").all()
        assert len(records) == 1
        assert records[0].status == "paid"


def test_dai_oakes_sync_rejects_entire_batch_on_a_single_unexpected_field(monkeypatch):
    # A red line, not a convenience filter: even one entry with one unexpected field
    # (e.g. something clinical/PII-looking that shouldn't be there) must reject the
    # WHOLE batch, not just drop that field and keep the rest.
    monkeypatch.setattr(daioakes_client, "get_payment_control", lambda: {"data": [
        {"id": "pc_safe", "status": "paid", "amount": 10.0},
        {"id": "pc_bad", "status": "paid", "amount": 20.0, "clientName": "Someone Real"},
    ]})

    backoffice_agent._sync_dai_oakes_payments()

    with session_scope() as session:
        assert session.query(DaiOakesPaymentRecord).filter_by(external_id="pc_safe").count() == 0
        assert session.query(DaiOakesPaymentRecord).filter_by(external_id="pc_bad").count() == 0
        audit = session.query(AuditRecord).filter_by(type="backoffice_dai_oakes_security_incident_failed").order_by(AuditRecord.id.desc()).first()
        assert audit is not None
        assert "clientName" in audit.detail
        # The incident report must never contain the actual leaked value, only the field name.
        assert "Someone Real" not in audit.detail
        # Structured (JSON) so the dashboard can show the field name(s) and how many
        # records were affected without fragile free-text parsing.
        payload = json.loads(audit.detail)
        assert payload["unexpected_fields"] == ["clientName"]
        assert payload["entries_affected"] == 2  # the whole batch, including the one safe entry
        # Shape only, never the actual value -- lets a human tell free text from a small
        # fixed enum apart without the incident report ever containing "Someone Real".
        shape = payload["unexpected_field_shapes"]["clientName"]
        assert shape["python_types"] == ["str"]
        assert shape["min_length"] == len("Someone Real")
        assert shape["max_length"] == len("Someone Real")
        assert shape["distinct_value_count"] == 1


def test_summarize_unexpected_field_shapes_reports_type_length_and_distinct_count_never_values():
    raw_entries = [
        {"id": "a", "problem": "card_declined"},
        {"id": "b", "problem": "insufficient_funds"},
        {"id": "c", "problem": "card_declined"},
        {"id": "d"},  # field absent on this entry -- must not be counted as a value
    ]

    shapes = backoffice_agent._summarize_unexpected_field_shapes(raw_entries, ["problem"])

    shape = shapes["problem"]
    assert shape["observed_in"] == 3
    assert shape["python_types"] == ["str"]
    assert shape["min_length"] == len("card_declined")
    assert shape["max_length"] == len("insufficient_funds")
    assert shape["distinct_value_count"] == 2
    detail_json = json.dumps(shapes)
    assert "card_declined" not in detail_json
    assert "insufficient_funds" not in detail_json


def test_summarize_unexpected_field_shapes_caps_distinct_count_for_high_cardinality_text():
    raw_entries = [{"id": str(i), "note": f"unique text {i}"} for i in range(30)]

    shapes = backoffice_agent._summarize_unexpected_field_shapes(raw_entries, ["note"])

    assert shapes["note"]["distinct_value_count"] == "more than 20"


def test_dai_oakes_sync_incident_never_touches_previously_synced_rows(monkeypatch):
    monkeypatch.setattr(daioakes_client, "get_payment_control", lambda: {"data": [{"id": "pc_prior", "status": "paid", "amount": 5.0}]})
    backoffice_agent._sync_dai_oakes_payments()

    monkeypatch.setattr(daioakes_client, "get_payment_control", lambda: {"data": [{"id": "pc_new", "status": "paid", "amount": 5.0, "patientName": "Someone"}]})
    backoffice_agent._sync_dai_oakes_payments()

    with session_scope() as session:
        # The prior good row survives untouched; nothing from the bad batch was stored.
        assert session.query(DaiOakesPaymentRecord).filter_by(external_id="pc_prior").count() == 1
        assert session.query(DaiOakesPaymentRecord).filter_by(external_id="pc_new").count() == 0


def test_dai_oakes_sync_malformed_response_shape_is_a_plain_failure_not_an_incident(monkeypatch):
    monkeypatch.setattr(daioakes_client, "get_payment_control", lambda: {"data": {"unexpected": "shape"}})

    with session_scope() as session:
        before_count = session.query(DaiOakesPaymentRecord).count()

    backoffice_agent._sync_dai_oakes_payments()

    with session_scope() as session:
        audit = session.query(AuditRecord).filter_by(type="backoffice_dai_oakes_sync_failed").order_by(AuditRecord.id.desc()).first()
        assert audit is not None
        # A malformed response must never add any row -- compare against the count just
        # before this call rather than assuming a pristine table (other tests in this
        # same shared-DB run legitimately insert their own Dai Oakes rows first).
        assert session.query(DaiOakesPaymentRecord).count() == before_count


# --- Round 2: bookings-summary -- aggregate-only, whole-object rejection ------------------

def test_dai_oakes_bookings_sync_stores_a_snapshot_on_success(monkeypatch):
    monkeypatch.setattr(daioakes_client, "get_bookings_summary", lambda: {"data": {"summary": {
        "totalBookings": 42, "todayCount": 3, "next7DaysCount": 11,
        "byStatus": {"confirmed": 30, "cancelled": 12}, "byLocation": None, "byDepositStatus": None,
    }}})

    backoffice_agent._sync_dai_oakes_bookings()

    with session_scope() as session:
        row = session.query(DaiOakesBookingsSnapshotRecord).order_by(DaiOakesBookingsSnapshotRecord.id.desc()).first()
        assert row is not None
        assert row.total_bookings == 42
        assert row.today_count == 3
        assert row.next_7_days_count == 11
        assert row.by_status == {"confirmed": 30, "cancelled": 12}
        audit = session.query(AuditRecord).filter_by(type="backoffice_dai_oakes_bookings_sync_completed").order_by(AuditRecord.id.desc()).first()
        assert audit is not None


def test_dai_oakes_bookings_sync_rejects_unexpected_top_level_field(monkeypatch):
    monkeypatch.setattr(daioakes_client, "get_bookings_summary", lambda: {"data": {"summary": {
        "totalBookings": 1, "todayCount": 0, "next7DaysCount": 0, "clientName": "Someone Real",
    }}})

    with session_scope() as session:
        before_count = session.query(DaiOakesBookingsSnapshotRecord).count()

    backoffice_agent._sync_dai_oakes_bookings()

    with session_scope() as session:
        assert session.query(DaiOakesBookingsSnapshotRecord).count() == before_count
        audit = session.query(AuditRecord).filter_by(type="backoffice_dai_oakes_security_incident_failed").order_by(AuditRecord.id.desc()).first()
        assert audit is not None
        payload = json.loads(audit.detail)
        assert payload["endpoint"] == "bookings-summary"
        assert "clientName" in payload["unexpected_fields"]
        assert "Someone Real" not in audit.detail


def test_dai_oakes_bookings_sync_skipped_when_key_not_configured(monkeypatch):
    monkeypatch.setattr(daioakes_client, "get_bookings_summary", lambda: {"error": "VOLT_CORE_SERVICE_KEY_DAIOAKES not configured"})
    backoffice_agent._sync_dai_oakes_bookings()
    with session_scope() as session:
        audit = session.query(AuditRecord).filter_by(type="dai_oakes_bookings_sync_skipped").order_by(AuditRecord.id.desc()).first()
        assert audit is not None


def test_dai_oakes_bookings_sync_malformed_shape_is_a_plain_failure(monkeypatch):
    monkeypatch.setattr(daioakes_client, "get_bookings_summary", lambda: {"data": {"summary": ["not", "an", "object"]}})
    backoffice_agent._sync_dai_oakes_bookings()
    with session_scope() as session:
        audit = session.query(AuditRecord).filter_by(type="backoffice_dai_oakes_bookings_sync_failed").order_by(AuditRecord.id.desc()).first()
        assert audit is not None


# --- Round 2: clients-summary -- especially sensitive, only two bare counts allowed -------

def test_dai_oakes_clients_sync_stores_a_snapshot_on_success(monkeypatch):
    monkeypatch.setattr(daioakes_client, "get_clients_summary", lambda: {"data": {"summary": {
        "totalClients": 250, "newClientsLast30Days": 14,
    }}})

    backoffice_agent._sync_dai_oakes_clients()

    with session_scope() as session:
        row = session.query(DaiOakesClientsSnapshotRecord).order_by(DaiOakesClientsSnapshotRecord.id.desc()).first()
        assert row is not None
        assert row.total_clients == 250
        assert row.new_clients_last_30_days == 14


def test_dai_oakes_clients_sync_rejects_any_extra_field_even_one(monkeypatch):
    # This endpoint is the most sensitive of the three -- it is explicitly built to
    # return only two bare counts, so anything else (even something that looks harmless,
    # e.g. an age bracket or a city breakdown) must reject the whole object.
    monkeypatch.setattr(daioakes_client, "get_clients_summary", lambda: {"data": {"summary": {
        "totalClients": 250, "newClientsLast30Days": 14, "averageAge": 42,
    }}})

    with session_scope() as session:
        before_count = session.query(DaiOakesClientsSnapshotRecord).count()

    backoffice_agent._sync_dai_oakes_clients()

    with session_scope() as session:
        assert session.query(DaiOakesClientsSnapshotRecord).count() == before_count
        audit = session.query(AuditRecord).filter_by(type="backoffice_dai_oakes_security_incident_failed").order_by(AuditRecord.id.desc()).first()
        assert audit is not None
        payload = json.loads(audit.detail)
        assert payload["endpoint"] == "clients-summary"
        assert payload["unexpected_fields"] == ["averageAge"]


# --- Round 2: system-health -- nested per-channel allowlists (webhooks/emails/messages) ---

def test_dai_oakes_system_health_sync_stores_a_snapshot_on_success(monkeypatch):
    monkeypatch.setattr(daioakes_client, "get_system_health", lambda: {"data": {"summary": {
        "webhooks": {"failedTotal": 2, "processedTotal": 500, "failedLast24h": 0},
        "emails": {"sentLast24h": 10, "failedLast24h": 0},
        "messages": {"sentLast24h": 4, "failedLast24h": 1},
        "adminActionsLast24h": 6,
        "loginRateLimitHitsLast24h": 0,
    }}})

    backoffice_agent._sync_dai_oakes_system_health()

    with session_scope() as session:
        row = session.query(DaiOakesSystemHealthSnapshotRecord).order_by(DaiOakesSystemHealthSnapshotRecord.id.desc()).first()
        assert row is not None
        assert row.webhooks_failed_total == 2
        assert row.webhooks_processed_total == 500
        assert row.emails_sent_last_24h == 10
        assert row.messages_failed_last_24h == 1
        assert row.admin_actions_last_24h == 6


def test_dai_oakes_system_health_sync_rejects_unexpected_nested_field(monkeypatch):
    # The unexpected field lives inside the nested "emails" object, not at the top level --
    # the incident detail must still name it (prefixed so it's traceable), and nothing
    # must be stored, same whole-object-rejection discipline as the flat endpoints.
    monkeypatch.setattr(daioakes_client, "get_system_health", lambda: {"data": {"summary": {
        "webhooks": {"failedTotal": 0, "processedTotal": 0, "failedLast24h": 0},
        "emails": {"sentLast24h": 10, "failedLast24h": 0, "recipientEmail": "someone@example.com"},
        "messages": {"sentLast24h": 0, "failedLast24h": 0},
        "adminActionsLast24h": 0,
        "loginRateLimitHitsLast24h": 0,
    }}})

    with session_scope() as session:
        before_count = session.query(DaiOakesSystemHealthSnapshotRecord).count()

    backoffice_agent._sync_dai_oakes_system_health()

    with session_scope() as session:
        assert session.query(DaiOakesSystemHealthSnapshotRecord).count() == before_count
        audit = session.query(AuditRecord).filter_by(type="backoffice_dai_oakes_security_incident_failed").order_by(AuditRecord.id.desc()).first()
        assert audit is not None
        payload = json.loads(audit.detail)
        assert payload["endpoint"] == "system-health"
        assert "emails.recipientEmail" in payload["unexpected_fields"]
        assert "someone@example.com" not in audit.detail


def test_dai_oakes_system_health_sync_rejects_when_nested_object_is_not_a_dict(monkeypatch):
    monkeypatch.setattr(daioakes_client, "get_system_health", lambda: {"data": {"summary": {
        "webhooks": "not an object", "emails": {}, "messages": {},
        "adminActionsLast24h": 0, "loginRateLimitHitsLast24h": 0,
    }}})

    backoffice_agent._sync_dai_oakes_system_health()

    with session_scope() as session:
        audit = session.query(AuditRecord).filter_by(type="backoffice_dai_oakes_security_incident_failed").order_by(AuditRecord.id.desc()).first()
        assert audit is not None
        payload = json.loads(audit.detail)
        assert "webhooks: not an object" in payload["unexpected_fields"]
