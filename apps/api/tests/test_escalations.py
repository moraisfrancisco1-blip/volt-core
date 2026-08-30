from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_scope
from app.escalations import MAX_CALL_ATTEMPTS, process_overdue_escalations
from app.main import app
from app.models import EscalationRecord, VoiceCallRecord


def _bootstrap(monkeypatch):
    monkeypatch.setenv("VOLT_BOOTSTRAP_CLIENT", "ci-admin")
    monkeypatch.setenv("VOLT_BOOTSTRAP_KEY", "ci-secret-key")
    return {"X-Volt-Key": "ci-secret-key"}


def _enable_mock_calling(monkeypatch, phone="+31600000001"):
    monkeypatch.setenv("VOLT_ALERT_PHONE", phone)
    monkeypatch.setenv("VOLT_AUTO_CALL_ENABLED", "true")
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_PHONE_NUMBER", raising=False)


def _latest_call_sid(event_id: int) -> str:
    with session_scope() as session:
        call = session.scalar(
            select(VoiceCallRecord).where(VoiceCallRecord.event_id == event_id).order_by(VoiceCallRecord.id.desc())
        )
        return call.call_sid


def test_event_is_automatically_queued_for_escalation(monkeypatch):
    headers = _bootstrap(monkeypatch)

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
        # No VOLT_ALERT_PHONE is configured in this test, so no call is ever attempted.
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


def test_p1_p2_p3_place_calls_but_stay_unconfirmed(monkeypatch):
    # Rebuilt from the abandoned fix/phone-escalation-priorities PR: P1, P2 and P3 all
    # place a real (mock, in CI) voice call. Adapted to this branch's actual invariant --
    # placing the call is not success. The escalation must land on "calling", never
    # "notified" or any other status that implies the operator was actually reached.
    headers = _bootstrap(monkeypatch)
    _enable_mock_calling(monkeypatch)

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

            response = client.get("/api/escalations?limit=50")
            escalation = next(item for item in response.json() if item["event_id"] == event["id"])
            assert escalation["status"] == "calling"
            assert escalation["call_attempts"] == 1

            with session_scope() as session:
                calls = session.scalars(select(VoiceCallRecord).where(VoiceCallRecord.event_id == event["id"])).all()
                call_count = len(calls)
                call_sid = calls[0].call_sid if calls else None
            assert call_count == 1
            assert call_sid


def test_p4_remains_digest_and_never_calls(monkeypatch):
    headers = _bootstrap(monkeypatch)
    _enable_mock_calling(monkeypatch)

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

        response = client.get("/api/escalations?limit=50")
        escalation = next(item for item in response.json() if item["event_id"] == event["id"])
        assert escalation["status"] == "queued"
        assert escalation["call_attempts"] == 0


def test_voice_status_callback_confirms_delivery(monkeypatch):
    headers = _bootstrap(monkeypatch)
    _enable_mock_calling(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/events",
            headers=headers,
            json={
                "system_id": "confirm-flow-system",
                "environment": "production",
                "severity": "critical",
                "message": "Confirm the call delivery flow",
            },
        )
        event_id = response.json()["id"]
        call_sid = _latest_call_sid(event_id)
        assert call_sid

        response = client.post("/api/voice/status", data={"CallSid": call_sid, "CallStatus": "completed"})
        assert response.status_code == 200
        assert response.json() == {"received": True, "matched": True}

        response = client.get("/api/escalations?limit=50")
        escalation = next(item for item in response.json() if item["event_id"] == event_id)
        assert escalation["status"] == "notified"


def test_voice_status_callback_no_answer_retries_instead_of_silent_success(monkeypatch):
    headers = _bootstrap(monkeypatch)
    _enable_mock_calling(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/events",
            headers=headers,
            json={
                "system_id": "retry-flow-system",
                "environment": "production",
                "severity": "medium",
                "message": "No-answer should trigger a retry, not success",
            },
        )
        event_id = response.json()["id"]
        first_sid = _latest_call_sid(event_id)

        response = client.post("/api/voice/status", data={"CallSid": first_sid, "CallStatus": "no-answer"})
        assert response.status_code == 200

        response = client.get("/api/escalations?limit=50")
        escalation = next(item for item in response.json() if item["event_id"] == event_id)
        # Never marked notified/acknowledged off an unanswered call -- it went back to
        # "calling" because a fresh retry call was placed immediately.
        assert escalation["status"] == "calling"
        assert escalation["priority"] == "P3"
        assert escalation["call_attempts"] == 2

        with session_scope() as session:
            calls = session.scalars(select(VoiceCallRecord).where(VoiceCallRecord.event_id == event_id)).all()
            call_count = len(calls)
            last_sid = calls[-1].call_sid if calls else None
        assert call_count == 2
        assert last_sid != first_sid


def test_repeated_no_answer_escalates_to_next_priority(monkeypatch):
    headers = _bootstrap(monkeypatch)
    _enable_mock_calling(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/events",
            headers=headers,
            json={
                "system_id": "escalate-flow-system",
                "environment": "production",
                "severity": "medium",
                "message": "Exhausting attempts should bump priority, never go quiet",
            },
        )
        event_id = response.json()["id"]

        for _ in range(MAX_CALL_ATTEMPTS):
            call_sid = _latest_call_sid(event_id)
            response = client.post("/api/voice/status", data={"CallSid": call_sid, "CallStatus": "no-answer"})
            assert response.status_code == 200

        response = client.get("/api/escalations?limit=50")
        escalation = next(item for item in response.json() if item["event_id"] == event_id)
        assert escalation["priority"] == "P2"  # bumped from P3 after MAX_CALL_ATTEMPTS unanswered calls
        assert escalation["status"] == "calling"
        assert escalation["call_attempts"] == 1

        response = client.get(f"/api/events/{event_id}")
        assert response.json()["priority"] == "P2"


def test_sla_timeout_redispatches_a_real_call_when_never_confirmed(monkeypatch):
    # Regression test for the original bug: process_overdue_escalations used to relabel
    # an overdue escalation's status without ever placing another call. A P2 whose first
    # call attempt never receives ANY status callback (Twilio outage, lost webhook, etc.)
    # must still get a fresh real call once its SLA window passes -- not just a new label.
    headers = _bootstrap(monkeypatch)
    _enable_mock_calling(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/events",
            headers=headers,
            json={
                "system_id": "sla-redispatch-system",
                "environment": "production",
                "severity": "high",
                "message": "SLA timeout must still place a real call",
            },
        )
        event_id = response.json()["id"]

    with session_scope() as session:
        escalation = session.scalar(select(EscalationRecord).where(EscalationRecord.event_id == event_id))
        assert escalation.status == "calling"
        assert escalation.call_attempts == 1
        escalation.created_at = datetime.now(timezone.utc) - timedelta(hours=1)

    with session_scope() as session:
        changed = process_overdue_escalations(session)
    assert any(item["event_id"] == event_id for item in changed)

    with session_scope() as session:
        escalation = session.scalar(select(EscalationRecord).where(EscalationRecord.event_id == event_id))
        calls = session.scalars(select(VoiceCallRecord).where(VoiceCallRecord.event_id == event_id)).all()
        assert escalation.status == "calling"
        assert escalation.call_attempts == 2
    assert len(calls) == 2


def test_voice_status_callback_rejects_invalid_twilio_signature(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-auth-token")
    monkeypatch.setenv("VOLT_PUBLIC_BASE_URL", "https://volt.example.com")

    with TestClient(app) as client:
        response = client.post(
            "/api/voice/status",
            data={"CallSid": "CAforgedsid", "CallStatus": "completed"},
            headers={"X-Twilio-Signature": "not-a-real-signature"},
        )
    assert response.status_code == 403


def test_voice_status_callback_accepts_valid_twilio_signature(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-auth-token")
    monkeypatch.setenv("VOLT_PUBLIC_BASE_URL", "https://volt.example.com")
    from twilio.request_validator import RequestValidator

    form = {"CallSid": "CAvalidatorsid", "CallStatus": "completed"}
    signature = RequestValidator("test-auth-token").compute_signature(
        "https://volt.example.com/api/voice/status", form
    )

    with TestClient(app) as client:
        response = client.post("/api/voice/status", data=form, headers={"X-Twilio-Signature": signature})
    assert response.status_code == 200
    # Signature passes, but no VoiceCallRecord has this fabricated sid.
    assert response.json() == {"received": True, "matched": False}
