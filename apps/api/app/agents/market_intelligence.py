from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from statistics import fmean
from typing import Any

import httpx

from .. import llm_client
from ..db import session_scope
from ..models import AuditRecord, MarketIntelligenceReportRecord
from ..telegram import send_telegram_message
from . import entsoe_client

# Weekly by default (7 days) -- not a continuous alert loop like the Production Monitor,
# this is a low-priority digest. max() floor keeps a misconfigured tiny value from
# turning this into an accidental spam loop.
SWEEP_INTERVAL_SECONDS = max(3600, int(os.getenv("VOLT_MARKET_INTEL_INTERVAL_SECONDS", "604800")))
MODEL = os.getenv("VOLT_MARKET_INTEL_MODEL") or llm_client.default_model()
MAX_TOKENS = 2048
MAX_SOURCE_CHARS = 4000

_DEFAULT_COMPETITORS = ["Sympower", "Next Kraftwerke", "Tibber (Grid Rewards)", "Sessy"]

# Small, fixed set of official/known sources -- deliberately not an open web search (none
# exists in volt-core): direct fetches only, same discipline as github_tools' direct API
# calls. Kept short and named so the list is easy to review/extend later.
_REGULATION_SOURCES = [
    ("Rijksoverheid -- salderingsregeling", "https://www.rijksoverheid.nl/onderwerpen/duurzame-energie/salderingsregeling"),
    ("RVO -- ISDE", "https://www.rvo.nl/subsidies-financiering/isde"),
    ("RVO -- SDE++", "https://www.rvo.nl/subsidies-financiering/sde"),
]
_INDUSTRY_NEWS_SOURCES = [
    ("Solar Magazine NL", "https://www.solarmagazine.nl/feed"),
    ("PV Magazine (EU/international)", "https://www.pv-magazine.com/feed/"),
]

_NO_NEWS_TEXT = "sem novidades esta semana"

SUBMIT_TOOL_NAME = "submit_market_intelligence_summary"
SUBMIT_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_TOOL_NAME,
    "description": "Submete o resumo semanal de inteligência de mercado, dividido pelas 4 áreas. Chama isto exatamente uma vez.",
    "input_schema": {
        "type": "object",
        "properties": {
            "competitors_summary": {"type": "string", "description": f"Resumo de concorrência, ou literalmente '{_NO_NEWS_TEXT}' se não houver nada de novo e confiável."},
            "regulation_summary": {"type": "string", "description": f"Resumo de mudanças regulatórias holandesas, ou literalmente '{_NO_NEWS_TEXT}'."},
            "price_signals_summary": {"type": "string", "description": f"Resumo de tendências/anomalias nos preços ENTSO-E, ou literalmente '{_NO_NEWS_TEXT}'."},
            "industry_news_summary": {"type": "string", "description": f"Resumo de notícias do setor, ou literalmente '{_NO_NEWS_TEXT}'."},
        },
        "required": ["competitors_summary", "regulation_summary", "price_signals_summary", "industry_news_summary"],
    },
}

SYSTEM_PROMPT = (
    "És o Agente de Inteligência de Mercado do VOLT CORE, dedicado ao VoltarisOS "
    "(plataforma de gestão energética doméstica para donos de solar/bateria/EV na "
    "Holanda). És puramente informativo -- nunca executas nada, nunca contactas "
    "ninguém, nunca publicas nada. A tua única saída é um resumo semanal em "
    "português, direto, dividido em 4 áreas fixas. Nunca inventes dados: se não "
    "tiveres informação genuína e fiável para uma área nesta semana, escreve "
    f"literalmente '{_NO_NEWS_TEXT}' nessa área em vez de forçar conteúdo. Os "
    "dados de preços e as fontes de regulação/notícias fornecidos abaixo já foram "
    "recolhidos por outro processo -- baseia-te neles, não presumas dados "
    "adicionais que não estejam no prompt."
)


def _competitors() -> list[str]:
    raw = os.getenv("VOLT_MARKET_COMPETITORS", "").strip()
    if not raw:
        return list(_DEFAULT_COMPETITORS)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return list(_DEFAULT_COMPETITORS)
    if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
        return list(_DEFAULT_COMPETITORS)
    return payload or list(_DEFAULT_COMPETITORS)


def _strip_html(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", without_tags).strip()


def _fetch_source(url: str) -> str:
    # The seam this module's tests substitute via httpx monkeypatching -- returns a
    # short "[error] ..." string rather than raising, so one dead source never aborts
    # the sweep. Matches the "never crash the whole run over one bad call" posture used
    # by every other agent tool in this codebase.
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            response = client.get(url)
        if response.status_code != 200:
            return f"[error] HTTP {response.status_code}"
        return _strip_html(response.text)[:MAX_SOURCE_CHARS]
    except httpx.HTTPError as exc:
        return f"[error] {type(exc).__name__}: {exc}"


def _gather_regulation_text() -> str:
    parts = []
    for label, url in _REGULATION_SOURCES:
        parts.append(f"### {label} ({url})\n{_fetch_source(url)}")
    return "\n\n".join(parts)


def _gather_industry_news_text() -> str:
    parts = []
    for label, url in _INDUSTRY_NEWS_SOURCES:
        parts.append(f"### {label} ({url})\n{_fetch_source(url)}")
    return "\n\n".join(parts)


def _gather_price_signals_text() -> str:
    result = entsoe_client.fetch_entsoe_day_ahead_prices(days=7)
    if "error" in result:
        return f"[dados de preços ENTSO-E indisponíveis: {result['error']}]"
    prices = result.get("prices") or []
    if not prices:
        return "[nenhum ponto de preço devolvido pela ENTSO-E para os últimos 7 dias]"

    by_day: dict[str, list[float]] = {}
    for point in prices:
        day = point["start"][:10]
        by_day.setdefault(day, []).append(point["price_eur_mwh"])

    all_values = [point["price_eur_mwh"] for point in prices]
    lines = [
        f"Preços day-ahead ENTSO-E (zona NL), últimos 7 dias -- "
        f"média geral: {fmean(all_values):.1f} EUR/MWh, mínimo: {min(all_values):.1f}, máximo: {max(all_values):.1f}",
    ]
    for day in sorted(by_day):
        values = by_day[day]
        lines.append(f"{day}: média {fmean(values):.1f} EUR/MWh (mín {min(values):.1f}, máx {max(values):.1f}, {len(values)} pontos)")
    return "\n".join(lines)


def _build_prompt(competitors: list[str], regulation_text: str, price_signals_text: str, industry_news_text: str) -> str:
    return (
        "Produz o resumo semanal de inteligência de mercado para o VoltarisOS.\n\n"
        f"## Concorrentes a acompanhar\n{', '.join(competitors)}\n"
        "(Resume apenas mudanças recentes de que tenhas conhecimento genuíno e fiável "
        f"sobre estes concorrentes específicos; caso contrário usa '{_NO_NEWS_TEXT}'.)\n\n"
        f"## Fontes de regulação holandesa (texto bruto recolhido)\n{regulation_text}\n\n"
        f"## Sinais de preço ENTSO-E\n{price_signals_text}\n\n"
        f"## Fontes de notícias do setor (texto bruto recolhido)\n{industry_news_text}\n"
    )


def _call_model(client: llm_client.LLMClient, prompt: str) -> Any:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    return client.call(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[SUBMIT_TOOL_SCHEMA],
        tool_choice=SUBMIT_TOOL_NAME,
        messages=[{"role": "user", "content": prompt}],
    )


def _format_telegram_message(record_fields: dict[str, str]) -> str:
    return (
        "INTELIGÊNCIA DE MERCADO -- resumo semanal\n\n"
        f"Concorrência:\n{record_fields['competitors_summary']}\n\n"
        f"Regulação:\n{record_fields['regulation_summary']}\n\n"
        f"Sinais de preço:\n{record_fields['price_signals_summary']}\n\n"
        f"Notícias do setor:\n{record_fields['industry_news_summary']}"
    )


def run_weekly_intelligence_sweep() -> None:
    try:
        client = llm_client.get_client()  # inside the try so a missing-provider
        # LLMConfigError degrades to a normal _persist_failure, same as every other
        # agent entrypoint in this codebase.
        competitors = _competitors()
        regulation_text = _gather_regulation_text()
        price_signals_text = _gather_price_signals_text()
        industry_news_text = _gather_industry_news_text()

        prompt = _build_prompt(competitors, regulation_text, price_signals_text, industry_news_text)
        response = _call_model(client, prompt)

        submitted = None
        for block in response.content:
            if block.get("type") == "tool_use" and block["name"] == SUBMIT_TOOL_NAME:
                submitted = block["input"]
                break

        if submitted is None:
            _persist_failure(reason=f"model stopped ({response.stop_reason}) without submitting a summary")
            return

        _persist_success(submitted, response)
    except Exception as exc:
        _persist_failure(reason=f"{type(exc).__name__}: {str(exc)[:500]}")


def _persist_success(submitted: dict[str, Any], response: Any) -> None:
    telegram_sent = False
    try:
        telegram_sent = send_telegram_message(_format_telegram_message(submitted))
    except Exception:
        telegram_sent = False  # Telegram failure never undoes the report already
        # about to be persisted -- matches notify_telegram_channel's isolated try/except.

    with session_scope() as session:
        session.add(
            MarketIntelligenceReportRecord(
                status="completed",
                competitors_summary=str(submitted.get("competitors_summary") or ""),
                regulation_summary=str(submitted.get("regulation_summary") or ""),
                price_signals_summary=str(submitted.get("price_signals_summary") or ""),
                industry_news_summary=str(submitted.get("industry_news_summary") or ""),
                model=MODEL,
                turns_used=1,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                telegram_sent=telegram_sent,
                completed_at=datetime.now(timezone.utc),
            )
        )
        session.add(AuditRecord(type="market_intelligence_report_completed", detail=f"telegram_sent={telegram_sent}"))


def _persist_failure(reason: str) -> None:
    with session_scope() as session:
        session.add(
            MarketIntelligenceReportRecord(
                status="failed",
                model=MODEL,
                telegram_sent=False,
                error=reason[:2000],
                completed_at=datetime.now(timezone.utc),
            )
        )
        session.add(AuditRecord(type="market_intelligence_report_failed", detail=reason[:500]))


def run_sweep() -> None:
    if not llm_client.is_configured():
        return
    run_weekly_intelligence_sweep()


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
            run_sweep()
        except Exception as exc:
            print(f"[volt-core-market-intel] sweep failure: {type(exc).__name__}: {exc}")
        finally:
            _sweep_in_progress = False
        time.sleep(SWEEP_INTERVAL_SECONDS)


def start_market_intelligence() -> None:
    global _started
    if _started or not llm_client.is_configured():
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_sweep_loop, name="volt-core-market-intelligence", daemon=True).start()
        _started = True
