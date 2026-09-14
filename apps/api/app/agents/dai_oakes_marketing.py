from __future__ import annotations

import html
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select

from .. import llm_client
from ..db import session_scope
from ..models import AuditRecord, DaiOakesMarketingContentRecord

# Content isn't urgent -- weekly cadence, same posture as VoltarisOS's marketing_agent.py.
# max() floor keeps a misconfigured tiny value from turning this into an accidental spam
# loop, same discipline as every other periodic agent in this codebase.
SWEEP_INTERVAL_SECONDS = max(3600, int(os.getenv("VOLT_DAIOAKES_MARKETING_INTERVAL_SECONDS", "604800")))
MODEL = os.getenv("VOLT_DAIOAKES_MARKETING_MODEL") or llm_client.default_model()
MAX_TOKENS = 2048

# The clinic's own real public website -- no authentication, no patient data anywhere on
# this path. This is the ONLY fact source this agent is allowed to use; see
# _fetch_dai_oakes_facts(). Confirmed with the user 2026-09-14.
_DAIOAKES_PUBLIC_SITE_URL = os.getenv("DAIOAKES_PUBLIC_SITE_URL", "https://www.daianeoakes.com")
_NO_FACTS_TEXT = "[sem factos confirmados sobre a Dai Oakes disponíveis -- não é possível gerar conteúdo]"
_UNCERTAIN_MARKER = "confirmar com a clínica antes de publicar"

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESCRIPTION_RE = re.compile(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', re.IGNORECASE)
_OG_TITLE_RE = re.compile(r'<meta\s+property=["\']og:title["\']\s+content=["\'](.*?)["\']', re.IGNORECASE)
_OG_DESCRIPTION_RE = re.compile(r'<meta\s+property=["\']og:description["\']\s+content=["\'](.*?)["\']', re.IGNORECASE)

SUBMIT_CONTENT_TOOL_NAME = "submit_dai_oakes_marketing_content"
SUBMIT_CONTENT_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_CONTENT_TOOL_NAME,
    "description": "Submete um rascunho de conteúdo de marketing para a Dai Oakes. Chama isto exatamente uma vez.",
    "input_schema": {
        "type": "object",
        "properties": {
            "format": {"type": "string", "enum": ["instagram_post", "facebook_post", "blog_post"]},
            "title": {"type": "string", "description": "Título ou primeira linha, curto e direto."},
            "body": {"type": "string", "description": "Corpo completo do conteúdo, em português."},
        },
        "required": ["format", "title", "body"],
    },
}

_CONTENT_SYSTEM_PROMPT = (
    "És o Agente de Marketing da Dai Oakes, uma clínica de fisioterapia especializada em "
    "saúde da mulher (diástase abdominal, pavimento pélvico, recuperação pós-parto, dor "
    "lombar e reabilitação do core) em Roterdão. Escreves conteúdo para os canais "
    "públicos da clínica (Instagram, Facebook, blog). REGRA ABSOLUTA: só podes usar "
    "factos que estejam literalmente no texto fornecido abaixo (retirado do site "
    "público da clínica) -- nunca inventes preços, horários, planos de tratamento, "
    "resultados clínicos, ou qualquer outro detalhe não confirmado. Se não tiveres a "
    f"certeza sobre um detalhe, marca-o explicitamente com a frase '{_UNCERTAIN_MARKER}' "
    "em vez de o apresentar como facto. Nunca menciones nem inventes nomes ou casos de "
    "pacientes reais ou fictícios. Tom profissional, acolhedor, em português. Este "
    "rascunho nunca é publicado por ti -- fica sempre pendente de aprovação humana."
)


def _unescape(text: str) -> str:
    return html.unescape(text).strip()


def _fetch_dai_oakes_facts() -> tuple[str, list[str]]:
    # The only network call this agent ever makes: a GET to the clinic's own public,
    # unauthenticated website -- no API key, no patient data, nothing Dai-Oakes-admin-
    # panel-shaped anywhere on this path. Fails closed (never raises) same as every
    # other external fetch in this codebase.
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            response = client.get(_DAIOAKES_PUBLIC_SITE_URL)
    except httpx.HTTPError:
        return _NO_FACTS_TEXT, []
    if response.status_code != 200:
        return _NO_FACTS_TEXT, []

    page = response.text
    parts: list[str] = []
    sources: list[str] = []

    title_match = _TITLE_RE.search(page)
    title_text = _unescape(title_match.group(1)) if title_match else None
    if title_text:
        parts.append(f"Título do site: {title_text}")
        sources.append("title")

    desc_match = _META_DESCRIPTION_RE.search(page)
    desc_text = _unescape(desc_match.group(1)) if desc_match else None
    if desc_text:
        parts.append(f"Descrição do site: {desc_text}")
        sources.append("meta description")

    og_title_match = _OG_TITLE_RE.search(page)
    og_title_text = _unescape(og_title_match.group(1)) if og_title_match else None
    if og_title_text and og_title_text != title_text:
        parts.append(f"Título (redes sociais): {og_title_text}")
        sources.append("og:title")

    og_desc_match = _OG_DESCRIPTION_RE.search(page)
    og_desc_text = _unescape(og_desc_match.group(1)) if og_desc_match else None
    if og_desc_text and og_desc_text != desc_text:
        parts.append(f"Descrição (redes sociais): {og_desc_text}")
        sources.append("og:description")

    if not parts:
        return _NO_FACTS_TEXT, []
    return "\n".join(parts), sources


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
        pending_exists = session.scalar(
            select(DaiOakesMarketingContentRecord.id).where(DaiOakesMarketingContentRecord.status == "pending_approval")
        ) is not None
    if pending_exists:
        return  # don't pile up unreviewed drafts -- one at a time is enough

    try:
        facts_text, sources = _fetch_dai_oakes_facts()
        prompt = (
            f"Factos reais sobre a Dai Oakes (site público):\n{facts_text}\n\n"
            "Escreve uma peça de conteúdo (post Instagram/Facebook, ou blog) para os "
            "canais públicos da clínica, com base nos factos acima."
        )
        response = _call_model(_CONTENT_SYSTEM_PROMPT, prompt, SUBMIT_CONTENT_TOOL_SCHEMA, SUBMIT_CONTENT_TOOL_NAME)
        submitted = _extract_tool_input(response, SUBMIT_CONTENT_TOOL_NAME)
        with session_scope() as session:
            if submitted is None:
                session.add(AuditRecord(type="dai_oakes_marketing_content_failed", detail=f"model stopped ({response.stop_reason}) without submitting"))
                return
            session.add(DaiOakesMarketingContentRecord(
                format=str(submitted.get("format") or "instagram_post"),
                title=str(submitted.get("title") or ""),
                body=str(submitted.get("body") or ""),
                source_facts=", ".join(sources) if sources else "(sem fonte -- ver corpo do texto)",
                status="pending_approval",
                model=MODEL,
            ))
            session.add(AuditRecord(type="dai_oakes_marketing_content_created", detail="status=pending_approval"))
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="dai_oakes_marketing_content_failed", detail=str(exc)[:500]))


def run_marketing_sweep() -> None:
    try:
        run_generate_content()
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="dai_oakes_marketing_sweep_failed", detail=f"{type(exc).__name__}: {str(exc)[:500]}"))


_started = False
_lock = threading.Lock()
_sweep_in_progress = False


def is_sweep_in_progress() -> bool:
    return _sweep_in_progress


def _seconds_until_sweep_due() -> float:
    # A restart/redeploy must never trigger an extra paid LLM call just because the
    # process happened to restart (the exact bug that took production down for three
    # days on 2026-09-10-13 -- see market_intelligence.py's twin of this function for
    # the full story). Anchored on the most recent content row of ANY status: combined
    # with run_generate_content()'s own pending-draft guard above, a redeploy right
    # after a human approves a draft still won't generate a new one before the interval
    # is actually up.
    with session_scope() as session:
        latest = session.scalar(select(DaiOakesMarketingContentRecord).order_by(DaiOakesMarketingContentRecord.id.desc()))
        created_at = latest.created_at if latest is not None else None
    if created_at is None:
        return 0.0
    if created_at.tzinfo is None:
        # sqlite (all local/CI testing) doesn't round-trip tzinfo on DateTime(timezone=
        # True) columns the way Postgres does.
        created_at = created_at.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - created_at).total_seconds()
    return max(0.0, SWEEP_INTERVAL_SECONDS - elapsed)


def _sweep_loop() -> None:
    global _sweep_in_progress
    while True:
        pending = _seconds_until_sweep_due()
        if pending > 0:
            time.sleep(pending)
        try:
            _sweep_in_progress = True
            if llm_client.is_configured():
                run_marketing_sweep()
        except Exception as exc:
            print(f"[volt-core-dai-oakes-marketing] sweep failure: {type(exc).__name__}: {exc}")
        finally:
            _sweep_in_progress = False
        time.sleep(SWEEP_INTERVAL_SECONDS)


def start_dai_oakes_marketing() -> None:
    global _started
    if _started or not llm_client.is_configured():
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_sweep_loop, name="volt-core-dai-oakes-marketing", daemon=True).start()
        _started = True
