from __future__ import annotations

import os
import threading
import time
from typing import Any

from sqlalchemy import select

from .. import llm_client
from ..db import session_scope
from ..models import AuditRecord, MarketingContentRecord
from . import github_tools, repo_config

# Content isn't urgent the way leads/deals are -- same weekly cadence as Market
# Intelligence. max() floor keeps a misconfigured tiny value from turning this into an
# accidental spam loop, same discipline as every other periodic agent in this codebase.
SWEEP_INTERVAL_SECONDS = max(3600, int(os.getenv("VOLT_MARKETING_INTERVAL_SECONDS", "604800")))
MODEL = os.getenv("VOLT_MARKETING_MODEL") or llm_client.default_model()
MAX_TOKENS = 2048

_VOLTARISOS_SYSTEM_ID = "voltaris-os"
_NO_FACTS_TEXT = "[sem README/documentação disponível -- não é possível gerar conteúdo com factos confirmados]"
_UNCERTAIN_MARKER = "confirmar com o Francisco antes de publicar"

SUBMIT_CONTENT_TOOL_NAME = "submit_marketing_content"
SUBMIT_CONTENT_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_CONTENT_TOOL_NAME,
    "description": "Submete um rascunho de conteúdo de marketing (blog post). Chama isto exatamente uma vez.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Título do post."},
            "body": {"type": "string", "description": "Corpo completo do post em português."},
            "audience": {"type": "string", "enum": ["consumer", "b2b_partner", "both"]},
        },
        "required": ["title", "body", "audience"],
    },
}

SUBMIT_REPURPOSE_TOOL_NAME = "submit_repurposed_variants"
SUBMIT_REPURPOSE_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_REPURPOSE_TOOL_NAME,
    "description": "Submete 2-3 variantes curtas de uma peça de conteúdo já existente, para diferentes formatos. Chama isto exatamente uma vez.",
    "input_schema": {
        "type": "object",
        "properties": {
            "variants": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "format": {"type": "string", "enum": ["linkedin_post", "twitter_post", "instagram_carousel"]},
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                    },
                    "required": ["format", "title", "body"],
                },
                "minItems": 2,
                "maxItems": 3,
            },
        },
        "required": ["variants"],
    },
}

_CONTENT_SYSTEM_PROMPT = (
    "És o Agente de Marketing do VOLT CORE, dedicado ao VoltarisOS. Escreves conteúdo "
    "de marketing (posts de blog) sobre o VoltarisOS. REGRA ABSOLUTA: só podes usar "
    "factos sobre o produto que estejam literalmente no texto do README/documentação "
    "fornecido abaixo -- nunca inventes funcionalidades, nunca uses o que a "
    "Inteligência de Mercado descobriu sobre concorrentes, nunca presumas. Se não "
    "tiveres a certeza sobre um detalhe (ex. um preço, uma funcionalidade específica), "
    f"marca-o explicitamente com a frase '{_UNCERTAIN_MARKER}' em vez de o apresentar "
    "como facto. Este rascunho nunca é publicado por ti -- fica sempre pendente de "
    "aprovação humana."
)

_REPURPOSE_SYSTEM_PROMPT = (
    "És o Agente de Marketing do VOLT CORE. Recebes uma peça de conteúdo já escrita e "
    "tens de a reescrever em 2-3 formatos mais curtos (LinkedIn, Twitter/X, carrossel "
    "Instagram), mantendo exatamente os mesmos factos -- nunca acrescentes nem "
    "inventes nada que não esteja já na peça original. Cada variante deve bater certo "
    "com a mensagem original, só adaptada ao formato."
)


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


def run_generate_content() -> None:
    with session_scope() as session:
        pending_blog_exists = session.scalar(
            select(MarketingContentRecord.id).where(
                MarketingContentRecord.content_type == "blog_post", MarketingContentRecord.status == "pending_approval",
            )
        ) is not None
    if pending_blog_exists:
        return  # don't pile up unreviewed drafts -- one at a time is enough

    try:
        facts_text, sources = _fetch_product_facts()
        prompt = (
            f"Factos reais sobre o VoltarisOS (README/documentação):\n{facts_text}\n\n"
            "Escreve um post de blog sobre o VoltarisOS, dirigido a donos de casa "
            "com solar (audience=consumer) ou a parceiros B2B (instaladoras/"
            "consultoras, audience=b2b_partner), consoante o que os factos acima "
            "sugerirem ser mais relevante."
        )
        response = _call_model(_CONTENT_SYSTEM_PROMPT, prompt, SUBMIT_CONTENT_TOOL_SCHEMA, SUBMIT_CONTENT_TOOL_NAME)
        submitted = _extract_tool_input(response, SUBMIT_CONTENT_TOOL_NAME)
        with session_scope() as session:
            if submitted is None:
                session.add(AuditRecord(type="marketing_content_failed", detail=f"model stopped ({response.stop_reason}) without submitting"))
                return
            session.add(MarketingContentRecord(
                content_type="blog_post",
                format="blog",
                audience=str(submitted.get("audience") or "both"),
                title=str(submitted.get("title") or ""),
                body=str(submitted.get("body") or ""),
                source_facts=", ".join(sources) if sources else "(sem fonte -- ver corpo do texto)",
                status="pending_approval",
                model=MODEL,
            ))
            session.add(AuditRecord(type="marketing_content_created", detail="status=pending_approval"))
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="marketing_content_failed", detail=str(exc)[:500]))


def run_repurpose_content(content_id: int) -> None:
    try:
        with session_scope() as session:
            original = session.get(MarketingContentRecord, content_id)
            if original is None:
                return
            prompt = (
                f"Peça original (título: {original.title}):\n{original.body}\n\n"
                f"Audiência: {original.audience}"
            )
            response = _call_model(_REPURPOSE_SYSTEM_PROMPT, prompt, SUBMIT_REPURPOSE_TOOL_SCHEMA, SUBMIT_REPURPOSE_TOOL_NAME)
            submitted = _extract_tool_input(response, SUBMIT_REPURPOSE_TOOL_NAME)
            if submitted is None:
                session.add(AuditRecord(type="marketing_repurpose_failed", reference_id=str(content_id), detail=f"model stopped ({response.stop_reason}) without submitting"))
                return
            variants = submitted.get("variants") or []
            for variant in variants:
                session.add(MarketingContentRecord(
                    content_type="social_post",
                    format=str(variant.get("format") or ""),
                    audience=original.audience,
                    parent_content_id=content_id,
                    title=str(variant.get("title") or ""),
                    body=str(variant.get("body") or ""),
                    source_facts=f"repurposed from content #{content_id}",
                    status="pending_approval",
                    model=MODEL,
                ))
            session.add(AuditRecord(type="marketing_repurpose_created", reference_id=str(content_id), detail=f"{len(variants)} variants"))
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="marketing_repurpose_failed", reference_id=str(content_id), detail=str(exc)[:500]))


def run_marketing_sweep() -> None:
    try:
        run_generate_content()
        with session_scope() as session:
            blog_ids = session.scalars(select(MarketingContentRecord.id).where(MarketingContentRecord.content_type == "blog_post")).all()
            repurposed_parent_ids = {row for row in session.scalars(select(MarketingContentRecord.parent_content_id).where(MarketingContentRecord.parent_content_id.is_not(None))).all()}
            needs_repurposing = [blog_id for blog_id in blog_ids if blog_id not in repurposed_parent_ids]
        for blog_id in needs_repurposing:
            run_repurpose_content(blog_id)
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="marketing_sweep_failed", detail=f"{type(exc).__name__}: {str(exc)[:500]}"))


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
                run_marketing_sweep()
        except Exception as exc:
            print(f"[volt-core-marketing] sweep failure: {type(exc).__name__}: {exc}")
        finally:
            _sweep_in_progress = False
        time.sleep(SWEEP_INTERVAL_SECONDS)


def start_marketing_agent() -> None:
    global _started
    if _started or not llm_client.is_configured():
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_sweep_loop, name="volt-core-marketing", daemon=True).start()
        _started = True
