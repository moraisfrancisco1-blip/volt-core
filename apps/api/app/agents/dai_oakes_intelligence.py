from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from .. import llm_client
from ..db import session_scope
from ..models import (
    AuditRecord,
    DaiOakesBookingsSnapshotRecord,
    DaiOakesClientsSnapshotRecord,
    DaiOakesIntelligenceReportRecord,
    DaiOakesPaymentRecord,
    DaiOakesSystemHealthSnapshotRecord,
)
from ..telegram import send_telegram_message

# Weekly by default (7 days) -- same low-priority-digest posture as market_intelligence.py,
# not a continuous alert loop. max() floor guards against a misconfigured tiny value turning
# this into an accidental spam loop.
SWEEP_INTERVAL_SECONDS = max(3600, int(os.getenv("VOLT_DAIOAKES_INTEL_INTERVAL_SECONDS", "604800")))
MODEL = os.getenv("VOLT_DAIOAKES_INTEL_MODEL") or llm_client.default_model()
MAX_TOKENS = 1536

_NO_DATA_TEXT = "sem dados disponíveis esta semana"
_NO_ALERTS_TEXT = "sem novidades esta semana"

SUBMIT_TOOL_NAME = "submit_dai_oakes_intelligence_summary"
SUBMIT_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_TOOL_NAME,
    "description": "Submete o resumo semanal de inteligência da Dai Oakes, dividido por 5 áreas. Chama isto exatamente uma vez.",
    "input_schema": {
        "type": "object",
        "properties": {
            "payments_summary": {"type": "string", "description": f"Resumo do estado dos pagamentos/faturas por estado, ou literalmente '{_NO_DATA_TEXT}' se não houver dados."},
            "bookings_summary": {"type": "string", "description": f"Resumo do volume e distribuição de marcações, ou literalmente '{_NO_DATA_TEXT}'."},
            "clients_summary": {"type": "string", "description": f"Resumo do total de clientes e crescimento recente, ou literalmente '{_NO_DATA_TEXT}'."},
            "system_health_summary": {"type": "string", "description": f"Resumo da saúde operacional do painel (webhooks/emails/mensagens/logins), ou literalmente '{_NO_DATA_TEXT}'."},
            "alerts_summary": {"type": "string", "description": f"Só sinaliza aqui o que sair claramente do normal (ex.: faturas atrasadas a acumular, falhas de sistema a subir, picos de rate-limit de login). Se nada for invulgar, escreve literalmente '{_NO_ALERTS_TEXT}'."},
        },
        "required": ["payments_summary", "bookings_summary", "clients_summary", "system_health_summary", "alerts_summary"],
    },
}

SYSTEM_PROMPT = (
    "És o Agente de Inteligência Dai Oakes do VOLT CORE, dedicado à Studio Dai Oakes "
    "(clínica de fisioterapia -- um negócio completamente separado da VoltarisOS). És "
    "puramente informativo -- nunca escreves nada no painel da Dai Oakes, nunca contactas "
    "clientes, nunca publicas nada, e nunca tens acesso direto à API da Dai Oakes: só lês "
    "os agregados (sem PII) que o agente Back Office já sincronizou para a base de dados "
    "do próprio Volt Core. Nunca inventes números -- baseia-te exclusivamente nos dados "
    "fornecidos abaixo; se um bloco de dados estiver vazio, escreve o texto de fallback "
    "indicado em vez de presumir. A tua saída é um resumo semanal em português, direto, "
    "dividido em 5 áreas fixas. Só preenches 'alertas' quando algo estiver genuinamente "
    "fora do normal -- não repitas aí os números normais."
)


def _fmt_dt(value: datetime | None) -> str:
    return value.isoformat() if value else "?"


def _gather_payments_text(session) -> str:
    rows = session.scalars(select(DaiOakesPaymentRecord)).all()
    if not rows:
        return _NO_DATA_TEXT
    by_status: dict[str, dict[str, float]] = {}
    for row in rows:
        bucket = by_status.setdefault(row.status, {"count": 0, "amount": 0.0, "amount_paid": 0.0})
        bucket["count"] += 1
        bucket["amount"] += row.amount or 0.0
        bucket["amount_paid"] += row.amount_paid or 0.0
    lines = [f"Total de faturas sincronizadas: {len(rows)}"]
    for status, bucket in sorted(by_status.items()):
        lines.append(
            f"- {status}: {int(bucket['count'])} fatura(s), "
            f"{bucket['amount']:.2f} faturado, {bucket['amount_paid']:.2f} pago"
        )
    return "\n".join(lines)


def _gather_bookings_text(session) -> str:
    latest = session.scalar(select(DaiOakesBookingsSnapshotRecord).order_by(DaiOakesBookingsSnapshotRecord.id.desc()))
    if latest is None:
        return _NO_DATA_TEXT
    return (
        f"Snapshot de {_fmt_dt(latest.created_at)}:\n"
        f"- total de marcações: {latest.total_bookings}\n"
        f"- hoje: {latest.today_count}, próximos 7 dias: {latest.next_7_days_count}\n"
        f"- por estado: {latest.by_status or {}}\n"
        f"- por localização: {latest.by_location or {}}\n"
        f"- por estado de depósito: {latest.by_deposit_status or {}}"
    )


def _gather_clients_text(session) -> str:
    latest = session.scalar(select(DaiOakesClientsSnapshotRecord).order_by(DaiOakesClientsSnapshotRecord.id.desc()))
    if latest is None:
        return _NO_DATA_TEXT
    return (
        f"Snapshot de {_fmt_dt(latest.created_at)}:\n"
        f"- total de clientes: {latest.total_clients}\n"
        f"- novos clientes (últimos 30 dias): {latest.new_clients_last_30_days}"
    )


def _gather_system_health_text(session) -> str:
    latest = session.scalar(select(DaiOakesSystemHealthSnapshotRecord).order_by(DaiOakesSystemHealthSnapshotRecord.id.desc()))
    if latest is None:
        return _NO_DATA_TEXT
    return (
        f"Snapshot de {_fmt_dt(latest.created_at)}:\n"
        f"- webhooks: {latest.webhooks_failed_last_24h} falhas nas últimas 24h "
        f"({latest.webhooks_failed_total} falhas / {latest.webhooks_processed_total} processados no total)\n"
        f"- emails (24h): {latest.emails_sent_last_24h} enviados, {latest.emails_failed_last_24h} falhados\n"
        f"- mensagens (24h): {latest.messages_sent_last_24h} enviadas, {latest.messages_failed_last_24h} falhadas\n"
        f"- ações admin (24h): {latest.admin_actions_last_24h}\n"
        f"- rate-limit de login atingido (24h): {latest.login_rate_limit_hits_last_24h}"
    )


def _build_prompt(payments_text: str, bookings_text: str, clients_text: str, system_health_text: str) -> str:
    return (
        "Produz o resumo semanal de inteligência da Dai Oakes a partir dos dados reais já "
        "sincronizados abaixo (todos vieram do próprio Back Office, não desta chamada).\n\n"
        f"## Pagamentos / faturação (dai_oakes_payments)\n{payments_text}\n\n"
        f"## Marcações (último snapshot bookings-summary)\n{bookings_text}\n\n"
        f"## Clientes (último snapshot clients-summary)\n{clients_text}\n\n"
        f"## Saúde operacional do painel (último snapshot system-health)\n{system_health_text}\n"
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


def _format_telegram_message(fields: dict[str, str]) -> str:
    return (
        "DAI OAKES · INTELIGÊNCIA -- resumo semanal\n\n"
        f"Pagamentos:\n{fields['payments_summary']}\n\n"
        f"Marcações:\n{fields['bookings_summary']}\n\n"
        f"Clientes:\n{fields['clients_summary']}\n\n"
        f"Saúde do sistema:\n{fields['system_health_summary']}\n\n"
        f"Alertas:\n{fields['alerts_summary']}"
    )


def run_weekly_dai_oakes_intelligence_sweep() -> None:
    try:
        client = llm_client.get_client()  # inside the try so a missing-provider LLMConfigError
        # degrades to a normal _persist_failure, same as market_intelligence.py.

        # Deliberately closes the DB session before the LLM call below -- this agent never
        # needs the connection open across a slow network call, unlike market_intelligence.py
        # which has no DB read at all in its gather phase.
        with session_scope() as session:
            payments_text = _gather_payments_text(session)
            bookings_text = _gather_bookings_text(session)
            clients_text = _gather_clients_text(session)
            system_health_text = _gather_system_health_text(session)

        prompt = _build_prompt(payments_text, bookings_text, clients_text, system_health_text)
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
        telegram_sent = False  # Telegram failure never undoes the report already about to be
        # persisted -- matches market_intelligence.py's own isolated try/except.

    with session_scope() as session:
        session.add(
            DaiOakesIntelligenceReportRecord(
                status="completed",
                payments_summary=str(submitted.get("payments_summary") or ""),
                bookings_summary=str(submitted.get("bookings_summary") or ""),
                clients_summary=str(submitted.get("clients_summary") or ""),
                system_health_summary=str(submitted.get("system_health_summary") or ""),
                alerts_summary=str(submitted.get("alerts_summary") or ""),
                model=MODEL,
                turns_used=1,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                telegram_sent=telegram_sent,
                completed_at=datetime.now(timezone.utc),
            )
        )
        session.add(AuditRecord(type="dai_oakes_intelligence_report_completed", detail=f"telegram_sent={telegram_sent}"))


def _persist_failure(reason: str) -> None:
    with session_scope() as session:
        session.add(
            DaiOakesIntelligenceReportRecord(
                status="failed",
                model=MODEL,
                telegram_sent=False,
                error=reason[:2000],
                completed_at=datetime.now(timezone.utc),
            )
        )
        session.add(AuditRecord(type="dai_oakes_intelligence_report_failed", detail=reason[:500]))


def run_sweep() -> None:
    if not llm_client.is_configured():
        return
    run_weekly_dai_oakes_intelligence_sweep()


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
            print(f"[volt-core-dai-oakes-intel] sweep failure: {type(exc).__name__}: {exc}")
        finally:
            _sweep_in_progress = False
        time.sleep(SWEEP_INTERVAL_SECONDS)


def start_dai_oakes_intelligence() -> None:
    global _started
    if _started or not llm_client.is_configured():
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_sweep_loop, name="volt-core-dai-oakes-intelligence", daemon=True).start()
        _started = True
