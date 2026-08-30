from datetime import datetime, timezone

from sqlalchemy import select

from app.agents.monitoring_alerts import raise_monitoring_alert
from app.agents.railway_tools import ProductionSweepJob
from app.db import session_scope
from app.models import EscalationRecord, EventRecord


def _job(system: str) -> ProductionSweepJob:
    return ProductionSweepJob(system=system, environment="production", project_id="p1", service_id="s1", environment_id="e1")


def test_raise_monitoring_alert_creates_event_and_escalation():
    job = _job("prodmon-alert-system")
    result = raise_monitoring_alert(job, severity="high", category="error_rate", title="Elevated 5xx", message="5xx rate at 12% over the last hour")
    assert result["created"] is True
    event_id = result["event_id"]

    with session_scope() as session:
        event = session.get(EventRecord, event_id)
        assert event.system_id == "prodmon-alert-system"
        assert event.event_type == "railway_error_rate"
        assert event.priority == "P2"  # severity=high -> P2
        escalation = session.scalar(select(EscalationRecord).where(EscalationRecord.event_id == event_id))
        assert escalation is not None


def test_raise_monitoring_alert_deduplicates_open_alert_same_category():
    job = _job("prodmon-dedup-system")
    first = raise_monitoring_alert(job, severity="medium", category="latency", title="Slow responses", message="p95 latency above 2s")
    assert first["created"] is True

    second = raise_monitoring_alert(job, severity="medium", category="latency", title="Still slow, worded differently this time", message="p95 latency remains elevated at 2.3s")
    assert second["created"] is False
    assert second["event_id"] == first["event_id"]

    with session_scope() as session:
        count = len(session.scalars(select(EventRecord).where(EventRecord.system_id == "prodmon-dedup-system", EventRecord.event_type == "railway_latency")).all())
    assert count == 1


def test_raise_monitoring_alert_does_not_suppress_after_resolution():
    job = _job("prodmon-resolved-system")
    first = raise_monitoring_alert(job, severity="low", category="resource_usage", title="High memory", message="memory at 85%")
    assert first["created"] is True

    with session_scope() as session:
        event = session.get(EventRecord, first["event_id"])
        event.status = "resolved"
        event.resolved_at = datetime.now(timezone.utc)

    second = raise_monitoring_alert(job, severity="low", category="resource_usage", title="High memory again", message="memory at 87%")
    assert second["created"] is True
    assert second["event_id"] != first["event_id"]


def test_raise_monitoring_alert_different_categories_do_not_suppress_each_other():
    job = _job("prodmon-multi-category-system")
    error_rate = raise_monitoring_alert(job, severity="high", category="error_rate", title="5xx spike", message="elevated error rate")
    latency = raise_monitoring_alert(job, severity="medium", category="latency", title="Slow", message="elevated latency")
    assert error_rate["created"] is True
    assert latency["created"] is True
    assert error_rate["event_id"] != latency["event_id"]


def test_raise_monitoring_alert_rejects_unknown_category():
    result = raise_monitoring_alert(_job("prodmon-bad-category"), severity="high", category="not-a-real-category", title="x", message="y")
    assert "error" in result
