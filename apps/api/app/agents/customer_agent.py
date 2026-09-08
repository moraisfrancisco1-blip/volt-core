from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from .. import llm_client
from ..db import session_scope
from ..models import AuditRecord, CustomerQueryPatternRecord, CustomerQueryRecord, CustomerResponseDraftRecord
from . import github_tools, repo_config

# Customer queries can't wait a week -- same cadence discipline as Sales. max() floor
# keeps a misconfigured tiny value from turning this into an accidental spam loop.
SWEEP_INTERVAL_SECONDS = max(300, int(os.getenv("VOLT_CUSTOMER_INTERVAL_SECONDS", "21600")))
MODEL = os.getenv("VOLT_CUSTOMER_MODEL") or llm_client.default_model()
# Triage is a binary classification (simple vs. sensitive), not prose generation -- the
# cheap tier is just as reliable at following the tool schema here, and it's the call
# site that runs most often (once per new query, before any draft is ever written).
MODEL_TRIAGE = os.getenv("VOLT_CUSTOMER_TRIAGE_MODEL") or llm_client.cheap_model()
MAX_TOKENS = 1024

_VOLTARISOS_SYSTEM_ID = "voltaris-os"
_NO_FACTS_TEXT = "[sem README/documentação disponível -- não é possível gerar resposta com factos confirmados]"
_UNCERTAIN_MARKER = "confirmar com o Francisco antes de responder"

# Deliberately broad and multilingual (PT/EN/NL, matching VoltarisOS's NL market) --
# a false positive here just means a human reviews an ordinary question one extra time;
# a false negative means a complaint or safety concern could get an automated draft,
# which the red line for this agent treats as unacceptable. Any single hit is enough to
# escalate, and this check runs BEFORE the model ever sees the query -- a keyword match
# skips the LLM call entirely, so no model behavior can downgrade it back to "simple".
SENSITIVE_SIGNALS: list[tuple[str, list[str]]] = [
    ("reclamação/queixa", ["reclama", "queixa", "complain", "klacht"]),
    ("pedido de reembolso/cancelamento", ["reembols", "refund", "cancelar", "cancelamento", "cancel", "opzeg", "terugbetal", "devolv"]),
    ("frustração/zanga visível", [
        "furios", "indignad", "revoltad", "angry", "furious", "frustrat", "péssimo", "pessimo",
        "terrível", "terrivel", "inaceitável", "inaceitavel", "vergonha", "absurdo", "!!!",
    ]),
    ("possível questão de segurança", [
        "segurança", "seguranca", "perigo", "perigoso", "choque", "incêndio", "incendio", "fogo",
        "avaria elétrica", "avaria eletrica", "cheiro a queimado", "fuga", "explos",
        "danger", "dangerous", "shock", "fire", "unsafe", "gevaar", "brand",
    ]),
]

SUBMIT_TRIAGE_TOOL_NAME = "submit_query_triage"
SUBMIT_TRIAGE_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_TRIAGE_TOOL_NAME,
    "description": "Classifica um pedido de cliente/parceiro. Chama isto exatamente uma vez.",
    "input_schema": {
        "type": "object",
        "properties": {
            "classification": {"type": "string", "enum": ["simple", "sensitive"]},
            "sensitive_reason": {"type": "string", "description": "Obrigatório se classification=sensitive: motivo curto (ex. reclamação, pedido de reembolso, frustração, segurança)."},
        },
        "required": ["classification"],
    },
}

SUBMIT_RESPONSE_TOOL_NAME = "submit_customer_response_draft"
SUBMIT_RESPONSE_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_RESPONSE_TOOL_NAME,
    "description": "Submete um rascunho de resposta a um cliente/parceiro. Chama isto exatamente uma vez.",
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "Assunto do email, curto e direto."},
            "body": {"type": "string", "description": "Corpo da resposta em português, profissional e simpático."},
        },
        "required": ["subject", "body"],
    },
}

_TRIAGE_SYSTEM_PROMPT = (
    "És o Agente de Customer do VOLT CORE, dedicado ao VoltarisOS. A tua única função "
    "aqui é classificar UM pedido de um cliente/parceiro já a bordo como 'simple' "
    "(pergunta direta sobre o produto, respondível com factos reais) ou 'sensitive' "
    "(reclamação, pedido de reembolso/cancelamento, frustração/zanga visível, ou "
    "qualquer menção a segurança -- mesmo indireta, ex. algo que pareça avaria "
    "elétrica ou risco físico). Na dúvida, classifica sempre como 'sensitive' -- o "
    "custo de escalar um pedido simples a mais é muito menor do que responder "
    "automaticamente a algo que precisava de atenção humana."
)

_DRAFT_SYSTEM_PROMPT = (
    "És o Agente de Customer do VOLT CORE, dedicado ao VoltarisOS. Escreves uma "
    "resposta a um cliente/parceiro já a bordo, respondendo à pergunta dele. REGRA "
    "ABSOLUTA: só podes usar factos sobre o produto que estejam literalmente no "
    "texto do README/documentação fornecido abaixo -- nunca inventes "
    "funcionalidades, nunca presumas. Se não tiveres a certeza sobre um detalhe, "
    f"marca-o explicitamente com a frase '{_UNCERTAIN_MARKER}' em vez de o "
    "apresentar como facto. Tom profissional e simpático, em português. Esta "
    "resposta nunca é enviada por ti -- fica sempre pendente de aprovação humana "
    "antes de qualquer envio real."
)


def _keyword_sensitive_reason(text: str) -> str | None:
    lowered = (text or "").lower()
    for reason, keywords in SENSITIVE_SIGNALS:
        if any(keyword in lowered for keyword in keywords):
            return reason
    return None


def _repo_target() -> tuple[str, str] | None:
    return repo_config.resolve_repo(_VOLTARISOS_SYSTEM_ID)


def _trivial_job(owner: str, repo: str) -> github_tools.CodeDiagnosisJob:
    # Only owner/repo are actually used by read_repo_file/list_repo_files -- the other
    # fields exist only because CodeDiagnosisJob was designed for the Dev/Debug
    # investigation flow, which this agent has no equivalent of.
    return github_tools.CodeDiagnosisJob(
        event_id=0, escalation_id=0, system=_VOLTARISOS_SYSTEM_ID, environment="production",
        priority="P4", owner=owner, repo=repo, parent_investigation_id=0,
    )


def _fetch_product_facts() -> tuple[str, list[str]]:
    target = _repo_target()
    if target is None:
        return _NO_FACTS_TEXT, []
    owner, repo = target
    job = _trivial_job(owner, repo)

    sources: list[str] = []
    parts: list[str] = []

    readme = github_tools.read_repo_file(job, "README.md")
    if "content" in readme:
        parts.append(f"### README.md\n{readme['content']}")
        sources.append("README.md")

    listing = github_tools.list_repo_files(job, "docs")
    if "files" in listing:
        for path in listing["files"][:2]:
            doc = github_tools.read_repo_file(job, path)
            if "content" in doc:
                parts.append(f"### {path}\n{doc['content']}")
                sources.append(path)

    if not parts:
        return _NO_FACTS_TEXT, []
    return "\n\n".join(parts), sources


def _call_model(system: str | list[dict], prompt: str, tool_schema: dict, tool_name: str, *, model: str) -> Any:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    client = llm_client.get_client()
    return client.call(
        model=model,
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


def _triage_new_queries() -> None:
    with session_scope() as session:
        new_ids = session.scalars(select(CustomerQueryRecord.id).where(CustomerQueryRecord.status == "new")).all()

    for query_id in new_ids:
        try:
            with session_scope() as session:
                query = session.get(CustomerQueryRecord, query_id)
                if query is None or query.status != "new":
                    continue

                keyword_reason = _keyword_sensitive_reason(query.question)
                if keyword_reason is not None:
                    query.classification = "sensitive"
                    query.sensitive_reason = keyword_reason
                    query.status = "sensitive_escalated"
                    query.triaged_at = datetime.now(timezone.utc)
                    session.add(AuditRecord(type="customer_query_escalated", reference_id=str(query_id), detail=f"keyword: {keyword_reason}"))
                    continue

                prompt = f"Pedido do cliente/parceiro:\n{query.question}"
                response = _call_model(_TRIAGE_SYSTEM_PROMPT, prompt, SUBMIT_TRIAGE_TOOL_SCHEMA, SUBMIT_TRIAGE_TOOL_NAME, model=MODEL_TRIAGE)
                submitted = _extract_tool_input(response, SUBMIT_TRIAGE_TOOL_NAME)

                if submitted is None:
                    # Fail-safe: a triage that couldn't complete is never left silently
                    # un-reviewed -- it escalates, the same as a real sensitive case.
                    query.classification = "sensitive"
                    query.sensitive_reason = "triagem falhou -- rever manualmente"
                    query.status = "sensitive_escalated"
                    query.triaged_at = datetime.now(timezone.utc)
                    session.add(AuditRecord(type="customer_query_triage_failed", reference_id=str(query_id), detail=f"model stopped ({response.stop_reason}) without submitting"))
                    continue

                classification = str(submitted.get("classification") or "sensitive")
                if classification != "simple":
                    # Anything other than an explicit "simple" (including an unexpected
                    # value) is treated as sensitive -- fail-safe, never fail-open.
                    query.classification = "sensitive"
                    query.sensitive_reason = str(submitted.get("sensitive_reason") or "sinalizado pelo agente")
                    query.status = "sensitive_escalated"
                    session.add(AuditRecord(type="customer_query_escalated", reference_id=str(query_id), detail="model classification"))
                else:
                    query.classification = "simple"
                    query.status = "simple"
                    session.add(AuditRecord(type="customer_query_triaged", reference_id=str(query_id), detail="simple"))
                query.triaged_at = datetime.now(timezone.utc)
        except Exception as exc:
            # One query's failure must never abort triage of the rest.
            with session_scope() as session:
                session.add(AuditRecord(type="customer_query_triage_failed", reference_id=str(query_id), detail=str(exc)[:500]))


def _generate_pending_response_drafts() -> None:
    with session_scope() as session:
        drafted_query_ids = {row for row in session.scalars(select(CustomerResponseDraftRecord.query_id)).all()}
        candidate_ids = session.scalars(select(CustomerQueryRecord.id).where(CustomerQueryRecord.status == "simple")).all()
        pending_ids = [query_id for query_id in candidate_ids if query_id not in drafted_query_ids]

    if not pending_ids:
        return

    facts_text, sources = _fetch_product_facts()
    # facts_text (README + docs, up to tens of thousands of tokens) is identical for
    # every pending query in this loop -- previously it was re-embedded in the user
    # prompt and re-billed in full on every single call. Moving it into a cached system
    # block means only the FIRST call in a sweep pays full price for it; every
    # subsequent call within the cache's ~5min window reads it back at a fraction of
    # the cost. The per-query part (the actual question) stays in the user message,
    # which is what varies and must never be cached.
    draft_system: str | list[dict] = [
        {"type": "text", "text": _DRAFT_SYSTEM_PROMPT},
        {
            "type": "text",
            "text": f"Factos reais sobre o VoltarisOS (README/documentação):\n{facts_text}",
            "cache_control": {"type": "ephemeral"},
        },
    ]

    for query_id in pending_ids:
        try:
            with session_scope() as session:
                query = session.get(CustomerQueryRecord, query_id)
                if query is None or query.status != "simple":
                    continue
                prompt = f"Pedido do cliente/parceiro:\n{query.question}"
                response = _call_model(draft_system, prompt, SUBMIT_RESPONSE_TOOL_SCHEMA, SUBMIT_RESPONSE_TOOL_NAME, model=MODEL)
                submitted = _extract_tool_input(response, SUBMIT_RESPONSE_TOOL_NAME)
                if submitted is None:
                    session.add(AuditRecord(type="customer_response_draft_failed", reference_id=str(query_id), detail=f"model stopped ({response.stop_reason}) without submitting"))
                    continue
                session.add(CustomerResponseDraftRecord(
                    query_id=query_id,
                    subject=str(submitted.get("subject") or ""),
                    body=str(submitted.get("body") or ""),
                    status="pending_approval",
                    model=MODEL,
                ))
                session.add(AuditRecord(type="customer_response_draft_created", reference_id=str(query_id), detail=f"sources={','.join(sources) if sources else 'none'}"))
        except Exception as exc:
            # One draft's failure must never abort the rest.
            with session_scope() as session:
                session.add(AuditRecord(type="customer_response_draft_failed", reference_id=str(query_id), detail=str(exc)[:500]))


def _normalize_question(text: str) -> str:
    lowered = (text or "").strip().lower()
    stripped = re.sub(r"[^\w\s]", "", lowered)
    return re.sub(r"\s+", " ", stripped).strip()[:500]


def _detect_repeated_patterns() -> None:
    # Literal repeat detection after light normalization -- never a similarity score or
    # any invented metric, just "this near-identical question has been asked N times".
    with session_scope() as session:
        rows = session.scalars(select(CustomerQueryRecord)).all()
        groups: dict[str, list[CustomerQueryRecord]] = {}
        for row in rows:
            key = _normalize_question(row.question)
            if not key:
                continue
            groups.setdefault(key, []).append(row)

        existing = {row.normalized_question: row for row in session.scalars(select(CustomerQueryPatternRecord)).all()}
        for key, matches in groups.items():
            if len(matches) < 2:
                continue
            pattern = existing.get(key)
            if pattern is None:
                pattern = CustomerQueryPatternRecord(normalized_question=key, example_question=matches[0].question)
                session.add(pattern)
            pattern.occurrence_count = len(matches)
            pattern.last_seen_at = datetime.now(timezone.utc)


def run_customer_sweep() -> None:
    try:
        _triage_new_queries()
        _generate_pending_response_drafts()
        _detect_repeated_patterns()
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="customer_sweep_failed", detail=f"{type(exc).__name__}: {str(exc)[:500]}"))


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
                run_customer_sweep()
        except Exception as exc:
            print(f"[volt-core-customer] sweep failure: {type(exc).__name__}: {exc}")
        finally:
            _sweep_in_progress = False
        time.sleep(SWEEP_INTERVAL_SECONDS)


def start_customer_agent() -> None:
    global _started
    if _started or not llm_client.is_configured():
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_sweep_loop, name="volt-core-customer", daemon=True).start()
        _started = True
