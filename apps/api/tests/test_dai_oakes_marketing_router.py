from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents import dai_oakes_marketing
from app.db import session_scope
from app.main import app
from app.models import AuditRecord, DaiOakesMarketingContentRecord


def _seed_content(**overrides) -> int:
    defaults = dict(format="instagram_post", title="Título", body="Corpo.", status="pending_approval")
    defaults.update(overrides)
    with session_scope() as session:
        content = DaiOakesMarketingContentRecord(**defaults)
        session.add(content)
        session.flush()
        return content.id


def test_list_and_get_content():
    content_id = _seed_content()
    with TestClient(app) as client:
        list_response = client.get("/api/dai-oakes-marketing-content?status=pending_approval")
        assert list_response.status_code == 200
        assert any(item["id"] == content_id for item in list_response.json())

        get_response = client.get(f"/api/dai-oakes-marketing-content/{content_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == content_id


def test_get_content_missing_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/dai-oakes-marketing-content/999999")
        assert response.status_code == 404


def test_list_content_rejects_invalid_status():
    with TestClient(app) as client:
        response = client.get("/api/dai-oakes-marketing-content?status=not-a-real-status")
        assert response.status_code == 422


def test_list_content_rejects_invalid_format():
    with TestClient(app) as client:
        response = client.get("/api/dai-oakes-marketing-content?format=not-a-real-format")
        assert response.status_code == 422


def test_approve_only_updates_status_never_touches_network(monkeypatch):
    content_id = _seed_content()

    def _forbidden(*args, **kwargs):
        raise AssertionError("approve must never make an HTTP request -- there is no real publish integration")

    import httpx
    monkeypatch.setattr(httpx, "Client", _forbidden)

    with TestClient(app) as client:
        response = client.post(f"/api/dai-oakes-marketing-content/{content_id}/approve")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "approved"
        assert payload["approved_at"] is not None


def test_approve_is_idempotent_against_double_click():
    content_id = _seed_content()
    with TestClient(app) as client:
        first = client.post(f"/api/dai-oakes-marketing-content/{content_id}/approve")
        second = client.post(f"/api/dai-oakes-marketing-content/{content_id}/approve")
        assert first.json()["status"] == "approved"
        assert second.json()["status"] == "approved"

    # The second call must be a no-op (status already "approved"), not a re-approve --
    # confirmed by exactly one "approved" audit entry for this content id, not two.
    with session_scope() as session:
        approvals = session.scalars(
            select(AuditRecord).where(AuditRecord.type == "dai_oakes_marketing_content_approved", AuditRecord.reference_id == str(content_id))
        ).all()
    assert len(approvals) == 1


def test_approve_missing_content_returns_404():
    with TestClient(app) as client:
        response = client.post("/api/dai-oakes-marketing-content/999999/approve")
        assert response.status_code == 404


def test_trigger_sweep_without_credentials_does_not_start_a_thread(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def spy():
        raise AssertionError("run_marketing_sweep must not be called without a provider")

    monkeypatch.setattr(dai_oakes_marketing, "run_marketing_sweep", spy)

    with TestClient(app) as client:
        response = client.post("/api/dai-oakes-marketing/run")
        assert response.json()["triggered"] is False
