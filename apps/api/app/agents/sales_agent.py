from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from .. import llm_client
from ..db import session_scope
from ..models import AuditRecord, SalesLeadRecord, SalesOutreachDraftRecord

# Leads can't wait a week like the Market Intelligence digest -- default cadence is much
# tighter (6h). max() floor keeps a misconfigured tiny value from turning this into an
# accidental spam loop, same discipline as every other periodic agent in this codebase.
SWEEP_INTERVAL_SECONDS = max(300, int(os.getenv("VOLT_SALES_INTERVAL_SECONDS", "21600")))
MODEL = os.getenv("VOLT_SALES_MODEL") or llm_client.default_model()
MAX_TOKENS = 1024

CONSUMER_ICP_PROMPT = (
    "Perfil de cliente ideal (consumidor): dono de casa individual na Holanda ou "
    "restante UE que já tem painéis solares instalados, e está a considerar (ou já "
    "perguntou sobre) uma bateria doméstica e/ou um carregador inteligente de EV. "
    "Sinais positivos: menciona querer reduzir dependência da rede, poupar com "
    "preços dinâmicos, ou já usa/considera um veículo elétrico. Este perfil serve "
    "só para qualificar leads que já chegaram por iniciativa própria -- nunca para "
    "os encontrar ou contactar primeiro."
)
B2B_ICP_PROMPT = (
    "Perfil de parceiro ideal (B2B): instaladora de painéis solares ou consultora "
    "de energia sediada na Holanda, com historial de trabalhar com donos de casa "
    "individuais em projetos de solar/bateria/carregamento EV. Sinais positivos: "
    "já opera na Holanda, tem uma equipa de instalação própria ou uma rede de "
    "parceiros, e não é uma concorrente direta do VoltarisOS (não vende o seu "
    "próprio software de gestão energética)."
)

_DEFAULT_B2B_PROSPECTS: list[dict] = []

SUBMIT_QUALIFICATION_TOOL_NAME = "submit_lead_qualification"
SUBMIT_QUALIFICATION_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_QUALIFICATION_TOOL_NAME,
    "description": "Submete a qualificação de um lead contra o ICP fornecido. Chama isto exatamente uma vez.",
    "input_schema": {
        "type": "object",
        "properties": {
            "fit_score": {"type": "number", "description": "0.0 a 1.0 -- quão bem este lead encaixa no ICP."},
            "qualification_summary": {"type": "string", "description": "Resumo curto: quem é, porque parece (ou não) um bom fit."},
            "suggested_next_step": {"type": "string", "description": "Próximo passo concreto sugerido."},
        },
        "required": ["fit_score", "qualification_summary", "suggested_next_step"],
    },
}

SUBMIT_OUTREACH_TOOL_NAME = "submit_outreach_draft"
SUBMIT_OUTREACH_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_OUTREACH_TOOL_NAME,
    "description": "Submete um rascunho de email de outreach B2B. Chama isto exatamente uma vez.",
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "Assunto do email, curto e direto."},
            "body": {"type": "string", "description": "Corpo do email em português, profissional, com uma linha clara de opt-out no final."},
        },
        "required": ["subject", "body"],
    },
}

SUBMIT_CALL_PREP_TOOL_NAME = "submit_call_prep"
SUBMIT_CALL_PREP_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_CALL_PREP_TOOL_NAME,
    "description": "Submete um resumo curto de preparação para uma chamada/demo com um lead. Chama isto exatamente uma vez.",
    "input_schema": {
        "type": "object",
        "properties": {
            "call_prep_summary": {"type": "string", "description": "Resumo curto: quem é o lead, contexto relevante, e 2-3 pontos a cobrir na chamada."},
        },
        "required": ["call_prep_summary"],
    },
}

_QUALIFICATION_SYSTEM_PROMPT = (
    "És o Agente de Sales do VOLT CORE, dedicado ao VoltarisOS. A tua única função "
    "aqui é qualificar UM lead que já existe no sistema contra o perfil de cliente "
    "ideal fornecido -- nunca inventas leads, nunca sugeres formas de os encontrar "
    "ou contactar por conta própria. Sê honesto: um fit_score baixo é uma resposta "
    "válida e útil, não forces um lead a parecer melhor do que é."
)

_CALL_PREP_SYSTEM_PROMPT = (
    "És o Agente de Sales do VOLT CORE. Prepara um resumo curto de preparação para "
    "uma chamada/demo que já foi marcada com um lead -- baseia-te só no contexto e "
    "qualificação já existentes, não inventes detalhes novos sobre o lead."
)

_OUTREACH_SYSTEM_PROMPT = (
    "És o Agente de Sales do VOLT CORE, dedicado ao VoltarisOS. Prepara um rascunho "
    "de email de outreach B2B profissional para um parceiro potencial (instaladora "
    "ou consultora de energia), propondo uma parceria/referência com o VoltarisOS. "
    "O email TEM de incluir, no final, uma linha clara a explicar como recusar "
    "contacto futuro (ex. 'Se preferires não receber mais contacto, basta "
    "responder a dizer que sim.'). Este rascunho nunca é enviado por ti -- fica "
    "sempre pendente de aprovação humana antes de qualquer envio real."
)


def _b2b_prospects() -> list[dict]:
    raw = os.getenv("VOLT_SALES_B2B_PROSPECTS", "").strip()
    if not raw:
        return list(_DEFAULT_B2B_PROSPECTS)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return list(_DEFAULT_B2B_PROSPECTS)
    if not isinstance(payload, list):
        return list(_DEFAULT_B2B_PROSPECTS)
    prospects = []
    for entry in payload:
        if isinstance(entry, dict) and entry.get("name") and entry.get("email"):
            prospects.append(entry)
    return prospects


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


def _sync_b2b_prospects() -> None:
    with session_scope() as session:
        existing_emails = {
            row for row in session.scalars(
                select(SalesLeadRecord.email).where(SalesLeadRecord.lead_type == "b2b_partner")
            ).all()
        }
        for prospect in _b2b_prospects():
            email = str(prospect["email"]).strip().lower()
            if not email or email in existing_emails:
                continue
            session.add(SalesLeadRecord(
                lead_type="b2b_partner",
                status="new",
                source="volt_sales_b2b_prospects_config",
                name=str(prospect["name"]),
                email=email,
                company=str(prospect.get("company") or prospect["name"]),
                context=str(prospect.get("notes") or ""),
                consent_basis="b2b_legitimate_interest",
            ))
            existing_emails.add(email)


def _qualify_new_leads() -> None:
    with session_scope() as session:
        new_lead_ids = session.scalars(select(SalesLeadRecord.id).where(SalesLeadRecord.status == "new")).all()

    for lead_id in new_lead_ids:
        try:
            with session_scope() as session:
                lead = session.get(SalesLeadRecord, lead_id)
                if lead is None or lead.status != "new":
                    continue
                icp = CONSUMER_ICP_PROMPT if lead.lead_type == "consumer_inbound" else B2B_ICP_PROMPT
                prompt = (
                    f"Perfil de cliente ideal:\n{icp}\n\n"
                    f"Lead a qualificar:\nNome: {lead.name}\nEmail: {lead.email}\n"
                    f"Empresa: {lead.company or 'N/A'}\nOrigem: {lead.source or 'desconhecida'}\n"
                    f"Contexto: {lead.context or '(sem contexto adicional)'}"
                )
                response = _call_model(_QUALIFICATION_SYSTEM_PROMPT, prompt, SUBMIT_QUALIFICATION_TOOL_SCHEMA, SUBMIT_QUALIFICATION_TOOL_NAME)
                submitted = _extract_tool_input(response, SUBMIT_QUALIFICATION_TOOL_NAME)
                if submitted is None:
                    session.add(AuditRecord(type="sales_lead_qualification_failed", reference_id=str(lead_id), detail=f"model stopped ({response.stop_reason}) without submitting"))
                    continue
                lead.fit_score = float(submitted.get("fit_score") or 0.0)
                lead.qualification_summary = str(submitted.get("qualification_summary") or "")
                lead.suggested_next_step = str(submitted.get("suggested_next_step") or "")
                lead.model = MODEL
                lead.status = "qualified"
                lead.qualified_at = datetime.now(timezone.utc)
                session.add(AuditRecord(type="sales_lead_qualified", reference_id=str(lead_id), detail=f"fit_score={lead.fit_score}"))
        except Exception as exc:
            # One lead's failure must never abort qualification of the rest.
            with session_scope() as session:
                session.add(AuditRecord(type="sales_lead_qualification_failed", reference_id=str(lead_id), detail=str(exc)[:500]))


def _generate_pending_outreach_drafts() -> None:
    with session_scope() as session:
        drafted_lead_ids = {row for row in session.scalars(select(SalesOutreachDraftRecord.lead_id)).all()}
        candidate_ids = session.scalars(
            select(SalesLeadRecord.id).where(SalesLeadRecord.lead_type == "b2b_partner", SalesLeadRecord.status == "qualified")
        ).all()
        pending_ids = [lead_id for lead_id in candidate_ids if lead_id not in drafted_lead_ids]

    for lead_id in pending_ids:
        try:
            with session_scope() as session:
                lead = session.get(SalesLeadRecord, lead_id)
                if lead is None:
                    continue
                prompt = (
                    f"Parceiro potencial:\nNome/Empresa: {lead.company or lead.name}\n"
                    f"Contacto: {lead.name} <{lead.email}>\nNotas: {lead.context or '(sem notas)'}\n"
                    f"Porque é um bom fit: {lead.qualification_summary or '(não avaliado)'}"
                )
                response = _call_model(_OUTREACH_SYSTEM_PROMPT, prompt, SUBMIT_OUTREACH_TOOL_SCHEMA, SUBMIT_OUTREACH_TOOL_NAME)
                submitted = _extract_tool_input(response, SUBMIT_OUTREACH_TOOL_NAME)
                if submitted is None:
                    session.add(AuditRecord(type="sales_outreach_draft_failed", reference_id=str(lead_id), detail=f"model stopped ({response.stop_reason}) without submitting"))
                    continue
                session.add(SalesOutreachDraftRecord(
                    lead_id=lead_id,
                    subject=str(submitted.get("subject") or ""),
                    body=str(submitted.get("body") or ""),
                    status="pending_approval",
                    model=MODEL,
                ))
                session.add(AuditRecord(type="sales_outreach_draft_created", reference_id=str(lead_id), detail="status=pending_approval"))
        except Exception as exc:
            # One draft's failure must never abort the rest.
            with session_scope() as session:
                session.add(AuditRecord(type="sales_outreach_draft_failed", reference_id=str(lead_id), detail=str(exc)[:500]))


def run_sales_sweep() -> None:
    try:
        _sync_b2b_prospects()
        _qualify_new_leads()
        _generate_pending_outreach_drafts()
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="sales_sweep_failed", detail=f"{type(exc).__name__}: {str(exc)[:500]}"))


def run_call_prep(lead_id: int) -> None:
    try:
        with session_scope() as session:
            lead = session.get(SalesLeadRecord, lead_id)
            if lead is None:
                return
            icp = CONSUMER_ICP_PROMPT if lead.lead_type == "consumer_inbound" else B2B_ICP_PROMPT
            prompt = (
                f"Perfil de cliente ideal:\n{icp}\n\n"
                f"Lead: {lead.name} <{lead.email}> ({lead.company or 'consumidor'})\n"
                f"Qualificação já feita: {lead.qualification_summary or '(ainda não qualificado)'}\n"
                f"Próximo passo sugerido: {lead.suggested_next_step or '(nenhum)'}\n\n"
                "Foi marcada uma chamada/demo com este lead. Prepara um resumo curto de "
                "preparação: quem é, contexto relevante, e 2-3 pontos a cobrir na chamada."
            )
            response = _call_model(_CALL_PREP_SYSTEM_PROMPT, prompt, SUBMIT_CALL_PREP_TOOL_SCHEMA, SUBMIT_CALL_PREP_TOOL_NAME)
            submitted = _extract_tool_input(response, SUBMIT_CALL_PREP_TOOL_NAME)
            if submitted is None:
                session.add(AuditRecord(type="sales_call_prep_failed", reference_id=str(lead_id), detail=f"model stopped ({response.stop_reason}) without submitting"))
                return
            lead.call_prep_summary = str(submitted.get("call_prep_summary") or "")
            if lead.scheduled_call_at is None:
                lead.scheduled_call_at = datetime.now(timezone.utc)
            session.add(AuditRecord(type="sales_call_prep_ready", reference_id=str(lead_id)))
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="sales_call_prep_failed", reference_id=str(lead_id), detail=str(exc)[:500]))


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
                run_sales_sweep()
        except Exception as exc:
            print(f"[volt-core-sales] sweep failure: {type(exc).__name__}: {exc}")
        finally:
            _sweep_in_progress = False
        time.sleep(SWEEP_INTERVAL_SECONDS)


def start_sales_agent() -> None:
    global _started
    if _started or not llm_client.is_configured():
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_sweep_loop, name="volt-core-sales", daemon=True).start()
        _started = True
