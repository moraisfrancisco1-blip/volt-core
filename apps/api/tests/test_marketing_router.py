from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents import marketing_agent
from app.db import session_scope
from app.main import app
from app.models import AuditRecord, MarketingContentRecord


def _seed_content(**overrides) -> int:
    defaults = dict(content_type="blog_post", format="blog", audience="consumer", title="Título", body="Corpo.", status="pending_approval")
    defaults.update(overrides)
    with session_scope() as session:
        content = MarketingContentRecord(**defaults)
        session.add(content)
        session.flush()
        return content.id


def test_list_and_get_content():
    content_id = _seed_content()
    with TestClient(app) as client:
        list_response = client.get("/api/marketing-content?status=pending_approval")
        assert list_response.status_code == 200
        assert any(item["id"] == content_id for item in list_response.json())

        get_response = client.get(f"/api/marketing-content/{content_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == content_id


def test_get_content_missing_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/marketing-content/999999")
        assert response.status_code == 404


def test_list_content_rejects_invalid_status():
    with TestClient(app) as client:
        response = client.get("/api/marketing-content?status=not-a-real-status")
        assert response.status_code == 422


def test_approve_only_updates_status_never_touches_network(monkeypatch):
    content_id = _seed_content()

    def _forbidden(*args, **kwargs):
        raise AssertionError("approve must never make an HTTP request -- there is no real publish integration")

    import httpx
    monkeypatch.setattr(httpx, "Client", _forbidden)

    with TestClient(app) as client:
        response = client.post(f"/api/marketing-content/{content_id}/approve")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "approved"
        assert payload["approved_at"] is not None


def test_approve_is_idempotent_against_double_click():
    content_id = _seed_content()
    with TestClient(app) as client:
        first = client.post(f"/api/marketing-content/{content_id}/approve")
        second = client.post(f"/api/marketing-content/{content_id}/approve")
        assert first.json()["status"] == "approved"
        assert second.json()["status"] == "approved"

    # The second call must be a no-op (status already "approved"), not a re-approve --
    # confirmed by exactly one "approved" audit entry for this content id, not two.
    with session_scope() as session:
        approvals = session.scalars(
            select(AuditRecord).where(AuditRecord.type == "marketing_content_approved", AuditRecord.reference_id == str(content_id))
        ).all()
    assert len(approvals) == 1


def test_approve_missing_content_returns_404():
    with TestClient(app) as client:
        response = client.post("/api/marketing-content/999999/approve")
        assert response.status_code == 404


def test_repurpose_without_credentials_does_not_start_a_thread(monkeypatch):
    content_id = _seed_content()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def spy(content_id):
        raise AssertionError("run_repurpose_content must not be called without a provider")

    monkeypatch.setattr(marketing_agent, "run_repurpose_content", spy)

    with TestClient(app) as client:
        response = client.post(f"/api/marketing-content/{content_id}/repurpose")
        assert response.json()["triggered"] is False


def test_repurpose_missing_content_returns_404():
    with TestClient(app) as client:
        response = client.post("/api/marketing-content/999999/repurpose")
        assert response.status_code == 404


def test_trigger_marketing_sweep_without_credentials_does_not_start_a_thread(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def spy():
        raise AssertionError("run_marketing_sweep must not be called without a provider")

    monkeypatch.setattr(marketing_agent, "run_marketing_sweep", spy)

    with TestClient(app) as client:
        response = client.post("/api/marketing/run")
        assert response.json()["triggered"] is False


def test_performance_always_reports_no_data_without_a_source():
    with TestClient(app) as client:
        response = client.get("/api/marketing/performance")
        assert response.status_code == 200
        assert response.json() == {"summary": "sem dados de performance ainda"}
