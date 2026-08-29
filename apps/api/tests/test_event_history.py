from fastapi.testclient import TestClient

from app.main import app


def test_event_history_lifecycle(monkeypatch):
    monkeypatch.setenv("VOLT_BOOTSTRAP_CLIENT", "ci-admin")
    monkeypatch.setenv("VOLT_BOOTSTRAP_KEY", "ci-secret-key")
    headers = {"X-Volt-Key": "ci-secret-key"}

    with TestClient(app) as client:
        response = client.post(
            "/api/events",
            headers=headers,
            json={
                "system_id": "solar-park-test",
                "system_name": "Solar Park Test",
                "environment": "production",
                "severity": "critical",
                "event_type": "production_stopped",
                "title": "Solar park production stopped",
                "message": "Production stopped. Immediate investigation required.",
                "source": "inverter-monitoring",
            },
        )
        assert response.status_code == 200
        event = response.json()
        assert event["priority"] == "P1"
        assert event["status"] == "active"
        event_id = event["id"]

        response = client.get("/api/events?severity=critical&system_id=solar-park-test")
        assert response.status_code == 200
        assert any(item["id"] == event_id for item in response.json())

        response = client.patch(f"/api/events/{event_id}", headers=headers, json={"acknowledge": True})
        assert response.status_code == 200
        assert response.json()["status"] == "acknowledged"

        response = client.patch(f"/api/events/{event_id}", headers=headers, json={"resolve": True})
        assert response.status_code == 200
        assert response.json()["status"] == "resolved"
        assert response.json()["resolved_at"] is not None
