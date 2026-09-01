from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..db import session_scope
from ..escalations import trigger_manual_investigation
from ..models import TelegramScheduleRecord
from ..telegram import send_telegram_message

CHECK_INTERVAL_SECONDS = 60  # granularity for "at HH:MM" schedules -- once a minute is enough

_started = False
_lock = threading.Lock()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _is_due(row: TelegramScheduleRecord, now: datetime) -> bool:
    last_run_at = _as_utc(row.last_run_at)
    if row.time_of_day:
        if now.strftime("%H:%M") != row.time_of_day:
            return False
        return last_run_at is None or last_run_at.date() != now.date()
    if row.interval_hours:
        return last_run_at is None or now - last_run_at >= timedelta(hours=row.interval_hours)
    return False


def _run_one(schedule_id: int, action: str, target: str | None) -> None:
    if action == "sweep":
        from .production_monitor_router import trigger_sweep

        result = trigger_sweep()
        text = "Varredura de monitorização disparada." if result.get("triggered") else f"Agendamento #{schedule_id}: não consegui disparar a varredura ({result.get('reason', 'motivo desconhecido')})."
    else:
        with session_scope() as session:
            event, _escalation = trigger_manual_investigation(session, target or "")
            event_id = event.id
        text = f"Agendamento #{schedule_id} — o Volt vai investigar {target} (evento #{event_id})."
    send_telegram_message(f"[agendado] {text}")


def run_due_schedules() -> None:
    now = datetime.now(timezone.utc)
    due: list[tuple[int, str, str | None]] = []
    with session_scope() as session:
        rows = session.scalars(select(TelegramScheduleRecord).where(TelegramScheduleRecord.active.is_(True))).all()
        for row in rows:
            if not _is_due(row, now):
                continue
            row.last_run_at = now  # marked before running -- never double-fires if the action is slow
            due.append((row.id, row.action, row.target))
    for schedule_id, action, target in due:
        try:
            _run_one(schedule_id, action, target)
        except Exception as exc:
            print(f"[volt-core-telegram-sched] schedule {schedule_id} failed: {type(exc).__name__}: {exc}")


def _sched_loop() -> None:
    while True:
        try:
            run_due_schedules()
        except Exception as exc:
            print(f"[volt-core-telegram-sched] {type(exc).__name__}: {exc}")
        time.sleep(CHECK_INTERVAL_SECONDS)


def start_telegram_scheduler() -> None:
    global _started
    # Gated on VOLT_TELEGRAM_BOT_TOKEN: schedules can only be created via Telegram, so
    # without it configured there can never be a row for this loop to act on.
    if _started or not os.getenv("VOLT_TELEGRAM_BOT_TOKEN"):
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_sched_loop, name="volt-core-telegram-scheduler", daemon=True).start()
        _started = True
