from datetime import datetime, timedelta, timezone

from app.decision_engine import validate_decision_matrix
from app.escalations import SLA_MINUTES, NEXT_PRIORITY


def test_decision_matrix():
    results = validate_decision_matrix()
    assert all(item["ok"] for item in results)


def test_sla_ladder():
    assert SLA_MINUTES == {"P1": 5, "P2": 15, "P3": 60, "P4": 240}
    assert NEXT_PRIORITY == {"P4": "P3", "P3": "P2", "P2": "P1", "P1": "P1"}


def test_priority_timeout_order():
    now = datetime.now(timezone.utc)
    created = {priority: now - timedelta(minutes=minutes + 1) for priority, minutes in SLA_MINUTES.items()}
    assert created["P1"] < now and created["P2"] < now and created["P3"] < now and created["P4"] < now
