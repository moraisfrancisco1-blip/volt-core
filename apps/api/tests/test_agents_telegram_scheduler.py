from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agents import telegram_scheduler
from app.db import session_scope
from app.models import TelegramScheduleRecord


def _make_row(session, **kwargs) -> TelegramScheduleRecord:
    defaults = {"action": "sweep", "target": None, "time_of_day": None, "interval_hours": None, "active": True}
    defaults.update(kwargs)
    row = TelegramScheduleRecord(**defaults)
    session.add(row)
    session.flush()
    return row


def test_time_of_day_schedule_fires_once_per_day(monkeypatch):
    now = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    with session_scope() as session:
        row = _make_row(session, time_of_day="09:00")
        assert telegram_scheduler._is_due(row, now) is True
        row_id = row.id

    with session_scope() as session:
        row = session.get(TelegramScheduleRecord, row_id)
        row.last_run_at = now  # already ran earlier today at 09:00

    with session_scope() as session:
        row = session.get(TelegramScheduleRecord, row_id)
        # Same day, same minute -- must not fire twice.
        assert telegram_scheduler._is_due(row, now) is False
        # Next day, same time -- fires again.
        assert telegram_scheduler._is_due(row, now + timedelta(days=1)) is True


def test_time_of_day_schedule_does_not_fire_outside_its_minute():
    row = TelegramScheduleRecord(action="sweep", time_of_day="09:00", active=True)
    now_wrong_minute = datetime(2026, 9, 1, 9, 1, tzinfo=timezone.utc)
    assert telegram_scheduler._is_due(row, now_wrong_minute) is False


def test_interval_schedule_fires_after_elapsed_hours():
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    row = TelegramScheduleRecord(action="sweep", interval_hours=4, last_run_at=now - timedelta(hours=4))
    assert telegram_scheduler._is_due(row, now) is True


def test_interval_schedule_does_not_fire_before_elapsed_hours():
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    row = TelegramScheduleRecord(action="sweep", interval_hours=4, last_run_at=now - timedelta(hours=2))
    assert telegram_scheduler._is_due(row, now) is False


def test_interval_schedule_with_no_prior_run_fires_immediately():
    row = TelegramScheduleRecord(action="sweep", interval_hours=4, last_run_at=None)
    assert telegram_scheduler._is_due(row, datetime.now(timezone.utc)) is True


def test_inactive_schedule_is_never_picked_up_by_run_due_schedules(monkeypatch):
    with session_scope() as session:
        row = _make_row(session, interval_hours=1, last_run_at=None, active=False)
        row_id = row.id

    ran = []
    monkeypatch.setattr(telegram_scheduler, "_run_one", lambda *a, **k: ran.append(a))

    telegram_scheduler.run_due_schedules()

    assert ran == []
    with session_scope() as session:
        row = session.get(TelegramScheduleRecord, row_id)
        assert row.last_run_at is None


def test_run_due_schedules_marks_last_run_at_before_running(monkeypatch):
    with session_scope() as session:
        row = _make_row(session, interval_hours=1, last_run_at=None, active=True)
        row_id = row.id

    ran = []
    monkeypatch.setattr(telegram_scheduler, "_run_one", lambda *a, **k: ran.append(a))

    telegram_scheduler.run_due_schedules()

    assert len(ran) == 1
    with session_scope() as session:
        row = session.get(TelegramScheduleRecord, row_id)
        assert row.last_run_at is not None


def test_run_one_sweep_action_calls_trigger_sweep_and_notifies(monkeypatch):
    import app.agents.production_monitor_router as production_monitor_router

    monkeypatch.setattr(production_monitor_router, "trigger_sweep", lambda: {"triggered": True})
    sent = []
    monkeypatch.setattr(telegram_scheduler, "send_telegram_message", lambda text: sent.append(text) or True)

    telegram_scheduler._run_one(1, "sweep", None)

    assert len(sent) == 1
    assert "disparada" in sent[0]


def test_run_one_investigate_action_calls_manual_trigger_and_notifies(monkeypatch):
    triggered = []
    monkeypatch.setattr(telegram_scheduler, "trigger_manual_investigation", lambda session, target: triggered.append(target) or (type("E", (), {"id": 42})(), None))
    sent = []
    monkeypatch.setattr(telegram_scheduler, "send_telegram_message", lambda text: sent.append(text) or True)

    telegram_scheduler._run_one(2, "investigate", "solar-park-test")

    assert triggered == ["solar-park-test"]
    assert len(sent) == 1
    assert "solar-park-test" in sent[0]
