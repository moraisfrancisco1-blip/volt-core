from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db import session_scope
from app.main import app
from app.models import AgentInvestigationRecord, EventRecord


def _seed_event(system_id: str) -> int:
    with session_scope() as session:
        event = EventRecord(
            system=system_id, system_id=system_id, system_name=system_id, environment="production",
            level="HIGH", severity="high", priority="P2", recommended_action="call",
            message="Investigations API probe", status="active",
        )
        session.add(event)
        session.flush()
        return event.id


def _seed_investigation(event_id: int, *, status: str, hypothesis: str | None = "A hypothesis", **overrides) -> int:
    with session_scope() as session:
        record = AgentInvestigationRecord(
            event_id=event_id, escalation_id=event_id, system="investigations-api-system", environment="production",
            priority="P2", status=status, hypothesis=hypothesis, recommended_next_step="Do something",
            confidence=0.5, is_known_pattern=False, model="claude-sonnet-4-5",
            completed_at=datetime.now(timezone.utc), **overrides,
        )
        session.add(record)
        session.flush()
        return record.id


def test_list_investigations_returns_seeded_rows():
    event_id = _seed_event("investigations-api-list-system")
    investigation_id = _seed_investigation(event_id, status="completed")

    with TestClient(app) as client:
        response = client.get("/api/investigations?limit=50")
        assert response.status_code == 200
        rows = response.json()
        match = next(item for item in rows if item["id"] == investigation_id)
        assert match["event_id"] == event_id
        assert match["status"] == "completed"
        assert match["hypothesis"] == "A hypothesis"


def test_list_investigations_filters_by_event_id_and_status():
    event_id = _seed_event("investigations-api-filter-system")
    completed_id = _seed_investigation(event_id, status="completed")
    _seed_investigation(event_id, status="failed", hypothesis=None)

    with TestClient(app) as client:
        response = client.get(f"/api/investigations?event_id={event_id}&status=completed")
        assert response.status_code == 200
        rows = response.json()
        assert {item["id"] for item in rows} == {completed_id}


def test_list_investigations_rejects_invalid_status():
    with TestClient(app) as client:
        response = client.get("/api/investigations?status=not-a-real-status")
        assert response.status_code == 422


def test_get_investigation_by_id():
    event_id = _seed_event("investigations-api-get-system")
    investigation_id = _seed_investigation(event_id, status="completed")

    with TestClient(app) as client:
        response = client.get(f"/api/investigations/{investigation_id}")
        assert response.status_code == 200
        assert response.json()["id"] == investigation_id


def test_get_investigation_missing_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/investigations/999999")
        assert response.status_code == 404


def test_list_investigations_filters_by_parent_investigation_id():
    parent_event_id = _seed_event("investigations-api-parent-system")
    parent_id = _seed_investigation(parent_event_id, status="completed", investigation_type="voice_call_failure")
    child_event_id = _seed_event("investigations-api-child-system")
    child_id = _seed_investigation(
        child_event_id, status="completed", investigation_type="code_diagnosis",
        parent_investigation_id=parent_id, repo_owner="acme", repo_name="widget",
    )
    _seed_investigation(child_event_id, status="completed", investigation_type="code_diagnosis")  # unrelated, no parent

    with TestClient(app) as client:
        response = client.get(f"/api/investigations?parent_investigation_id={parent_id}")
        assert response.status_code == 200
        rows = response.json()
        assert {item["id"] for item in rows} == {child_id}
        assert rows[0]["repo_owner"] == "acme"
        assert rows[0]["repo_name"] == "widget"
        assert rows[0]["parent_investigation_id"] == parent_id
