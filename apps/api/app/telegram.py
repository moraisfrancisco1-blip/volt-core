from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Request
from sqlalchemy import func, select

from . import llm_client
from .db import session_scope
from .escalations import sync_escalation_status, trigger_manual_investigation
from .integrations_router import twilio_configured
from .models import AgentInvestigationRecord, AuditRecord, EscalationRecord, EventRecord, TelegramScheduleRecord
from .voice import build_voice_script

TELEGRAM_API_BASE = "https://api.telegram.org"

router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])

MODEL = os.getenv("VOLT_TELEGRAM_MODEL") or llm_client.default_model()


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


_HELP_TEXT = (
    "Comandos disponíveis: status, reconhecer <id>.\n"
    "Também percebo pedidos soltos: \"força uma varredura\", "
    "\"investiga o <sistema>\", ou um agendamento tipo \"todos os dias às 09:00\"."
)

# Not an agent with tools -- a single forced-tool-choice call to get structured output
# from a free-text request, same llm_client every agent already uses, without
# hand-rolling a natural-language parser.
CLASSIFY_TOOL_NAME = "classify_telegram_request"
CLASSIFY_TOOL_SCHEMA = {
    "name": CLASSIFY_TOOL_NAME,
    "description": "Classifica um pedido em português solto do operador do VOLT CORE.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["sweep_now", "investigate_now", "schedule_sweep", "schedule_investigate", "unknown"],
            },
            "target_system": {
                "type": "string",
                "description": "Nome do sistema a investigar, ex. 'solar-park-test'. Vazio se não aplicável.",
            },
            "schedule_description_pt": {
                "type": "string",
                "description": "Frase curta em português a confirmar o agendamento entendido, ex. 'varredura todos os dias às 09:00'. Vazio se não for um pedido de agendamento.",
            },
            "schedule_time_of_day": {
                "type": "string",
                "description": "HH:MM (24h) se foi mencionada uma hora do dia específica, senão vazio.",
            },
            "schedule_interval_hours": {
                "type": "integer",
                "description": "N se foi pedido algo como 'de N em N horas', senão 0.",
            },
        },
        "required": ["intent", "target_system", "schedule_description_pt", "schedule_time_of_day", "schedule_interval_hours"],
    },
}

_CLASSIFY_SYSTEM_PROMPT = (
    "Classificas pedidos em português para o VOLT CORE, um centro de operações de IA. "
    "Só sabes fazer duas coisas: forçar uma varredura de monitorização, ou pedir uma "
    "investigação a um sistema específico -- cada uma pode ser pedida agora ou agendada. "
    "Nunca inventes um intent fora dos definidos na ferramenta, e nunca assumas um "
    "target_system que não esteja explícito na mensagem."
)


def classify_telegram_request(text: str) -> dict | None:
    # None means "couldn't classify" (no provider configured, or the model didn't call
    # the tool) -- the caller degrades to the help text, never crashes.
    if not llm_client.is_configured():
        return None
    client = llm_client.get_client()
    response = client.call(
        model=MODEL,
        max_tokens=512,
        system=_CLASSIFY_SYSTEM_PROMPT,
        tools=[CLASSIFY_TOOL_SCHEMA],
        tool_choice=CLASSIFY_TOOL_NAME,
        messages=[{"role": "user", "content": text}],
    )
    for block in response.content:
        if block.get("type") == "tool_use":
            return block["input"]
    return None


def _trigger_sweep_now() -> str:
    # Lazy import: production_monitor_router -> production_monitor, no cycle risk with
    # telegram.py, but keeps the import next to its one use, matching _status_summary's
    # style for the other lazy import in this file.
    from .agents.production_monitor_router import trigger_sweep

    result = trigger_sweep()
    if result.get("triggered"):
        return "Varredura de monitorização disparada."
    return f"Não consegui disparar a varredura: {result.get('reason', 'motivo desconhecido')}."


def _trigger_investigation_now(target_system: str) -> str:
    if not target_system:
        return "Preciso de saber qual sistema investigar -- ex. \"investiga o solar-park-test\"."
    with session_scope() as session:
        event, _escalation = trigger_manual_investigation(session, target_system)
        event_id = event.id
    return f"Pedido — o Volt vai investigar {target_system} (evento #{event_id})."


# In-memory only, on purpose -- this is a single-user system and a 2-message confirmation
# gate ("aqui está o que percebi, confirmas?" / "sim") has no reason to survive a restart.
_pending_schedule: dict | None = None


def _propose_schedule(classification: dict) -> str:
    global _pending_schedule
    action = "sweep" if classification["intent"] == "schedule_sweep" else "investigate"
    target = classification.get("target_system") or None
    time_of_day = classification.get("schedule_time_of_day") or None
    interval_hours = classification.get("schedule_interval_hours") or 0
    if action == "investigate" and not target:
        return "Para agendar uma investigação preciso de saber qual sistema -- ex. \"investiga o solar-park-test todos os dias às 09:00\"."
    if not time_of_day and not interval_hours:
        return "Não percebi quando queres que isto corra -- diz uma hora (\"às 09:00\") ou um intervalo (\"de 4 em 4 horas\")."
    _pending_schedule = {
        "action": action, "target": target,
        "time_of_day": time_of_day, "interval_hours": interval_hours or None,
    }
    description = classification.get("schedule_description_pt") or "esse agendamento"
    return f"Entendi: {description}. Confirmas? (responde \"sim\")"


def _confirm_pending_schedule() -> str:
    global _pending_schedule
    schedule = _pending_schedule
    _pending_schedule = None
    with session_scope() as session:
        row = TelegramScheduleRecord(
            action=schedule["action"], target=schedule["target"],
            time_of_day=schedule["time_of_day"], interval_hours=schedule["interval_hours"],
        )
        session.add(row)
        session.flush()
        row_id = row.id
        session.add(AuditRecord(type="telegram_schedule_created", reference_id=str(row_id), detail=f"action={schedule['action']} target={schedule['target']} time_of_day={schedule['time_of_day']} interval_hours={schedule['interval_hours']}"))
    return f"Agendamento #{row_id} guardado."


def handle_telegram_message(text: str) -> str:
    global _pending_schedule
    stripped = text.strip()
    lowered = stripped.lower()

    if lowered == "status":
        return _status_summary()
    if lowered.startswith("reconhecer"):
        rest = stripped[len("reconhecer"):].strip()
        if not rest:
            return "Uso: reconhecer <id>"
        return _acknowledge(rest)

    if _pending_schedule is not None:
        if lowered in {"sim", "s", "yes", "confirmo", "ok"}:
            return _confirm_pending_schedule()
        _pending_schedule = None  # any other reply cancels the pending confirmation,
        # falling through to reclassify this new message rather than silently dropping it

    classification = classify_telegram_request(stripped)
    if classification is None:
        return _HELP_TEXT

    intent = classification.get("intent")
    if intent == "sweep_now":
        return _trigger_sweep_now()
    if intent == "investigate_now":
        return _trigger_investigation_now((classification.get("target_system") or "").strip())
    if intent in {"schedule_sweep", "schedule_investigate"}:
        return _propose_schedule(classification)
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
    reply = handle_telegram_message(text)
    if reply:
        send_telegram_message(reply)
    return {"ok": True}
