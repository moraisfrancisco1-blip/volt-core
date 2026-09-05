from fastapi.testclient import TestClient
from sqlalchemy import select

from app import main as main_module
from app.db import session_scope
from app.main import app
from app.models import AuditRecord, VoiceCallRecord


def test_test_call_returns_400_without_alert_phone(monkeypatch):
    monkeypatch.delenv("VOLT_ALERT_PHONE", raising=False)
    with TestClient(app) as client:
        response = client.post("/api/voice/test-call")
        assert response.status_code == 400


def test_test_call_places_a_call_and_persists_records(monkeypatch):
    monkeypatch.setenv("VOLT_ALERT_PHONE", "+31600000000")
    calls = []

    class _FakeVoiceProvider:
        def place_call(self, to, script, **kwargs):
            calls.append((to, script))
            return {"provider": "mock", "status": "queued", "to": to, "script": script, "sid": "CAtest123"}

    monkeypatch.setattr(main_module, "voice_provider", _FakeVoiceProvider())

    with TestClient(app) as client:
        response = client.post("/api/voice/test-call")
        assert response.status_code == 200
        payload = response.json()
        assert payload["destination"] == "+31600000000"
        assert payload["status"] == "queued"

    assert calls == [("+31600000000", calls[0][1])]

    with session_scope() as session:
        call = session.get(VoiceCallRecord, payload["id"])
        assert call is not None
        assert call.destination == "+31600000000"
        audit = session.scalar(select(AuditRecord).where(AuditRecord.type == "test_call_dispatched", AuditRecord.reference_id == str(payload["id"])))
        assert audit is not None


def test_test_call_never_calls_place_call_without_alert_phone(monkeypatch):
    monkeypatch.delenv("VOLT_ALERT_PHONE", raising=False)

    def _forbidden(*args, **kwargs):
        raise AssertionError("place_call must not be called without VOLT_ALERT_PHONE configured")

    class _FakeVoiceProvider:
        place_call = staticmethod(_forbidden)

    monkeypatch.setattr(main_module, "voice_provider", _FakeVoiceProvider())

    with TestClient(app) as client:
        response = client.post("/api/voice/test-call")
        assert response.status_code == 400
