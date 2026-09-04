from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import entsoe_client, market_intelligence
from app.db import session_scope
from app.models import MarketIntelligenceReportRecord


@pytest.fixture(autouse=True)
def _default_provider_key(monkeypatch):
    # _call_model is always monkeypatched in the run_weekly_intelligence_sweep-level
    # tests, so the real client is never used -- but the function still calls
    # llm_client.get_client() first, which would raise LLMConfigError with no provider
    # configured at all. Same lazy-validation harmlessness as every other agent test file.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key-not-real")


def _fake_message(input, input_tokens=100, output_tokens=50):
    return SimpleNamespace(
        content=[{"type": "tool_use", "name": market_intelligence.SUBMIT_TOOL_NAME, "input": input, "id": "toolu_1"}],
        stop_reason="tool_use",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _latest_report() -> MarketIntelligenceReportRecord:
    with session_scope() as session:
        row = session.scalar(select(MarketIntelligenceReportRecord).order_by(MarketIntelligenceReportRecord.id.desc()))
        session.expunge(row)
        return row


def _no_network(monkeypatch):
    monkeypatch.setattr(market_intelligence, "_fetch_source", lambda url: "[no network in tests]")
    monkeypatch.setattr(entsoe_client, "fetch_entsoe_day_ahead_prices", lambda days=7: {"error": "no network in tests"})


# --- _competitors ---------------------------------------------------------------------

def test_competitors_defaults_when_env_unset(monkeypatch):
    monkeypatch.delenv("VOLT_MARKET_COMPETITORS", raising=False)
    assert market_intelligence._competitors() == ["Sympower", "Next Kraftwerke", "Tibber (Grid Rewards)", "Sessy"]


def test_competitors_reads_valid_json_array_override(monkeypatch):
    monkeypatch.setenv("VOLT_MARKET_COMPETITORS", '["Acme Corp", "Widget Co"]')
    assert market_intelligence._competitors() == ["Acme Corp", "Widget Co"]


def test_competitors_falls_back_to_defaults_on_malformed_json(monkeypatch):
    monkeypatch.setenv("VOLT_MARKET_COMPETITORS", "not json")
    assert market_intelligence._competitors() == ["Sympower", "Next Kraftwerke", "Tibber (Grid Rewards)", "Sessy"]


def test_competitors_falls_back_to_defaults_on_non_list_json(monkeypatch):
    monkeypatch.setenv("VOLT_MARKET_COMPETITORS", '{"not": "a list"}')
    assert market_intelligence._competitors() == ["Sympower", "Next Kraftwerke", "Tibber (Grid Rewards)", "Sessy"]


# --- _gather_price_signals_text ---------------------------------------------------------

def test_gather_price_signals_text_reports_entsoe_error(monkeypatch):
    monkeypatch.setattr(entsoe_client, "fetch_entsoe_day_ahead_prices", lambda days=7: {"error": "ENTSOE_API_TOKEN not configured"})
    text = market_intelligence._gather_price_signals_text()
    assert "indisponíveis" in text
    assert "ENTSOE_API_TOKEN not configured" in text


def test_gather_price_signals_text_summarizes_by_day(monkeypatch):
    monkeypatch.setattr(entsoe_client, "fetch_entsoe_day_ahead_prices", lambda days=7: {"prices": [
        {"start": "2026-09-01T00:00:00+00:00", "price_eur_mwh": 50.0},
        {"start": "2026-09-01T01:00:00+00:00", "price_eur_mwh": 60.0},
        {"start": "2026-09-02T00:00:00+00:00", "price_eur_mwh": 40.0},
    ]})
    text = market_intelligence._gather_price_signals_text()
    assert "2026-09-01" in text
    assert "2026-09-02" in text
    assert "média geral" in text


# --- run_weekly_intelligence_sweep -----------------------------------------------------

def test_run_weekly_intelligence_sweep_persists_all_four_areas_and_sends_telegram(monkeypatch):
    _no_network(monkeypatch)
    monkeypatch.setattr(market_intelligence, "_call_model", lambda client, prompt: _fake_message({
        "competitors_summary": "Sympower expandiu para baterias residenciais.",
        "regulation_summary": "sem novidades esta semana",
        "price_signals_summary": "Preços estáveis, sem anomalias.",
        "industry_news_summary": "sem novidades esta semana",
    }))
    telegram_calls = []
    monkeypatch.setattr(market_intelligence, "send_telegram_message", lambda text: telegram_calls.append(text) or True)

    market_intelligence.run_weekly_intelligence_sweep()

    report = _latest_report()
    assert report.status == "completed"
    assert report.competitors_summary == "Sympower expandiu para baterias residenciais."
    assert report.regulation_summary == "sem novidades esta semana"
    assert report.price_signals_summary == "Preços estáveis, sem anomalias."
    assert report.industry_news_summary == "sem novidades esta semana"
    assert report.telegram_sent is True
    assert report.turns_used == 1
    assert len(telegram_calls) == 1
    assert "INTELIGÊNCIA DE MERCADO" in telegram_calls[0]


def test_run_weekly_intelligence_sweep_records_report_even_if_telegram_fails(monkeypatch):
    _no_network(monkeypatch)
    monkeypatch.setattr(market_intelligence, "_call_model", lambda client, prompt: _fake_message({
        "competitors_summary": "x", "regulation_summary": "x", "price_signals_summary": "x", "industry_news_summary": "x",
    }))

    def _boom(text):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(market_intelligence, "send_telegram_message", _boom)

    market_intelligence.run_weekly_intelligence_sweep()  # must not raise

    report = _latest_report()
    assert report.status == "completed"
    assert report.telegram_sent is False


def test_run_weekly_intelligence_sweep_no_tool_use_is_recorded_as_failed(monkeypatch):
    _no_network(monkeypatch)
    monkeypatch.setattr(market_intelligence, "_call_model", lambda client, prompt: SimpleNamespace(
        content=[{"type": "text", "text": "uncertain"}], stop_reason="end_turn", input_tokens=10, output_tokens=5,
    ))

    market_intelligence.run_weekly_intelligence_sweep()

    report = _latest_report()
    assert report.status == "failed"
    assert "end_turn" in report.error
    assert report.telegram_sent is False


def test_run_weekly_intelligence_sweep_model_exception_is_recorded_as_failed_not_raised(monkeypatch):
    _no_network(monkeypatch)

    def _boom(client, prompt):
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr(market_intelligence, "_call_model", _boom)

    market_intelligence.run_weekly_intelligence_sweep()  # must not raise

    report = _latest_report()
    assert report.status == "failed"
    assert "simulated API failure" in report.error


def test_fetch_source_returns_error_text_on_transport_failure(monkeypatch):
    import httpx as httpx_module

    def _raise(*args, **kwargs):
        raise httpx_module.ConnectError("simulated DNS failure")

    monkeypatch.setattr(market_intelligence.httpx, "Client", _raise)
    result = market_intelligence._fetch_source("https://example.invalid")
    assert result.startswith("[error]")


def test_fetch_source_returns_error_text_on_non_200(monkeypatch):
    class _FakeResponse:
        status_code = 503
        text = ""

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return _FakeResponse()

    monkeypatch.setattr(market_intelligence.httpx, "Client", lambda **kw: _FakeClient())
    result = market_intelligence._fetch_source("https://example.invalid")
    assert result == "[error] HTTP 503"


def test_run_weekly_intelligence_sweep_one_dead_source_does_not_abort_the_sweep(monkeypatch):
    # _fetch_source itself never raises (proven above) -- this proves that contract
    # keeps the whole sweep alive even when every configured source is unreachable.
    monkeypatch.setattr(market_intelligence, "_fetch_source", lambda url: "[error] simulated failure")
    monkeypatch.setattr(entsoe_client, "fetch_entsoe_day_ahead_prices", lambda days=7: {"error": "no network in tests"})
    monkeypatch.setattr(market_intelligence, "_call_model", lambda client, prompt: _fake_message({
        "competitors_summary": "x", "regulation_summary": "x", "price_signals_summary": "x", "industry_news_summary": "x",
    }))

    market_intelligence.run_weekly_intelligence_sweep()  # must not raise

    report = _latest_report()
    assert report.status == "completed"


# --- run_sweep gating -------------------------------------------------------------------

def test_run_sweep_without_credentials_never_calls_model(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def spy(client, prompt):
        raise AssertionError("_call_model must not be called without a provider configured")

    monkeypatch.setattr(market_intelligence, "_call_model", spy)

    market_intelligence.run_sweep()  # must not raise, must not call the model


# --- start_market_intelligence ----------------------------------------------------------

def test_start_market_intelligence_does_nothing_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(market_intelligence, "_started", False)

    market_intelligence.start_market_intelligence()

    assert market_intelligence._started is False


def test_start_market_intelligence_starts_a_thread_when_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr(market_intelligence, "_started", False)
    started_threads = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started_threads.append((target, name, daemon))

        def start(self):
            pass  # deliberately never actually run the loop -- no real thread, no network

    monkeypatch.setattr(market_intelligence.threading, "Thread", _FakeThread)

    market_intelligence.start_market_intelligence()

    assert market_intelligence._started is True
    assert len(started_threads) == 1
    assert started_threads[0][1] == "volt-core-market-intelligence"
