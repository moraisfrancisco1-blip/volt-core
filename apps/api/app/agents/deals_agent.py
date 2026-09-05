from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from .. import llm_client
from ..db import session_scope
from ..models import AuditRecord, DealProposalRecord, DealRecord, SalesLeadRecord, SalesOutreachDraftRecord
from . import stripe_config, stripe_tools

# Deals move at the same pace as the leads that feed them -- same cadence as the Sales
# agent by default. max() floor keeps a misconfigured tiny value from turning this into
# an accidental spam loop, same discipline as every other periodic agent in this codebase.
SWEEP_INTERVAL_SECONDS = max(300, int(os.getenv("VOLT_DEALS_INTERVAL_SECONDS", "21600")))
STALE_DAYS = max(1, int(os.getenv("VOLT_DEALS_STALE_DAYS", "7")))
MODEL = os.getenv("VOLT_DEALS_MODEL") or llm_client.default_model()
MAX_TOKENS = 1024

_NO_PRICE_TEXT = "confirmar preço com o Francisco"
_VOLTARISOS_SYSTEM_ID = "voltaris-os"

SUBMIT_PROPOSAL_TOOL_NAME = "submit_deal_proposal"
SUBMIT_PROPOSAL_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_PROPOSAL_TOOL_NAME,
    "description": "Submete um rascunho de proposta comercial para este deal. Chama isto exatamente uma vez.",
    "input_schema": {
        "type": "object",
        "properties": {
            "price_summary": {
                "type": "string",
                "description": f"Resumo do preço usado, citando o catálogo fornecido. Se o catálogo não tiver um preço claro para esta situação, usa literalmente '{_NO_PRICE_TEXT}'.",
            },
            "body": {"type": "string", "description": "Corpo completo da proposta comercial, em português, profissional."},
        },
        "required": ["price_summary", "body"],
    },
}

SUBMIT_CLOSE_SUGGESTION_TOOL_NAME = "submit_close_suggestion"
SUBMIT_CLOSE_SUGGESTION_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_CLOSE_SUGGESTION_TOOL_NAME,
    "description": "Submete uma sugestão de fecho de deal com base numa nota real fornecida por um humano. Chama isto exatamente uma vez.",
    "input_schema": {
        "type": "object",
        "properties": {
            "suggested_stage": {"type": "string", "enum": ["closed_won", "closed_lost"]},
            "reason": {"type": "string", "description": "Justificação curta, baseada só na nota fornecida -- nunca inventada."},
        },
        "required": ["suggested_stage", "reason"],
    },
}

_PROPOSAL_SYSTEM_PROMPT = (
    "És o Agente de Deals do VOLT CORE, dedicado ao VoltarisOS. Preparas rascunhos de "
    "propostas comerciais para leads já qualificados pelo Sales. NUNCA inventas um "
    f"preço ou condição comercial -- usa só o catálogo de preços fornecido; se não "
    f"houver um preço real e claro aplicável, escreve literalmente '{_NO_PRICE_TEXT}' "
    "em price_summary e deixa isso claro também no corpo da proposta. Esta proposta "
    "nunca é enviada por ti -- fica sempre pendente de aprovação humana."
)

_CLOSE_SUGGESTION_SYSTEM_PROMPT = (
    "És o Agente de Deals do VOLT CORE. Um humano deu-te uma nota sobre o estado real "
    "de um deal (algo que só ele sabe, ex. uma resposta do cliente). Com base só nessa "
    "nota, sugere se o deal deve fechar como ganho ou perdido, e porquê. Nunca inventas "
    "factos além do que a nota diz. Esta sugestão nunca muda o estado do deal sozinha "
    "-- só um humano confirma isso no dashboard."
)


def _call_model(system: str, prompt: str, tool_schema: dict, tool_name: str) -> Any:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    client = llm_client.get_client()
    return client.call(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        tools=[tool_schema],
        tool_choice=tool_name,
        messages=[{"role": "user", "content": prompt}],
    )


def _extract_tool_input(response: Any, tool_name: str) -> dict | None:
    for block in response.content:
        if block.get("type") == "tool_use" and block["name"] == tool_name:
            return block["input"]
    return None


def _price_catalog_text() -> str:
    env_var = stripe_config.resolve_stripe_key_env_var(_VOLTARISOS_SYSTEM_ID)
    if env_var is None:
        return f"[sem chave Stripe configurada para {_VOLTARISOS_SYSTEM_ID}]"
    result = stripe_tools.list_active_prices(env_var)
    if "error" in result:
        return f"[catálogo de preços Stripe indisponível: {result['error']}]"
    prices = result.get("prices") or []
    if not prices:
        return "[nenhum preço ativo encontrado na Stripe]"
    lines = []
    for price in prices:
        amount = price.get("unit_amount")
        amount_text = f"{amount / 100:.2f}" if isinstance(amount, (int, float)) else "?"
        interval = f"/{price['recurring_interval']}" if price.get("recurring_interval") else ""
        name = price.get("product_name") or price.get("nickname") or price.get("id")
        lines.append(f"{name}: {amount_text} {(price.get('currency') or '').upper()}{interval} (price id: {price.get('id')})")
    return "\n".join(lines)


def _sync_deals_from_sales() -> None:
    with session_scope() as session:
        existing_lead_ids = {row for row in session.scalars(select(DealRecord.lead_id)).all()}
        sent_draft_lead_ids = {
            row for row in session.scalars(
                select(SalesOutreachDraftRecord.lead_id).where(SalesOutreachDraftRecord.status == "approved_sent")
            ).all()
        }
        qualified_leads = session.scalars(select(SalesLeadRecord).where(SalesLeadRecord.status == "qualified")).all()

        for lead in qualified_leads:
            if lead.id in existing_lead_ids:
                continue
            if lead.lead_type == "b2b_partner" and lead.id not in sent_draft_lead_ids:
                continue  # B2B partners only enter the pipeline once actually contacted
            session.add(DealRecord(lead_id=lead.id, stage="qualified"))
            existing_lead_ids.add(lead.id)


def _prepare_proposals_for_qualified_deals() -> None:
    with session_scope() as session:
        proposed_deal_ids = {row for row in session.scalars(select(DealProposalRecord.deal_id)).all()}
        candidate_ids = session.scalars(select(DealRecord.id).where(DealRecord.stage == "qualified")).all()
        pending_ids = [deal_id for deal_id in candidate_ids if deal_id not in proposed_deal_ids]

    if not pending_ids:
        return

    price_catalog = _price_catalog_text()

    for deal_id in pending_ids:
        try:
            with session_scope() as session:
                deal = session.get(DealRecord, deal_id)
                if deal is None or deal.stage != "qualified":
                    continue
                lead = session.get(SalesLeadRecord, deal.lead_id)
                if lead is None:
                    continue
                prompt = (
                    f"Catálogo de preços real (Stripe):\n{price_catalog}\n\n"
                    f"Lead/parceiro:\nNome: {lead.name}\nEmail: {lead.email}\n"
                    f"Empresa: {lead.company or 'N/A'} (tipo: {lead.lead_type})\n"
                    f"Qualificação: {lead.qualification_summary or '(sem resumo)'}\n"
                    f"Próximo passo sugerido pelo Sales: {lead.suggested_next_step or '(nenhum)'}"
                )
                response = _call_model(_PROPOSAL_SYSTEM_PROMPT, prompt, SUBMIT_PROPOSAL_TOOL_SCHEMA, SUBMIT_PROPOSAL_TOOL_NAME)
                submitted = _extract_tool_input(response, SUBMIT_PROPOSAL_TOOL_NAME)
                if submitted is None:
                    session.add(AuditRecord(type="deal_proposal_failed", reference_id=str(deal_id), detail=f"model stopped ({response.stop_reason}) without submitting"))
                    continue
                session.add(DealProposalRecord(
                    deal_id=deal_id,
                    price_summary=str(submitted.get("price_summary") or _NO_PRICE_TEXT),
                    body=str(submitted.get("body") or ""),
                    status="pending_approval",
                    model=MODEL,
                ))
                deal.stage = "proposal_prepared"
                deal.stage_changed_at = datetime.now(timezone.utc)
                deal.model = MODEL
                session.add(AuditRecord(type="deal_proposal_created", reference_id=str(deal_id), detail="status=pending_approval"))
        except Exception as exc:
            # One proposal's failure must never abort the rest.
            with session_scope() as session:
                session.add(AuditRecord(type="deal_proposal_failed", reference_id=str(deal_id), detail=str(exc)[:500]))


def run_deals_sweep() -> None:
    try:
        _sync_deals_from_sales()
        _prepare_proposals_for_qualified_deals()
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="deals_sweep_failed", detail=f"{type(exc).__name__}: {str(exc)[:500]}"))


def run_close_suggestion(deal_id: int, note: str) -> None:
    # Never touches `stage` -- only ever writes suggested_stage/suggested_stage_reason.
    # The actual stage change is a separate, explicit human action (confirm-stage).
    try:
        with session_scope() as session:
            deal = session.get(DealRecord, deal_id)
            if deal is None:
                return
            prompt = f"Nota fornecida sobre este deal (deal #{deal_id}, estágio atual: {deal.stage}):\n{note}"
            response = _call_model(_CLOSE_SUGGESTION_SYSTEM_PROMPT, prompt, SUBMIT_CLOSE_SUGGESTION_TOOL_SCHEMA, SUBMIT_CLOSE_SUGGESTION_TOOL_NAME)
            submitted = _extract_tool_input(response, SUBMIT_CLOSE_SUGGESTION_TOOL_NAME)
            if submitted is None:
                session.add(AuditRecord(type="deal_close_suggestion_failed", reference_id=str(deal_id), detail=f"model stopped ({response.stop_reason}) without submitting"))
                return
            deal.suggested_stage = str(submitted.get("suggested_stage") or "")
            deal.suggested_stage_reason = str(submitted.get("reason") or "")
            session.add(AuditRecord(type="deal_close_suggested", reference_id=str(deal_id), detail=deal.suggested_stage))
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="deal_close_suggestion_failed", reference_id=str(deal_id), detail=str(exc)[:500]))


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
            if llm_client.is_configured():
                run_deals_sweep()
        except Exception as exc:
            print(f"[volt-core-deals] sweep failure: {type(exc).__name__}: {exc}")
        finally:
            _sweep_in_progress = False
        time.sleep(SWEEP_INTERVAL_SECONDS)


def start_deals_agent() -> None:
    global _started
    if _started or not llm_client.is_configured():
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_sweep_loop, name="volt-core-deals", daemon=True).start()
        _started = True
