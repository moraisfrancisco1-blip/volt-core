from fastapi.testclient import TestClient

from app.main import app


def test_event_is_automatically_queued_for_escalation(monkeypatch):
    monkeypatch.setenv("VOLT_BOOTSTRAP_CLIENT", "ci-admin")
    monkeypatch.setenv("VOLT_BOOTSTRAP_KEY", "ci-secret-key")
    headers = {"X-Volt-Key": "ci-secret-key"}

    with TestClient(app) as client:
        response = client.post(
            "/api/events",
            headers=headers,
            json={
                "system_id": "queue-test-system",
                "environment": "production",
                "severity": "critical",
                "message": "Queue a P1 escalation",
            },
        )
        assert response.status_code == 200
        event_id = response.json()["id"]

        response = client.get("/api/escalations?limit=50")
        assert response.status_code == 200
        escalation = next(item for item in response.json() if item["event_id"] == event_id)
        assert escalation["priority"] == "P1"
        assert escalation["action"] == "call"
        assert escalation["status"] == "queued"

        response = client.patch(f"/api/events/{event_id}", headers=headers, json={"acknowledge": True})
        assert response.status_code == 200

        response = client.get("/api/escalations?limit=50")
        escalation = next(item for item in response.json() if item["event_id"] == event_id)
        assert escalation["status"] == "acknowledged"

        response = client.patch(f"/api/events/{event_id}", headers=headers, json={"resolve": True})
        assert response.status_code == 200

        response = client.get("/api/escalations?limit=50")
        escalation = next(item for item in response.json() if item["event_id"] == event_id)
        assert escalation["status"] == "completed"


def test_p1_p2_p3_are_phone_call_escalations(monkeypatch):
    monkeypatch.setenv("VOLT_BOOTSTRAP_CLIENT", "ci-admin")
    monkeypatch.setenv("VOLT_BOOTSTRAP_KEY", "ci-secret-key")
    headers = {"X-Volt-Key": "ci-secret-key"}

    with TestClient(app) as client:
        for severity, expected_priority in (("critical", "P1"), ("high", "P2"), ("medium", "P3")):
            response = client.post(
                "/api/events",
                headers=headers,
                json={
                    "system_id": f"phone-{severity}",
                    "environment": "production",
                    "severity": severity,
                    "message": f"{expected_priority} must call the operator",
                },
            )
            assert response.status_code == 200
            event = response.json()
            assert event["priority"] == expected_priority
            assert event["recommended_action"] == "call"


def test_p4_remains_digest(monkeypatch):
    monkeypatch.setenv("VOLT_BOOTSTRAP_CLIENT", "ci-admin")
    monkeypatch.setenv("VOLT_BOOTSTRAP_KEY", "ci-secret-key")
    headers = {"X-Volt-Key": "ci-secret-key"}

    with TestClient(app) as client:
        response = client.post(
            "/api/events",
            headers=headers,
            json={
                "system_id": "digest-low",
                "environment": "production",
                "severity": "low",
                "message": "P4 should stay in the digest",
            },
        )
        assert response.status_code == 200
        event = response.json()
        assert event["priority"] == "P4"
        assert event["recommended_action"] == "digest"
