from fastapi.testclient import TestClient
from sqlalchemy import select

from app import escalations as escalations_module
from app.db import session_scope
from app.main import app
from app.models import EventRecord


def test_trigger_manual_investigation_endpoint_creates_a_real_event(monkeypatch):
    monkeypatch.setattr(escalations_module, "post_message", lambda session, **kwargs: None)

    with TestClient(app) as client:
        response = client.post("/api/investigations/trigger-manual", json={"system_id": "dashboard-trigger-test"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["system_id"] == "dashboard-trigger-test"

    with session_scope() as session:
        event = session.get(EventRecord, payload["event_id"])
        assert event is not None
        assert event.system_id == "dashboard-trigger-test"
        assert "via dashboard" in event.title
        assert "via dashboard" in event.message


def test_trigger_manual_investigation_endpoint_defaults_environment_to_production(monkeypatch):
    monkeypatch.setattr(escalations_module, "post_message", lambda session, **kwargs: None)

    with TestClient(app) as client:
        response = client.post("/api/investigations/trigger-manual", json={"system_id": "dashboard-trigger-env-test"})
        assert response.status_code == 200

    with session_scope() as session:
        event = session.scalar(select(EventRecord).where(EventRecord.system_id == "dashboard-trigger-env-test"))
        assert event.environment == "production"
