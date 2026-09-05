from app.agents import stripe_tools
from app.agents.stripe_tools import FinanceJob


def _job() -> FinanceJob:
    return FinanceJob(
        event_id=1, escalation_id=2, system="daiane-oakes-admin", environment="production",
        priority="P2", stripe_key_env_var="STRIPE_SECRET_KEY_DAIANE_OAKES", parent_investigation_id=9,
    )


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_list_recent_charges_success(monkeypatch):
    payload = {"data": [{
        "id": "ch_1", "status": "failed", "amount": 1000, "amount_captured": 0, "amount_refunded": 0,
        "currency": "eur", "created": 1700000000, "captured": False, "paid": False, "refunded": False,
        "disputed": False, "failure_code": "card_declined", "failure_message": "Your card was declined.",
        "outcome": {"type": "issuer_declined", "network_status": "declined_by_network"},
        "customer": "cus_abc",
    }]}
    monkeypatch.setattr(stripe_tools, "_stripe_request", lambda method, path, **kwargs: FakeResponse(200, payload))

    result = stripe_tools.list_recent_charges(_job())

    assert result["charges"][0]["id"] == "ch_1"
    assert result["charges"][0]["failure_code"] == "card_declined"
    assert result["charges"][0]["customer"] == "cus_abc"


def test_list_recent_charges_clamps_limit(monkeypatch):
    seen = {}

    def fake(method, path, **kwargs):
        seen.update(kwargs.get("params") or {})
        return FakeResponse(200, {"data": []})

    monkeypatch.setattr(stripe_tools, "_stripe_request", fake)
    stripe_tools.list_recent_charges(_job(), limit=500)
    assert seen["limit"] == 100
    stripe_tools.list_recent_charges(_job(), limit=-5)
    assert seen["limit"] == 1


def test_list_recent_charges_network_failure(monkeypatch):
    monkeypatch.setattr(stripe_tools, "_stripe_request", lambda method, path, **kwargs: None)
    result = stripe_tools.list_recent_charges(_job())
    assert "network/transport error" in result["error"]


def test_list_recent_charges_http_error(monkeypatch):
    monkeypatch.setattr(stripe_tools, "_stripe_request", lambda method, path, **kwargs: FakeResponse(401, {}))
    result = stripe_tools.list_recent_charges(_job())
    assert result == {"error": "Stripe API returned 401"}


def test_list_open_disputes_success(monkeypatch):
    payload = {"data": [{
        "id": "dp_1", "charge": "ch_1", "amount": 1000, "currency": "eur", "status": "needs_response",
        "reason": "fraudulent", "created": 1700000000, "is_charge_refundable": True,
        "evidence_details": {"due_by": 1700100000, "has_evidence": False, "past_due": False, "submission_count": 0},
    }]}
    monkeypatch.setattr(stripe_tools, "_stripe_request", lambda method, path, **kwargs: FakeResponse(200, payload))

    result = stripe_tools.list_open_disputes(_job())

    assert result["disputes"][0]["id"] == "dp_1"
    assert result["disputes"][0]["reason"] == "fraudulent"


def test_get_account_balance_success(monkeypatch):
    payload = {
        "available": [{"amount": 5000, "currency": "eur", "source_types": {"card": 5000}}],
        "pending": [{"amount": 200, "currency": "eur", "source_types": {"card": 200}}],
    }
    monkeypatch.setattr(stripe_tools, "_stripe_request", lambda method, path, **kwargs: FakeResponse(200, payload))

    result = stripe_tools.get_account_balance(_job())

    assert result["available"] == [{"amount": 5000, "currency": "eur", "source_types": {"card": 5000}}]
    assert result["pending"] == [{"amount": 200, "currency": "eur", "source_types": {"card": 200}}]


def test_list_recent_payouts_success(monkeypatch):
    payload = {"data": [{
        "id": "po_1", "amount": 3000, "currency": "eur", "status": "paid", "arrival_date": 1700000000,
        "created": 1699000000, "type": "bank_account", "method": "standard", "automatic": True,
        "failure_code": None, "failure_message": None, "destination": "ba_1",
    }]}
    monkeypatch.setattr(stripe_tools, "_stripe_request", lambda method, path, **kwargs: FakeResponse(200, payload))

    result = stripe_tools.list_recent_payouts(_job())

    assert result["payouts"][0]["id"] == "po_1"
    assert result["payouts"][0]["status"] == "paid"


def test_list_subscriptions_success_and_status_param(monkeypatch):
    seen = {}

    def fake(method, path, **kwargs):
        seen.update(kwargs.get("params") or {})
        return FakeResponse(200, {"data": [{
            "id": "sub_1", "status": "canceled", "customer": "cus_abc", "created": 1699000000,
            "current_period_start": 1699000000, "current_period_end": 1701600000,
            "cancel_at_period_end": False, "canceled_at": 1700500000,
            "cancellation_details": {"reason": "cancellation_requested", "feedback": "too_expensive", "comment": "sensitive customer text"},
            "items": {"data": [{"price": {"id": "price_1", "nickname": "Pro Monthly"}, "quantity": 1}]},
        }]})

    monkeypatch.setattr(stripe_tools, "_stripe_request", fake)

    result = stripe_tools.list_subscriptions(_job(), status="canceled")

    assert seen["status"] == "canceled"
    sub = result["subscriptions"][0]
    assert sub["id"] == "sub_1"
    assert sub["cancellation_reason"] == "cancellation_requested"
    assert sub["items"] == [{"price": "price_1", "quantity": 1}]
    assert "comment" not in str(sub)
    assert "sensitive customer text" not in str(result)
    assert "nickname" not in str(sub)


def test_get_prior_investigation_reads_from_db():
    from app.db import session_scope
    from app.models import AgentInvestigationRecord

    with session_scope() as session:
        record = AgentInvestigationRecord(
            event_id=1, escalation_id=2, investigation_type="voice_call_failure",
            system="daiane-oakes-admin", environment="production", priority="P2", status="completed",
            hypothesis="probe hypothesis", is_known_pattern=False,
        )
        session.add(record)
        session.flush()
        parent_id = record.id

    job = FinanceJob(event_id=1, escalation_id=2, system="daiane-oakes-admin", environment="production", priority="P2", stripe_key_env_var="STRIPE_SECRET_KEY_DAIANE_OAKES", parent_investigation_id=parent_id)
    result = stripe_tools.get_prior_investigation(job)

    assert result["hypothesis"] == "probe hypothesis"


def test_get_prior_investigation_missing():
    job = FinanceJob(event_id=1, escalation_id=2, system="daiane-oakes-admin", environment="production", priority="P2", stripe_key_env_var="STRIPE_SECRET_KEY_DAIANE_OAKES", parent_investigation_id=999999)
    result = stripe_tools.get_prior_investigation(job)
    assert result == {"error": "prior investigation not found"}


# --- Central regression test: no excluded (PII / free-text) field ever leaks --------

def test_list_active_prices_success(monkeypatch):
    payload = {"data": [{
        "id": "price_1", "unit_amount": 4900, "currency": "eur",
        "recurring": {"interval": "month"}, "nickname": "Plano Base",
        "product": {"id": "prod_1", "name": "VoltarisOS Home"},
    }]}
    monkeypatch.setattr(stripe_tools, "_stripe_request", lambda method, path, **kwargs: FakeResponse(200, payload))

    result = stripe_tools.list_active_prices("STRIPE_SECRET_KEY_VOLTARISOS")

    assert result["prices"][0]["id"] == "price_1"
    assert result["prices"][0]["unit_amount"] == 4900
    assert result["prices"][0]["recurring_interval"] == "month"
    assert result["prices"][0]["product_name"] == "VoltarisOS Home"
    assert result["prices"][0]["product_id"] == "prod_1"


def test_list_active_prices_handles_unexpanded_product_id(monkeypatch):
    payload = {"data": [{"id": "price_2", "unit_amount": 1000, "currency": "eur", "product": "prod_2"}]}
    monkeypatch.setattr(stripe_tools, "_stripe_request", lambda method, path, **kwargs: FakeResponse(200, payload))

    result = stripe_tools.list_active_prices("STRIPE_SECRET_KEY_VOLTARISOS")

    assert result["prices"][0]["product_id"] == "prod_2"
    assert result["prices"][0]["product_name"] is None


def test_list_active_prices_network_failure(monkeypatch):
    monkeypatch.setattr(stripe_tools, "_stripe_request", lambda method, path, **kwargs: None)
    result = stripe_tools.list_active_prices("STRIPE_SECRET_KEY_VOLTARISOS")
    assert "network/transport error" in result["error"]


def test_list_active_prices_http_error(monkeypatch):
    monkeypatch.setattr(stripe_tools, "_stripe_request", lambda method, path, **kwargs: FakeResponse(401, {}))
    result = stripe_tools.list_active_prices("STRIPE_SECRET_KEY_VOLTARISOS")
    assert result == {"error": "Stripe API returned 401"}


_POISONED_CHARGE = {
    "id": "ch_poison", "status": "failed", "amount": 100, "currency": "eur", "created": 1700000000,
    "description": "MARKER_DESCRIPTION_TEXT",
    "receipt_email": "MARKER_RECEIPT_EMAIL@example.com",
    "receipt_url": "https://MARKER_RECEIPT_URL.example.com",
    "metadata": {"note": "MARKER_METADATA_TEXT"},
    "billing_details": {"name": "MARKER_BILLING_NAME", "email": "MARKER_BILLING_EMAIL@example.com"},
    "payment_method_details": {"card": {"brand": "visa", "last4": "MARKER_LAST4"}},
    "outcome": {"type": "issuer_declined", "seller_message": "MARKER_SELLER_MESSAGE"},
}

_POISONED_DISPUTE = {
    "id": "dp_poison", "charge": "ch_poison", "amount": 100, "currency": "eur", "status": "needs_response",
    "reason": "fraudulent", "created": 1700000000,
    "evidence_details": {"due_by": 1700100000},
    "evidence": {
        "customer_communication": "MARKER_CUSTOMER_COMMUNICATION",
        "customer_email_address": "MARKER_CUSTOMER_EMAIL@example.com",
        "customer_name": "MARKER_CUSTOMER_NAME",
        "customer_purchase_ip": "MARKER_CUSTOMER_IP",
        "billing_address": "MARKER_BILLING_ADDRESS",
        "shipping_address": "MARKER_SHIPPING_ADDRESS",
    },
    "metadata": {"note": "MARKER_DISPUTE_METADATA"},
}

_POISONED_PAYOUT = {
    "id": "po_poison", "amount": 100, "currency": "eur", "status": "paid", "arrival_date": 1700000000,
    "created": 1699000000, "statement_descriptor": "MARKER_STATEMENT_DESCRIPTOR",
    "metadata": {"note": "MARKER_PAYOUT_METADATA"},
}

_POISONED_SUBSCRIPTION = {
    "id": "sub_poison", "status": "canceled", "customer": "cus_poison", "created": 1699000000,
    "cancellation_details": {"reason": "cancellation_requested", "feedback": "too_expensive", "comment": "MARKER_CANCELLATION_COMMENT"},
    "items": {"data": [{"price": {"id": "price_poison", "nickname": "MARKER_PRICE_NICKNAME"}, "quantity": 1}]},
    "default_payment_method": {"card": {"last4": "MARKER_DEFAULT_PM_LAST4"}},
    "metadata": {"note": "MARKER_SUB_METADATA"},
}

_POISONED_PRICE = {
    "id": "price_poison", "unit_amount": 100, "currency": "eur",
    "metadata": {"note": "MARKER_PRICE_METADATA"},
    "product": {"id": "prod_poison", "name": "Plan", "metadata": {"note": "MARKER_PRODUCT_METADATA"}},
}

_MARKERS = [
    "MARKER_DESCRIPTION_TEXT", "MARKER_RECEIPT_EMAIL", "MARKER_RECEIPT_URL", "MARKER_METADATA_TEXT",
    "MARKER_BILLING_NAME", "MARKER_BILLING_EMAIL", "MARKER_LAST4", "MARKER_SELLER_MESSAGE",
    "MARKER_CUSTOMER_COMMUNICATION", "MARKER_CUSTOMER_EMAIL", "MARKER_CUSTOMER_NAME", "MARKER_CUSTOMER_IP",
    "MARKER_BILLING_ADDRESS", "MARKER_SHIPPING_ADDRESS", "MARKER_DISPUTE_METADATA",
    "MARKER_STATEMENT_DESCRIPTOR", "MARKER_PAYOUT_METADATA", "MARKER_CANCELLATION_COMMENT",
    "MARKER_PRICE_NICKNAME", "MARKER_DEFAULT_PM_LAST4", "MARKER_SUB_METADATA",
    "MARKER_PRICE_METADATA", "MARKER_PRODUCT_METADATA",
]


def test_no_excluded_field_ever_leaks_into_any_tool_result(monkeypatch):
    def fake(method, path, **kwargs):
        payload_by_path = {
            "/charges": {"data": [_POISONED_CHARGE]},
            "/disputes": {"data": [_POISONED_DISPUTE]},
            "/payouts": {"data": [_POISONED_PAYOUT]},
            "/subscriptions": {"data": [_POISONED_SUBSCRIPTION]},
            "/prices": {"data": [_POISONED_PRICE]},
        }
        return FakeResponse(200, payload_by_path[path])

    monkeypatch.setattr(stripe_tools, "_stripe_request", fake)

    results = [
        stripe_tools.list_recent_charges(_job()),
        stripe_tools.list_open_disputes(_job()),
        stripe_tools.list_recent_payouts(_job()),
        stripe_tools.list_subscriptions(_job()),
        stripe_tools.list_active_prices("STRIPE_SECRET_KEY_VOLTARISOS"),
    ]

    combined = str(results)
    for marker in _MARKERS:
        assert marker not in combined, f"excluded field leaked into tool result: {marker}"
