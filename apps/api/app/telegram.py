from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Request
from sqlalchemy import func, select

from .db import session_scope
from .escalations import sync_escalation_status
from .integrations_router import twilio_configured
from .models import AgentInvestigationRecord, AuditRecord, EscalationRecord, EventRecord
from .voice import build_voice_script

TELEGRAM_API_BASE = "https://api.telegram.org"

router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])


def _telegram_request(method: str, payload: dict) -> dict | None:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    # Returns None only on missing config or a transport-level failure; Telegram's own
    # error responses (ok: false) still come back as a normal dict for the caller.
    token = os.getenv("VOLT_TELEGRAM_BOT_TOKEN")
    if not token:
        return None
    try:
        with httpx.Client(timeout=10) as client:
            response = client.post(f"{TELEGRAM_API_BASE}/bot{token}/{method}", json=payload)
        return response.json()
    except httpx.HTTPError:
        return None


def send_telegram_message(text: str) -> bool:
    chat_id = os.getenv("VOLT_TELEGRAM_CHAT_ID")
    if not chat_id:
        return False
    result = _telegram_request("sendMessage", {"chat_id": chat_id, "text": text})
    return bool(result and result.get("ok"))


def notify_telegram_channel(event: EventRecord, escalation: EscalationRecord) -> None:
    # Isolated from Twilio -- its own credential, its own failure mode, never blocks or
    # fails create_event. Fires for every classified event (P1-P4), unlike
    # dispatch_voice_call which only acts on action=="call": P4 ("digest") has never had
    # any delivery mechanism of its own, so this is the first channel that reaches it.
    script = build_voice_script({
        "priority": event.priority,
        "system": event.system_name or event.system,
        "message": event.message,
        "recommended_action": event.recommended_action,
    })
    try:
        send_telegram_message(script)
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="telegram_notify_failed", reference_id=str(event.id), detail=str(exc)[:500]))


def _status_summary() -> str:
    from .agents.status_router import agents_status  # lazy: status_router -> production_monitor
    # -> monitoring_alerts -> event_history -> telegram would be circular at import time.

    with session_scope() as session:
        investigation_count = session.scalar(select(func.count()).select_from(AgentInvestigationRecord)) or 0
        active_critical = session.scalar(
            select(func.count()).select_from(EscalationRecord).where(
                EscalationRecord.priority.in_(["P1", "P2"]),
                EscalationRecord.status.in_(["queued", "calling", "notified", "acknowledged"]),
            )
        ) or 0

    agents = agents_status()
    active_agents = sum(1 for a in agents if a["state"] != "idle")
    standby_agents = len(agents) - active_agents
    voice_line = "CONFIGURADA" if twilio_configured() else "PENDENTE"
    system_state = "ÓTIMO" if active_critical == 0 else "ATENÇÃO"

    return (
        "VOLT CORE -- estado atual\n"
        "Orquestrador: ATIVO\n"
        f"Memória (investigações): {investigation_count} guardadas\n"
        f"Linha de Voz: {voice_line}\n"
        f"Agentes: {active_agents} ativos · {standby_agents} standby\n"
        f"Sistema: {system_state}"
    )


def _acknowledge(escalation_id_text: str) -> str:
    try:
        escalation_id = int(escalation_id_text)
    except ValueError:
        return "Uso: reconhecer <id> (id numérico do escalonamento)"
    with session_scope() as session:
        escalation = session.get(EscalationRecord, escalation_id)
        if escalation is None:
            return f"Escalonamento {escalation_id} não encontrado."
        event = session.get(EventRecord, escalation.event_id)
        if event is None:
            return f"Escalonamento {escalation_id} não tem evento associado."
        event.status = "acknowledged"
        event.updated_at = datetime.now(timezone.utc)
        # Reuses the exact same function the dashboard/API's event PATCH endpoint calls
        # (apps/api/app/event_history.py's update_event) -- no new acknowledge logic.
        sync_escalation_status(session, event)
        session.add(AuditRecord(type="event_status_updated", reference_id=str(event.id), detail="acknowledged via telegram"))
        return f"Escalonamento {escalation_id} (evento {event.id}) reconhecido."


_HELP_TEXT = "Comandos disponíveis: status, reconhecer <id>"


def handle_telegram_command(text: str) -> str:
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered == "status":
        return _status_summary()
    if lowered.startswith("reconhecer"):
        rest = stripped[len("reconhecer"):].strip()
        if not rest:
            return "Uso: reconhecer <id>"
        return _acknowledge(rest)
    return _HELP_TEXT


@router.post("/webhook")
async def telegram_webhook(request: Request) -> dict:
    payload = await request.json()
    message = payload.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id") or "")
    expected_chat_id = os.getenv("VOLT_TELEGRAM_CHAT_ID", "").strip()
    if not expected_chat_id or chat_id != expected_chat_id:
        with session_scope() as session:
            session.add(AuditRecord(
                type="telegram_unauthorized_attempt",
                reference_id=chat_id or "unknown",
                detail=str(message.get("text", ""))[:200],
            ))
        return {"ok": True}  # Always 200 -- never give Telegram a reason to retry.

    text = str(message.get("text", ""))
    reply = handle_telegram_command(text)
    if reply:
        send_telegram_message(reply)
    return {"ok": True}
