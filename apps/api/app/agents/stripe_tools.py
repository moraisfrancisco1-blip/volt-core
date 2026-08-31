from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from ..db import session_scope
from ..models import AgentInvestigationRecord

_API_BASE = "https://api.stripe.com/v1"


@dataclass(frozen=True)
class FinanceJob:
    event_id: int
    escalation_id: int
    system: str
    environment: str
    priority: str
    stripe_key_env_var: str  # name of the env var holding the key, never the value itself
    parent_investigation_id: int


def _stripe_request(method: str, path: str, *, api_key_env_var: str, params: dict | None = None) -> httpx.Response | None:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    # Returns None only on a transport-level failure (DNS/timeout/connection refused);
    # HTTP error statuses (400/401/...) come back as a normal Response for callers to
    # interpret, same as _github_request/_railway_request.
    api_key = os.getenv(api_key_env_var)
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(base_url=_API_BASE, timeout=15) as client:
            return client.request(method, path, headers=headers, params=params)
    except httpx.HTTPError:
        return None


def _epoch_to_iso(ts: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat() if ts is not None else None
    except (TypeError, ValueError, OSError):
        return None


def list_recent_charges(job: FinanceJob, limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 100))
    response = _stripe_request("GET", "/charges", api_key_env_var=job.stripe_key_env_var, params={"limit": limit})
    if response is None:
        return {"error": "Stripe API request failed (network/transport error)"}
    if response.status_code != 200:
        return {"error": f"Stripe API returned {response.status_code}"}
    return {
        "charges": [
            {
                "id": c.get("id"),
                "status": c.get("status"),
                "amount": c.get("amount"),
                "amount_captured": c.get("amount_captured"),
                "amount_refunded": c.get("amount_refunded"),
                "currency": c.get("currency"),
                "created": _epoch_to_iso(c.get("created")),
                "captured": c.get("captured"),
                "paid": c.get("paid"),
                "refunded": c.get("refunded"),
                "disputed": c.get("disputed"),
                "failure_code": c.get("failure_code"),
                "failure_message": c.get("failure_message"),
                "outcome_type": (c.get("outcome") or {}).get("type"),
                "outcome_network_status": (c.get("outcome") or {}).get("network_status"),
                "customer": c.get("customer"),  # opaque cus_... id -- never expanded, never a name/email
            }
            for c in response.json().get("data", [])
        ]
    }


def list_open_disputes(job: FinanceJob, limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 100))
    response = _stripe_request("GET", "/disputes", api_key_env_var=job.stripe_key_env_var, params={"limit": limit})
    if response is None:
        return {"error": "Stripe API request failed (network/transport error)"}
    if response.status_code != 200:
        return {"error": f"Stripe API returned {response.status_code}"}
    return {
        "disputes": [
            {
                "id": d.get("id"),
                "charge": d.get("charge"),  # opaque ch_... id
                "amount": d.get("amount"),
                "currency": d.get("currency"),
                "status": d.get("status"),
                "reason": d.get("reason"),
                "created": _epoch_to_iso(d.get("created")),
                "is_charge_refundable": d.get("is_charge_refundable"),
                "evidence_due_by": _epoch_to_iso((d.get("evidence_details") or {}).get("due_by")),
                "evidence_has_evidence": (d.get("evidence_details") or {}).get("has_evidence"),
                "evidence_past_due": (d.get("evidence_details") or {}).get("past_due"),
                "evidence_submission_count": (d.get("evidence_details") or {}).get("submission_count"),
            }
            for d in response.json().get("data", [])
        ]
    }


def get_account_balance(job: FinanceJob) -> dict:
    response = _stripe_request("GET", "/balance", api_key_env_var=job.stripe_key_env_var)
    if response is None:
        return {"error": "Stripe API request failed (network/transport error)"}
    if response.status_code != 200:
        return {"error": f"Stripe API returned {response.status_code}"}
    payload = response.json()
    return {
        "available": [{"amount": b.get("amount"), "currency": b.get("currency"), "source_types": b.get("source_types")} for b in payload.get("available", [])],
        "pending": [{"amount": b.get("amount"), "currency": b.get("currency"), "source_types": b.get("source_types")} for b in payload.get("pending", [])],
    }


def list_recent_payouts(job: FinanceJob, limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 100))
    response = _stripe_request("GET", "/payouts", api_key_env_var=job.stripe_key_env_var, params={"limit": limit})
    if response is None:
        return {"error": "Stripe API request failed (network/transport error)"}
    if response.status_code != 200:
        return {"error": f"Stripe API returned {response.status_code}"}
    return {
        "payouts": [
            {
                "id": p.get("id"),
                "amount": p.get("amount"),
                "currency": p.get("currency"),
                "status": p.get("status"),
                "arrival_date": _epoch_to_iso(p.get("arrival_date")),
                "created": _epoch_to_iso(p.get("created")),
                "type": p.get("type"),
                "method": p.get("method"),
                "automatic": p.get("automatic"),
                "failure_code": p.get("failure_code"),
                "failure_message": p.get("failure_message"),
                "destination": p.get("destination"),  # opaque ba_.../card_... id
            }
            for p in response.json().get("data", [])
        ]
    }


def list_subscriptions(job: FinanceJob, status: str | None = None, limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 100))
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    response = _stripe_request("GET", "/subscriptions", api_key_env_var=job.stripe_key_env_var, params=params)
    if response is None:
        return {"error": "Stripe API request failed (network/transport error)"}
    if response.status_code != 200:
        return {"error": f"Stripe API returned {response.status_code}"}
    return {
        "subscriptions": [
            {
                "id": s.get("id"),
                "status": s.get("status"),
                "customer": s.get("customer"),  # opaque cus_... id
                "created": _epoch_to_iso(s.get("created")),
                "current_period_start": _epoch_to_iso(s.get("current_period_start")),
                "current_period_end": _epoch_to_iso(s.get("current_period_end")),
                "cancel_at_period_end": s.get("cancel_at_period_end"),
                "canceled_at": _epoch_to_iso(s.get("canceled_at")),
                "cancellation_reason": (s.get("cancellation_details") or {}).get("reason"),
                "cancellation_feedback": (s.get("cancellation_details") or {}).get("feedback"),
                "items": [
                    {"price": (item.get("price") or {}).get("id"), "quantity": item.get("quantity")}
                    for item in (s.get("items") or {}).get("data", [])
                ],
            }
            for s in response.json().get("data", [])
        ]
    }


def get_prior_investigation(job: FinanceJob) -> dict:
    with session_scope() as session:
        record = session.get(AgentInvestigationRecord, job.parent_investigation_id)
        if record is None:
            return {"error": "prior investigation not found"}
        return {
            "id": record.id,
            "status": record.status,
            "hypothesis": record.hypothesis,
            "recommended_next_step": record.recommended_next_step,
            "confidence": record.confidence,
            "is_known_pattern": record.is_known_pattern,
        }


# Read-only. Every handler above returns a strict field allowlist, never the raw Stripe
# payload -- this account holds real financial and customer data for a real business.
# See stripe_tools' tests for the regression guard: no excluded (PII / free-text) field
# ever survives into a returned dict.
TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "list_recent_charges": list_recent_charges,
    "list_open_disputes": list_open_disputes,
    "get_account_balance": get_account_balance,
    "list_recent_payouts": list_recent_payouts,
    "list_subscriptions": list_subscriptions,
    "get_prior_investigation": get_prior_investigation,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_recent_charges",
        "description": "Read recent charges on this system's Stripe account: status, amounts, failure code/message, and outcome. Look for a cluster of failures rather than a single one -- a single failed charge is normal noise.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Max charges to return, most recent first (default 20, max 100)"}},
            "required": [],
        },
    },
    {
        "name": "list_open_disputes",
        "description": "Read disputes (chargebacks) on this account: status, reason, amount, and evidence-submission deadline. A relevant signal for booking/customer-facing businesses.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Max disputes to return, most recent first (default 20, max 100)"}},
            "required": [],
        },
    },
    {
        "name": "get_account_balance",
        "description": "Read the current available and pending balance on this Stripe account, by currency.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_recent_payouts",
        "description": "Read recent payouts to this account's bank/card destination: amount, status, arrival date, and failure code/message if one failed.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Max payouts to return, most recent first (default 20, max 100)"}},
            "required": [],
        },
    },
    {
        "name": "list_subscriptions",
        "description": "Read subscriptions on this account: status, billing period, and cancellation reason/feedback if canceled. Useful for spotting a churn pattern (a burst of cancellations or past_due subscriptions).",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Optional Stripe subscription status filter (e.g. 'active', 'past_due', 'canceled', 'all'). Omit for Stripe's default (active-ish statuses)."},
                "limit": {"type": "integer", "description": "Max subscriptions to return (default 20, max 100)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_prior_investigation",
        "description": "Read Volt's earlier diagnosis of this same incident (hypothesis, recommended next step, confidence) -- start here so you're not investigating from scratch.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]
