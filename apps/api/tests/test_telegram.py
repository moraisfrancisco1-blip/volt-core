from fastapi.testclient import TestClient
from sqlalchemy import select

from app import telegram
from app.agents import status_router
from app.db import session_scope
from app.main import app
from app.models import AuditRecord, EscalationRecord, EventRecord, TelegramScheduleRecord


def _seed_event_and_escalation(system_id: str, *, priority: str = "P2", action: str = "call", status: str = "queued") -> tuple[int, int]:
    with session_scope() as session:
        event = EventRecord(
            system=system_id, system_id=system_id, system_name=system_id, environment="production",
            level="HIGH", severity="high", priority=priority, recommended_action=action,
            message="Telegram test probe", status="active",
        )
        session.add(event)
        session.flush()
        escalation = EscalationRecord(event_id=event.id, system=system_id, priority=priority, action=action, status=status)
        session.add(escalation)
        session.flush()
        return event.id, escalation.id


# --- _telegram_request / send_telegram_message seam ------------------------------

def test_telegram_request_without_token_returns_none(monkeypatch):
    monkeypatch.delenv("VOLT_TELEGRAM_BOT_TOKEN", raising=False)
    assert telegram._telegram_request("sendMessage", {}) is None


def test_send_telegram_message_without_chat_id_returns_false(monkeypatch):
    monkeypatch.setenv("VOLT_TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.delenv("VOLT_TELEGRAM_CHAT_ID", raising=False)
    assert telegram.send_telegram_message("hello") is False


def test_send_telegram_message_success(monkeypatch):
    monkeypatch.setenv("VOLT_TELEGRAM_CHAT_ID", "12345")
    calls = []
    monkeypatch.setattr(telegram, "_telegram_request", lambda method, payload: calls.append((method, payload)) or {"ok": True, "result": {"message_id": 1}})

    result = telegram.send_telegram_message("hello world")

    assert result is True
    assert calls == [("sendMessage", {"chat_id": "12345", "text": "hello world"})]


def test_send_telegram_message_telegram_error_returns_false(monkeypatch):
    monkeypatch.setenv("VOLT_TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr(telegram, "_telegram_request", lambda method, payload: {"ok": False, "description": "bad request"})
    assert telegram.send_telegram_message("hello") is False


# --- notify_telegram_channel -- fires for P1-P4, including digest ----------------

def test_notify_telegram_channel_sends_for_call_action(monkeypatch):
    sent = []
    monkeypatch.setattr(telegram, "send_telegram_message", lambda text: sent.append(text) or True)
    event = EventRecord(id=1, system="sys", system_id="sys", system_name="My System", environment="production", level="HIGH", priority="P1", recommended_action="call", message="Error rate spike", status="active")
    escalation = EscalationRecord(id=1, event_id=1, system="sys", priority="P1", action="call", status="queued")

    telegram.notify_telegram_channel(event, escalation)

    assert len(sent) == 1
    assert "P1" in sent[0]
    assert "My System" in sent[0]
    assert "Error rate spike" in sent[0]


def test_notify_telegram_channel_sends_for_digest_action_too(monkeypatch):
    # The key behavioral change: P4 "digest" never had ANY delivery mechanism before --
    # this is the first channel that reaches it, unlike dispatch_voice_call which only
    # acts on action=="call".
    sent = []
    monkeypatch.setattr(telegram, "send_telegram_message", lambda text: sent.append(text) or True)
    event = EventRecord(id=2, system="sys", system_id="sys", system_name="My System", environment="production", level="INFO", priority="P4", recommended_action="digest", message="Routine notice", status="active")
    escalation = EscalationRecord(id=2, event_id=2, system="sys", priority="P4", action="digest", status="queued")

    telegram.notify_telegram_channel(event, escalation)

    assert len(sent) == 1
    assert "P4" in sent[0]
    assert "Routine notice" in sent[0]


def test_notify_telegram_channel_failure_is_audited_not_raised(monkeypatch):
    def boom(text):
        raise RuntimeError("network exploded")
    monkeypatch.setattr(telegram, "send_telegram_message", boom)
    event = EventRecord(id=3, system="sys", system_id="sys", system_name="sys", environment="production", level="HIGH", priority="P2", recommended_action="call", message="msg", status="active")
    escalation = EscalationRecord(id=3, event_id=3, system="sys", priority="P2", action="call", status="queued")

    telegram.notify_telegram_channel(event, escalation)  # must not raise

    with session_scope() as session:
        rows = session.scalars(select(AuditRecord).where(AuditRecord.type == "telegram_notify_failed", AuditRecord.reference_id == "3")).all()
    assert len(rows) == 1


# --- status command ----------------------------------------------------------------

def test_status_command_reports_real_counts(monkeypatch):
    # _status_summary imports agents_status lazily (from app.agents.status_router) to
    # avoid a circular import (status_router -> production_monitor -> monitoring_alerts
    # -> event_history -> telegram) -- patch it at the source module, not on `telegram`.
    monkeypatch.setattr(status_router, "agents_status", lambda: [
        {"agent": "volt", "state": "idle"}, {"agent": "dev_debug", "state": "working"},
        {"agent": "database", "state": "idle"}, {"agent": "finance", "state": "idle"}, {"agent": "production_monitor", "state": "idle"},
    ])
    monkeypatch.setattr(telegram, "twilio_configured", lambda: True)

    reply = telegram.handle_telegram_message("status")

    assert "Orquestrador: ATIVO" in reply
    assert "1 ativos" in reply
    assert "4 standby" in reply
    assert "Linha de Voz: CONFIGURADA" in reply


def test_status_command_is_case_insensitive():
    assert "Orquestrador" in telegram.handle_telegram_message("STATUS")
    assert "Orquestrador" in telegram.handle_telegram_message("  status  ")


# --- reconhecer command -- reuses sync_escalation_status, no new ack logic ---------

def test_reconhecer_command_acknowledges_event_and_escalation():
    event_id, escalation_id = _seed_event_and_escalation("telegram-ack-system")

    reply = telegram.handle_telegram_message(f"reconhecer {escalation_id}")

    assert str(escalation_id) in reply
    assert str(event_id) in reply
    with session_scope() as session:
        event = session.get(EventRecord, event_id)
        escalation = session.get(EscalationRecord, escalation_id)
        assert event.status == "acknowledged"
        assert escalation.status == "acknowledged"
        audit_rows = session.scalars(select(AuditRecord).where(AuditRecord.type == "event_status_updated", AuditRecord.reference_id == str(event_id))).all()
        assert any("telegram" in (row.detail or "") for row in audit_rows)


def test_reconhecer_command_unknown_id_does_not_raise():
    reply = telegram.handle_telegram_message("reconhecer 999999")
    assert "não encontrado" in reply


def test_reconhecer_command_missing_id_returns_usage():
    reply = telegram.handle_telegram_message("reconhecer")
    assert "Uso" in reply


def test_unknown_command_returns_help_text(monkeypatch):
    # Deterministic regardless of the real shell environment: forces the "couldn't
    # classify" path rather than relying on ANTHROPIC_API_KEY happening to be unset.
    monkeypatch.setattr(telegram, "classify_telegram_request", lambda text: None)
    reply = telegram.handle_telegram_message("qualquer coisa aleatória")
    assert "status" in reply
    assert "reconhecer" in reply


# --- classify_telegram_request seam ------------------------------------------------

def test_classify_without_anthropic_api_key_returns_none(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert telegram.classify_telegram_request("força uma varredura") is None


# --- natural-language dispatch: sweep_now -------------------------------------------

def test_sweep_now_intent_triggers_real_sweep_function(monkeypatch):
    monkeypatch.setattr(telegram, "classify_telegram_request", lambda text: {
        "intent": "sweep_now", "target_system": "", "schedule_description_pt": "", "schedule_time_of_day": "", "schedule_interval_hours": 0,
    })
    calls = []
    import app.agents.production_monitor_router as production_monitor_router
    monkeypatch.setattr(production_monitor_router, "trigger_sweep", lambda: calls.append(True) or {"triggered": True})

    reply = telegram.handle_telegram_message("força uma varredura agora")

    assert calls == [True]
    assert "disparada" in reply


def test_sweep_now_intent_reports_real_failure_reason(monkeypatch):
    monkeypatch.setattr(telegram, "classify_telegram_request", lambda text: {
        "intent": "sweep_now", "target_system": "", "schedule_description_pt": "", "schedule_time_of_day": "", "schedule_interval_hours": 0,
    })
    import app.agents.production_monitor_router as production_monitor_router
    monkeypatch.setattr(production_monitor_router, "trigger_sweep", lambda: {"triggered": False, "reason": "RAILWAY_TOKEN not configured"})

    reply = telegram.handle_telegram_message("força uma varredura agora")

    assert "RAILWAY_TOKEN not configured" in reply


# --- natural-language dispatch: investigate_now -------------------------------------

def test_investigate_now_intent_triggers_manual_investigation(monkeypatch):
    monkeypatch.setattr(telegram, "classify_telegram_request", lambda text: {
        "intent": "investigate_now", "target_system": "solar-park-test", "schedule_description_pt": "", "schedule_time_of_day": "", "schedule_interval_hours": 0,
    })

    reply = telegram.handle_telegram_message("investiga o solar-park-test")

    assert "solar-park-test" in reply
    with session_scope() as session:
        event = session.scalar(select(EventRecord).where(EventRecord.system_id == "solar-park-test").order_by(EventRecord.id.desc()))
        assert event is not None
        assert event.event_type == "manual_investigation_request"


def test_investigate_now_intent_without_target_asks_for_one(monkeypatch):
    monkeypatch.setattr(telegram, "classify_telegram_request", lambda text: {
        "intent": "investigate_now", "target_system": "", "schedule_description_pt": "", "schedule_time_of_day": "", "schedule_interval_hours": 0,
    })

    reply = telegram.handle_telegram_message("investiga isso")

    assert "sistema" in reply.lower()


# --- natural-language dispatch: scheduling, 2-message confirmation -----------------

def test_schedule_request_proposes_interpretation_and_waits_for_confirmation(monkeypatch):
    telegram._pending_schedule = None
    monkeypatch.setattr(telegram, "classify_telegram_request", lambda text: {
        "intent": "schedule_sweep", "target_system": "", "schedule_description_pt": "varredura todos os dias às 09:00",
        "schedule_time_of_day": "09:00", "schedule_interval_hours": 0,
    })

    reply = telegram.handle_telegram_message("faz uma varredura todos os dias às 9h")

    assert "09:00" in reply
    assert "sim" in reply.lower()
    assert telegram._pending_schedule == {"action": "sweep", "target": None, "time_of_day": "09:00", "interval_hours": None}


def test_schedule_confirmation_saves_row_and_clears_pending_state(monkeypatch):
    telegram._pending_schedule = {"action": "sweep", "target": None, "time_of_day": "09:00", "interval_hours": None}

    reply = telegram.handle_telegram_message("sim")

    assert "guardado" in reply.lower()
    assert telegram._pending_schedule is None
    with session_scope() as session:
        row = session.scalar(select(TelegramScheduleRecord).order_by(TelegramScheduleRecord.id.desc()))
        assert row.action == "sweep"
        assert row.time_of_day == "09:00"
        assert row.active is True


def test_schedule_request_for_investigation_without_target_is_rejected(monkeypatch):
    telegram._pending_schedule = None
    monkeypatch.setattr(telegram, "classify_telegram_request", lambda text: {
        "intent": "schedule_investigate", "target_system": "", "schedule_description_pt": "investigação diária",
        "schedule_time_of_day": "09:00", "schedule_interval_hours": 0,
    })

    reply = telegram.handle_telegram_message("investiga todos os dias às 9h")

    assert "sistema" in reply.lower()
    assert telegram._pending_schedule is None


def test_non_confirmation_reply_cancels_pending_schedule_and_reclassifies(monkeypatch):
    telegram._pending_schedule = {"action": "sweep", "target": None, "time_of_day": "09:00", "interval_hours": None}
    monkeypatch.setattr(telegram, "classify_telegram_request", lambda text: None)

    reply = telegram.handle_telegram_message("na verdade esquece isso")

    assert telegram._pending_schedule is None
    assert "status" in reply  # fell through to the help text, not silently dropped


# --- out-of-scope requests are refused, never invented ------------------------------

def test_out_of_scope_request_is_refused_not_interpreted(monkeypatch):
    monkeypatch.setattr(telegram, "classify_telegram_request", lambda text: {
        "intent": "unknown", "target_system": "", "schedule_description_pt": "", "schedule_time_of_day": "", "schedule_interval_hours": 0,
    })

    reply = telegram.handle_telegram_message("apaga a base de dados")

    assert "status" in reply
    assert "reconhecer" in reply


# --- webhook: chat_id gate -----------------------------------------------------

def test_webhook_authorized_chat_processes_command(monkeypatch):
    monkeypatch.setenv("VOLT_TELEGRAM_CHAT_ID", "555")
    sent = []
    monkeypatch.setattr(telegram, "send_telegram_message", lambda text: sent.append(text) or True)

    with TestClient(app) as client:
        response = client.post("/api/v1/telegram/webhook", json={"message": {"chat": {"id": 555}, "text": "status"}})

    assert response.status_code == 200
    assert len(sent) == 1
    assert "Orquestrador" in sent[0]


def test_webhook_unauthorized_chat_is_ignored_and_audited(monkeypatch):
    monkeypatch.setenv("VOLT_TELEGRAM_CHAT_ID", "555")
    sent = []
    monkeypatch.setattr(telegram, "send_telegram_message", lambda text: sent.append(text) or True)

    with session_scope() as session:
        before = len(session.scalars(select(AuditRecord).where(AuditRecord.type == "telegram_unauthorized_attempt", AuditRecord.reference_id == "999")).all())

    with TestClient(app) as client:
        response = client.post("/api/v1/telegram/webhook", json={"message": {"chat": {"id": 999}, "text": "status"}})

    assert response.status_code == 200
    assert sent == []  # never processed, never replied to
    with session_scope() as session:
        after = len(session.scalars(select(AuditRecord).where(AuditRecord.type == "telegram_unauthorized_attempt", AuditRecord.reference_id == "999")).all())
    assert after == before + 1


def test_webhook_no_chat_id_configured_ignores_everything(monkeypatch):
    monkeypatch.delenv("VOLT_TELEGRAM_CHAT_ID", raising=False)
    sent = []
    monkeypatch.setattr(telegram, "send_telegram_message", lambda text: sent.append(text) or True)

    with TestClient(app) as client:
        response = client.post("/api/v1/telegram/webhook", json={"message": {"chat": {"id": 555}, "text": "status"}})

    assert response.status_code == 200
    assert sent == []
