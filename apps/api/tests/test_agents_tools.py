from app.agents.tools import (
    InvestigationJob,
    get_escalation_and_call_trail,
    get_incident_event,
    get_recent_audit_log,
    get_recent_system_events,
    get_system_monitoring_status,
)
from app.db import session_scope
from app.models import AuditRecord, EscalationRecord, EventRecord, SystemRecord, VoiceCallRecord


def _seed_event(system_id: str, **overrides) -> int:
    with session_scope() as session:
        event = EventRecord(
            system=system_id,
            system_id=system_id,
            system_name=system_id,
            environment="production",
            level="HIGH",
            severity="high",
            priority="P2",
            event_type="probe",
            title="Investigation tool probe",
            recommended_action="call",
            message="Probe message for tool tests",
            status="active",
            **overrides,
        )
        session.add(event)
        session.flush()
        return event.id


def test_get_incident_event_returns_the_event():
    event_id = _seed_event("tools-incident-system")
    job = InvestigationJob(event_id=event_id, escalation_id=0, system="tools-incident-system", environment="production", priority="P2")
    result = get_incident_event(job)
    assert result["id"] == event_id
    assert result["system_id"] == "tools-incident-system"
    assert result["message"] == "Probe message for tool tests"


def test_get_incident_event_missing_returns_error():
    job = InvestigationJob(event_id=999999, escalation_id=0, system="nope", environment="production", priority="P2")
    result = get_incident_event(job)
    assert result == {"error": "event not found"}


def test_get_recent_system_events_excludes_the_incident_itself():
    older_id = _seed_event("tools-recent-system")
    newer_id = _seed_event("tools-recent-system")
    job = InvestigationJob(event_id=newer_id, escalation_id=0, system="tools-recent-system", environment="production", priority="P2")
    result = get_recent_system_events(job, limit=10)
    ids = [item["id"] for item in result["events"]]
    assert older_id in ids
    assert newer_id not in ids


def test_get_recent_system_events_only_same_system_and_environment():
    event_id = _seed_event("tools-scope-system-a")
    _seed_event("tools-scope-system-b")
    job = InvestigationJob(event_id=event_id, escalation_id=0, system="tools-scope-system-a", environment="production", priority="P2")
    result = get_recent_system_events(job, limit=10)
    for item in result["events"]:
        assert item["system_id"] == "tools-scope-system-a"


def test_get_escalation_and_call_trail_returns_escalation_and_calls():
    event_id = _seed_event("tools-trail-system")
    with session_scope() as session:
        escalation = EscalationRecord(event_id=event_id, system="tools-trail-system", priority="P2", action="call", status="calling", call_attempts=1)
        session.add(escalation)
        session.flush()
        escalation_id = escalation.id
        session.add(VoiceCallRecord(event_id=event_id, provider="mock", status="queued", destination="+31600000001", call_sid="TOOLSID1"))
        session.add(VoiceCallRecord(event_id=event_id, provider="mock", status="no-answer", destination="+31600000001", call_sid="TOOLSID2"))

    job = InvestigationJob(event_id=event_id, escalation_id=escalation_id, system="tools-trail-system", environment="production", priority="P2")
    result = get_escalation_and_call_trail(job)
    assert result["escalation"]["id"] == escalation_id
    assert result["escalation"]["call_attempts"] == 1
    assert [call["call_sid"] for call in result["calls"]] == ["TOOLSID1", "TOOLSID2"]


def test_get_escalation_and_call_trail_missing_escalation():
    event_id = _seed_event("tools-trail-missing")
    job = InvestigationJob(event_id=event_id, escalation_id=999999, system="tools-trail-missing", environment="production", priority="P2")
    result = get_escalation_and_call_trail(job)
    assert result["escalation"] is None
    assert result["calls"] == []


def test_get_system_monitoring_status_reads_system_record():
    with session_scope() as session:
        session.add(SystemRecord(name="tools-monitor-system", environment="production", status="down"))
    job = InvestigationJob(event_id=0, escalation_id=0, system="tools-monitor-system", environment="production", priority="P2")
    result = get_system_monitoring_status(job)
    assert result["system"]["name"] == "tools-monitor-system"
    assert result["system"]["status"] == "down"
    assert result["monitor"] is None  # not a configured health-check target


def test_get_recent_audit_log_filters_by_reference_id():
    event_id = _seed_event("tools-audit-system")
    escalation_id = 424242
    with session_scope() as session:
        session.add(AuditRecord(type="voice_call_dispatched", reference_id=str(event_id), detail="attempt=1"))
        session.add(AuditRecord(type="escalation_priority_bumped", reference_id=str(escalation_id), detail="P3->P2"))
        session.add(AuditRecord(type="unrelated_noise", reference_id="not-this-one", detail="ignore me"))

    job = InvestigationJob(event_id=event_id, escalation_id=escalation_id, system="tools-audit-system", environment="production", priority="P2")
    result = get_recent_audit_log(job, limit=10)
    types = {entry["type"] for entry in result["entries"]}
    assert types == {"voice_call_dispatched", "escalation_priority_bumped"}
