from fastapi.testclient import TestClient

from app.main import app


def test_full_staging_flow(monkeypatch):
    monkeypatch.setenv("VOLT_BOOTSTRAP_CLIENT", "ci-admin")
    monkeypatch.setenv("VOLT_BOOTSTRAP_KEY", "ci-secret-key")

    headers = {"X-Volt-Key": "ci-secret-key"}

    with TestClient(app) as client:
        response = client.get("/api/v1/status", headers=headers)
        assert response.status_code == 200

        response = client.post(
            "/api/v1/systems",
            headers=headers,
            json={"name": "demo-service", "environment": "production"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "connected"

        response = client.post(
            "/api/v1/watch/events",
            headers=headers,
            json={
                "system": "demo-service",
                "level": "CRITICAL",
                "message": "Database connection lost",
            },
        )
        assert response.status_code == 200
        event = response.json()
        assert event["priority"] == "P1"
        event_id = event["id"]

        response = client.post(
            "/api/v1/voice/calls",
            headers=headers,
            json={"event_id": event_id, "to": "+31000000000"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "queued"

        response = client.post(
            "/api/v1/approvals",
            headers=headers,
            json={"event_id": event_id, "action": "restart_service"},
        )
        assert response.status_code == 200
        approval_id = response.json()["id"]

        response = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            headers=headers,
            json={"decision": "approved"},
        )
        assert response.status_code == 200
        assert response.json()["decision"] == "approved"

        response = client.post(
            "/api/v1/actions",
            headers=headers,
            json={"approval_id": approval_id, "environment": "staging"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "executed"

        response = client.post(
            "/api/v1/actions",
            headers=headers,
            json={"approval_id": approval_id, "environment": "production"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "blocked"

        response = client.get("/api/v1/audit", headers=headers)
        assert response.status_code == 200
        audit_types = {item["type"] for item in response.json()}
        assert {"system_registered", "event_received", "voice_call_requested", "approval_requested", "approval_decision", "action_evaluated"}.issubset(audit_types)
