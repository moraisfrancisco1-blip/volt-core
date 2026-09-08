from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select

from ..db import session_scope
from ..models import AuditRecord, BackOfficeReconciliationRecord, BackOfficeReportRecord, DaiOakesPaymentRecord, DealRecord, SalesLeadRecord
from . import daioakes_client, stripe_config, stripe_tools

# Reconciliation involves a live Stripe call, unlike Operations' pure-DB sweep -- same
# cadence floor discipline as every other periodic agent in this codebase.
SWEEP_INTERVAL_SECONDS = max(300, int(os.getenv("VOLT_BACKOFFICE_INTERVAL_SECONDS", "21600")))

_VOLTARISOS_SYSTEM_ID = "voltaris-os"
_SANDBOX_DISCLAIMER = "dados de sandbox, não representam receita real"
_NO_SOURCE_TEXT = "sem dados financeiros ainda"

# Every field this code will ever read from a Dai Oakes payment-control entry -- real
# money bookkeeping fields only, never a name/email/session/date-of-birth/clinical field.
# This is a second, independent allowlist on top of what Dai Oakes's own API already
# filters server-side (defense in depth, per the explicit red line for this connector).
#
# The second and third groups below were reviewed and approved on 2026-09-08 after the
# first-ever real sync flagged 13 fields as unexpected: all are payment/billing metadata
# (client id, invoice number, payment method, refund amount, Stripe status mirrors, a
# "total" amount, boolean verification/test-mode flags, a timestamp) -- nothing
# name/email/clinical-shaped. "problem" was held back one extra round specifically: a
# shape check (_summarize_unexpected_field_shapes, never the actual value) showed it's
# always exactly 12 characters or null, with only 2 distinct values across all 121
# records -- a small fixed enum/code, not free text -- and was approved on that basis.
_DAIOAKES_PAYMENT_FIELD_ALLOWLIST = {
    "id", "invoiceId", "amount", "amountPaid", "currency", "status",
    "dueDate", "paidAt", "createdAt", "stripeInvoiceId", "stripePaymentIntentId",
    "clientId", "invoiceNumber", "paymentMethod", "refundedAmount", "state",
    "stripeCheckoutStatus", "stripePaymentIntentStatus", "total", "verified",
    "isTest", "hasPayment", "lastStripeVerifiedAt",
    "problem",
}


def _extract_safe_dai_oakes_entries(raw_entries) -> tuple[list[dict], list[str]] | None:
    # Returns (safe_entries, unexpected_field_names), or None if raw_entries isn't a list
    # of objects at all (a genuinely malformed response, handled as a plain failure by the
    # caller). If ANY entry contains ANY field outside the allowlist -- even one, even if
    # it looks harmless -- the ENTIRE batch is rejected (safe_entries=[]) rather than
    # silently dropping just that field and continuing: a Volt Core red line explicitly
    # requires stopping and flagging, not quietly filtering and moving on. Only field
    # NAMES are ever returned, never their values, so even the incident report itself
    # can't leak whatever unexpected data showed up.
    if not isinstance(raw_entries, list):
        return None
    unexpected: set[str] = set()
    for entry in raw_entries:
        if not isinstance(entry, dict):
            return None
        unexpected |= (set(entry.keys()) - _DAIOAKES_PAYMENT_FIELD_ALLOWLIST)
    if unexpected:
        return [], sorted(unexpected)
    safe_entries = [{k: v for k, v in entry.items() if k in _DAIOAKES_PAYMENT_FIELD_ALLOWLIST} for entry in raw_entries]
    return safe_entries, []


_MAX_DISTINCT_VALUES_TO_COUNT = 20


def _summarize_unexpected_field_shapes(raw_entries: list[dict], unexpected_fields: list[str]) -> dict[str, dict]:
    # Lets a human tell "free text" from "small fixed enum" apart for a still-unexpected
    # field WITHOUT ever seeing (or us ever storing/logging) a single actual value --
    # only aggregate shape facts: which Python type(s) appear, string length range, and a
    # distinct-value count capped at _MAX_DISTINCT_VALUES_TO_COUNT (above the cap we only
    # say "more than N", since the count itself becomes a values-list proxy at high
    # cardinality e.g. near-unique free text).
    shapes: dict[str, dict] = {}
    for field in unexpected_fields:
        values = [entry[field] for entry in raw_entries if isinstance(entry, dict) and field in entry]
        if not values:
            continue
        shape: dict = {
            "observed_in": len(values),
            "python_types": sorted({type(v).__name__ for v in values}),
        }
        str_values = [v for v in values if isinstance(v, str)]
        if str_values:
            shape["min_length"] = min(len(v) for v in str_values)
            shape["max_length"] = max(len(v) for v in str_values)
        hashable_values = {v for v in values if v is None or isinstance(v, (str, int, float, bool))}
        if len(hashable_values) <= _MAX_DISTINCT_VALUES_TO_COUNT:
            shape["distinct_value_count"] = len(hashable_values)
        else:
            shape["distinct_value_count"] = f"more than {_MAX_DISTINCT_VALUES_TO_COUNT}"
        shapes[field] = shape
    return shapes


def _sync_dai_oakes_payments() -> None:
    result = daioakes_client.get_payment_control()

    with session_scope() as session:
        if "error" in result:
            error_text = result["error"]
            audit_type = "dai_oakes_payment_sync_skipped" if error_text.endswith("not configured") else "dai_oakes_payment_sync_failed"
            session.add(AuditRecord(type=audit_type, detail=error_text[:500]))
            return

        raw = result.get("data")
        if isinstance(raw, list):
            raw_entries = raw
        elif isinstance(raw, dict):
            raw_entries = raw.get("payments") if isinstance(raw.get("payments"), list) else raw.get("data")
        else:
            raw_entries = None

        extraction = _extract_safe_dai_oakes_entries(raw_entries) if raw_entries is not None else None
        if extraction is None:
            session.add(AuditRecord(type="backoffice_dai_oakes_sync_failed", detail="unexpected /api/service/payment-control response shape"))
            return

        safe_entries, unexpected_fields = extraction
        if unexpected_fields:
            # SECURITY INCIDENT -- named to start with "backoffice_" and end in "_failed"
            # so status_router's existing audit-based dashboard status picks this up as an
            # error automatically, without needing a bespoke check. Nothing from this
            # batch is stored; field NAMES only, never values, appear in the detail --
            # stored as JSON so the dashboard can show the field names and the affected
            # count without re-parsing free text (and so a value can never slip in as an
            # unstructured string).
            session.add(AuditRecord(
                type="backoffice_dai_oakes_security_incident_failed",
                detail=json.dumps({
                    "unexpected_fields": unexpected_fields,
                    "entries_affected": len(raw_entries),
                    "unexpected_field_shapes": _summarize_unexpected_field_shapes(raw_entries, unexpected_fields),
                }),
            ))
            return

        existing = {row.external_id: row for row in session.scalars(select(DaiOakesPaymentRecord)).all()}
        for entry in safe_entries:
            external_id = str(entry.get("id") or entry.get("invoiceId") or "").strip()
            if not external_id:
                continue
            record = existing.get(external_id)
            if record is None:
                record = DaiOakesPaymentRecord(external_id=external_id)
                session.add(record)
            record.status = str(entry.get("status") or "unknown")
            record.amount = entry.get("amount")
            record.amount_paid = entry.get("amountPaid")
            record.currency = entry.get("currency")
            record.due_date = entry.get("dueDate")
            record.paid_at = entry.get("paidAt")
            record.stripe_invoice_id = entry.get("stripeInvoiceId")
            record.synced_at = datetime.now(timezone.utc)
        session.add(AuditRecord(type="backoffice_dai_oakes_sync_completed", detail=f"entries={len(safe_entries)}"))


def _fetch_sandbox_invoices() -> tuple[str, dict[str, dict] | None]:
    # Returns (data_source, invoices_by_email). invoices_by_email is None whenever there
    # is nothing to match against (no key configured, or the call failed) -- callers
    # must never treat None as "zero invoices exist", only as "no data available".
    env_var = stripe_config.resolve_stripe_key_env_var(_VOLTARISOS_SYSTEM_ID)
    if env_var is None:
        return "no_source_configured", None
    result = stripe_tools.list_recent_invoices(env_var)
    if "error" in result:
        return "stripe_unavailable", None
    by_email: dict[str, dict] = {}
    for invoice in result.get("invoices") or []:
        email = invoice.get("customer_email")
        if email and email not in by_email:  # first (most recent) invoice per customer wins
            by_email[email] = invoice
    return "stripe_sandbox", by_email


def _reconcile_closed_deals() -> None:
    data_source, invoices_by_email = _fetch_sandbox_invoices()

    with session_scope() as session:
        closed_deal_ids = session.scalars(select(DealRecord.id).where(DealRecord.stage == "closed_won")).all()
        existing = {row.deal_id: row for row in session.scalars(select(BackOfficeReconciliationRecord)).all()}

        for deal_id in closed_deal_ids:
            deal = session.get(DealRecord, deal_id)
            lead = session.get(SalesLeadRecord, deal.lead_id) if deal else None
            email = (lead.email or "").strip().lower() if lead and lead.email else None

            if data_source == "no_source_configured":
                match_found, invoice_id, note = False, None, _NO_SOURCE_TEXT
            elif data_source == "stripe_unavailable":
                match_found, invoice_id, note = False, None, f"Stripe indisponível neste momento -- rever manualmente ({_SANDBOX_DISCLAIMER})."
            elif email is None:
                match_found, invoice_id, note = False, None, f"Sem email de lead associado a este deal -- não é possível procurar correspondência ({_SANDBOX_DISCLAIMER})."
            else:
                invoice = (invoices_by_email or {}).get(email)
                if invoice:
                    match_found, invoice_id = True, invoice.get("id")
                    note = f"Fatura sandbox correspondente encontrada (estado: {invoice.get('status')}) -- {_SANDBOX_DISCLAIMER}."
                else:
                    match_found, invoice_id = False, None
                    note = f"Sem fatura sandbox correspondente para {email} -- {_SANDBOX_DISCLAIMER}. Rever manualmente."

            record = existing.get(deal_id)
            if record is None:
                record = BackOfficeReconciliationRecord(deal_id=deal_id)
                session.add(record)
            record.data_source = data_source
            record.match_found = match_found
            record.stripe_invoice_id = invoice_id
            record.note = note

        session.add(AuditRecord(type="backoffice_reconciliation_run", detail=f"data_source={data_source}, deals={len(closed_deal_ids)}"))


def run_generate_report() -> None:
    with session_scope() as session:
        closed_ids = session.scalars(select(DealRecord.id).where(DealRecord.stage == "closed_won")).all()
        reconciliations = session.scalars(
            select(BackOfficeReconciliationRecord).where(BackOfficeReconciliationRecord.deal_id.in_(closed_ids))
        ).all() if closed_ids else []

        matched = sum(1 for r in reconciliations if r.match_found)
        unmatched = len(reconciliations) - matched
        data_source = reconciliations[0].data_source if reconciliations else "no_source_configured"

        if not closed_ids:
            summary = "Sem deals fechados (Fechado Ganho) ainda."
        elif data_source == "no_source_configured":
            summary = f"{len(closed_ids)} deal(s) fechado(s). {_NO_SOURCE_TEXT} (nenhuma chave Stripe configurada para voltaris-os)."
        elif data_source == "stripe_unavailable":
            summary = f"{len(closed_ids)} deal(s) fechado(s). Stripe indisponível neste momento -- não foi possível verificar faturação."
        else:
            summary = (
                f"{len(closed_ids)} deal(s) fechado(s): {matched} com fatura sandbox correspondente, "
                f"{unmatched} sem correspondência (rever manualmente). {_SANDBOX_DISCLAIMER}."
            )

        # matched/unmatched only mean "checked against Stripe" when there was actually
        # something to check against -- with no source configured (or Stripe down), no
        # deal was truly "checked and found unmatched", so both stay 0 rather than
        # implying a real comparison happened.
        checked = data_source == "stripe_sandbox"
        session.add(BackOfficeReportRecord(
            data_source=data_source,
            deals_closed_count=len(closed_ids),
            deals_matched_count=matched if checked else 0,
            deals_unmatched_count=unmatched if checked else 0,
            summary=summary,
        ))
        session.add(AuditRecord(type="backoffice_report_created", detail=data_source))


def run_backoffice_sweep() -> None:
    # Deliberately deterministic, no model call: every number here is a real count from
    # the database or the Stripe sandbox, never a generated or projected figure -- there
    # is nothing here an LLM could add value to without risking an invented number.
    try:
        _reconcile_closed_deals()
        run_generate_report()
        _sync_dai_oakes_payments()
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="backoffice_sweep_failed", detail=f"{type(exc).__name__}: {str(exc)[:500]}"))


_started = False
_lock = threading.Lock()
_sweep_in_progress = False


def is_sweep_in_progress() -> bool:
    return _sweep_in_progress


def _sweep_loop() -> None:
    global _sweep_in_progress
    while True:
        try:
            _sweep_in_progress = True
            run_backoffice_sweep()
        except Exception as exc:
            print(f"[volt-core-backoffice] sweep failure: {type(exc).__name__}: {exc}")
        finally:
            _sweep_in_progress = False
        time.sleep(SWEEP_INTERVAL_SECONDS)


def start_backoffice_agent() -> None:
    # No LLM gate needed -- this agent never calls a model, only Stripe (read-only) and
    # its own database tables.
    global _started
    if _started:
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_sweep_loop, name="volt-core-backoffice", daemon=True).start()
        _started = True
