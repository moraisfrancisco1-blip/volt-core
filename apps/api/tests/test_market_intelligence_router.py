from app.agents import market_intelligence
from app.agents.market_intelligence_router import trigger_market_intelligence_sweep
from app.db import session_scope
from app.models import MarketIntelligenceReportRecord
from fastapi.testclient import TestClient
from app.main import app


def _seed_report(**overrides) -> int:
    defaults = dict(status="completed", competitors_summary="c", regulation_summary="r", price_signals_summary="p", industry_news_summary="n", telegram_sent=True)
    defaults.update(overrides)
    with session_scope() as session:
        record = MarketIntelligenceReportRecord(**defaults)
        session.add(record)
        session.flush()
        return record.id


def test_trigger_without_credentials_does_not_start_a_thread(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def spy():
        raise AssertionError("run_weekly_intelligence_sweep must not be called without a provider")

    monkeypatch.setattr(market_intelligence, "run_weekly_intelligence_sweep", spy)

    result = trigger_market_intelligence_sweep()

    assert result["triggered"] is False
    assert "not configured" in result["reason"]


def test_trigger_with_credentials_starts_a_thread(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-not-real")
    started_threads = []

    class _FakeThread:
        def __init__(self, target, daemon):
            started_threads.append(target)

        def start(self):
            pass  # deliberately never actually run the sweep -- no real network/LLM calls

    import app.agents.market_intelligence_router as router_module
    monkeypatch.setattr(router_module.threading, "Thread", _FakeThread)

    result = trigger_market_intelligence_sweep()

    assert result == {"triggered": True}
    assert started_threads == [market_intelligence.run_weekly_intelligence_sweep]


def test_list_and_get_report_via_api():
    report_id = _seed_report()

    with TestClient(app) as client:
        list_response = client.get("/api/market-intelligence-reports?limit=10")
        assert list_response.status_code == 200
        rows = list_response.json()
        match = next(item for item in rows if item["id"] == report_id)
        assert match["competitors_summary"] == "c"
        assert match["telegram_sent"] is True

        get_response = client.get(f"/api/market-intelligence-reports/{report_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == report_id


def test_get_report_missing_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/market-intelligence-reports/999999")
        assert response.status_code == 404


def test_list_rejects_invalid_status():
    with TestClient(app) as client:
        response = client.get("/api/market-intelligence-reports?status=not-a-real-status")
        assert response.status_code == 422
