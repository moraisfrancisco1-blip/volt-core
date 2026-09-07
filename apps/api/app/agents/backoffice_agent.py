from __future__ import annotations

import os
import threading
import time

from sqlalchemy import select

from ..db import session_scope
from ..models import AuditRecord, BackOfficeReconciliationRecord, BackOfficeReportRecord, DealRecord, SalesLeadRecord
from . import stripe_config, stripe_tools

# Reconciliation involves a live Stripe call, unlike Operations' pure-DB sweep -- same
# cadence floor discipline as every other periodic agent in this codebase.
SWEEP_INTERVAL_SECONDS = max(300, int(os.getenv("VOLT_BACKOFFICE_INTERVAL_SECONDS", "21600")))

_VOLTARISOS_SYSTEM_ID = "voltaris-os"
_SANDBOX_DISCLAIMER = "dados de sandbox, não representam receita real"
_NO_SOURCE_TEXT = "sem dados financeiros ainda"


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
