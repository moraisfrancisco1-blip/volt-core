from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import dai_oakes_intelligence
from app.db import session_scope
from app.models import (
    DaiOakesBookingsSnapshotRecord,
    DaiOakesClientsSnapshotRecord,
    DaiOakesIntelligenceReportRecord,
    DaiOakesPaymentRecord,
    DaiOakesSystemHealthSnapshotRecord,
)


@pytest.fixture(autouse=True)
def _default_provider_key(monkeypatch):
    # _call_model is always monkeypatched in the run_weekly_dai_oakes_intelligence_sweep-
    # level tests, so the real client is never used -- but the function still calls
    # llm_client.get_client() first, which would raise LLMConfigError with no provider
    # configured at all. Same lazy-validation harmlessness as every other agent test file.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-test-key-not-real")


def _fake_message(input, input_tokens=100, output_tokens=50):
    return SimpleNamespace(
        content=[{"type": "tool_use", "name": dai_oakes_intelligence.SUBMIT_TOOL_NAME, "input": input, "id": "toolu_1"}],
        stop_reason="tool_use",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _latest_report() -> DaiOakesIntelligenceReportRecord:
    with session_scope() as session:
        row = session.scalar(select(DaiOakesIntelligenceReportRecord).order_by(DaiOakesIntelligenceReportRecord.id.desc()))
        session.expunge(row)
        return row


def _fake_submission():
    return {
        "payments_summary": "121 faturas, 113 pagas.",
        "bookings_summary": "42 marcações no total.",
        "clients_summary": "250 clientes, 14 novos.",
        "system_health_summary": "tudo saudável.",
        "alerts_summary": "sem novidades esta semana",
    }


# --- gather functions -- this agent never calls the Dai Oakes API itself, only reads what
# Back Office already synced into this same database -----------------------------------

def test_gather_payments_text_reports_no_data_when_table_empty():
    with session_scope() as session:
        session.query(DaiOakesPaymentRecord).delete()
        text = dai_oakes_intelligence._gather_payments_text(session)
    assert text == dai_oakes_intelligence._NO_DATA_TEXT


def test_gather_payments_text_summarizes_by_status():
    with session_scope() as session:
        session.query(DaiOakesPaymentRecord).delete()
        session.add(DaiOakesPaymentRecord(external_id="p1", status="paid", amount=100.0, amount_paid=100.0))
        session.add(DaiOakesPaymentRecord(external_id="p2", status="pending", amount=50.0, amount_paid=0.0))
    with session_scope() as session:
        text = dai_oakes_intelligence._gather_payments_text(session)
    assert "Total de faturas sincronizadas: 2" in text
    assert "paid" in text
    assert "pending" in text


def test_gather_bookings_text_reports_no_data_when_no_snapshot():
    with session_scope() as session:
        session.query(DaiOakesBookingsSnapshotRecord).delete()
        text = dai_oakes_intelligence._gather_bookings_text(session)
    assert text == dai_oakes_intelligence._NO_DATA_TEXT


def test_gather_bookings_text_uses_latest_snapshot():
    with session_scope() as session:
        session.add(DaiOakesBookingsSnapshotRecord(total_bookings=10, today_count=1, next_7_days_count=3))
        session.add(DaiOakesBookingsSnapshotRecord(total_bookings=42, today_count=2, next_7_days_count=9))
    with session_scope() as session:
        text = dai_oakes_intelligence._gather_bookings_text(session)
    assert "total de marcações: 42" in text


def test_gather_clients_text_uses_latest_snapshot():
    with session_scope() as session:
        session.add(DaiOakesClientsSnapshotRecord(total_clients=100, new_clients_last_30_days=5))
        session.add(DaiOakesClientsSnapshotRecord(total_clients=250, new_clients_last_30_days=14))
    with session_scope() as session:
        text = dai_oakes_intelligence._gather_clients_text(session)
    assert "total de clientes: 250" in text
    assert "novos clientes (últimos 30 dias): 14" in text


def test_gather_system_health_text_uses_latest_snapshot():
    with session_scope() as session:
        session.add(DaiOakesSystemHealthSnapshotRecord(webhooks_failed_last_24h=1, webhooks_failed_total=3, webhooks_processed_total=100))
    with session_scope() as session:
        text = dai_oakes_intelligence._gather_system_health_text(session)
    assert "1 falhas nas últimas 24h" in text


# --- run_weekly_dai_oakes_intelligence_sweep --------------------------------------------

def test_run_weekly_sweep_persists_all_five_areas_and_sends_telegram(monkeypatch):
    monkeypatch.setattr(dai_oakes_intelligence, "_call_model", lambda client, prompt: _fake_message(_fake_submission()))
    telegram_calls = []
    monkeypatch.setattr(dai_oakes_intelligence, "send_telegram_message", lambda text: telegram_calls.append(text) or True)

    dai_oakes_intelligence.run_weekly_dai_oakes_intelligence_sweep()

    report = _latest_report()
    assert report.status == "completed"
    assert report.payments_summary == "121 faturas, 113 pagas."
    assert report.bookings_summary == "42 marcações no total."
    assert report.clients_summary == "250 clientes, 14 novos."
    assert report.system_health_summary == "tudo saudável."
    assert report.alerts_summary == "sem novidades esta semana"
    assert report.telegram_sent is True
    assert len(telegram_calls) == 1
    assert "DAI OAKES" in telegram_calls[0]


def test_run_weekly_sweep_records_report_even_if_telegram_fails(monkeypatch):
    monkeypatch.setattr(dai_oakes_intelligence, "_call_model", lambda client, prompt: _fake_message(_fake_submission()))

    def _boom(text):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(dai_oakes_intelligence, "send_telegram_message", _boom)

    dai_oakes_intelligence.run_weekly_dai_oakes_intelligence_sweep()  # must not raise

    report = _latest_report()
    assert report.status == "completed"
    assert report.telegram_sent is False


def test_run_weekly_sweep_no_tool_use_is_recorded_as_failed(monkeypatch):
    monkeypatch.setattr(dai_oakes_intelligence, "_call_model", lambda client, prompt: SimpleNamespace(
        content=[{"type": "text", "text": "uncertain"}], stop_reason="end_turn", input_tokens=10, output_tokens=5,
    ))

    dai_oakes_intelligence.run_weekly_dai_oakes_intelligence_sweep()

    report = _latest_report()
    assert report.status == "failed"
    assert "end_turn" in report.error
    assert report.telegram_sent is False


def test_run_weekly_sweep_model_exception_is_recorded_as_failed_not_raised(monkeypatch):
    def _boom(client, prompt):
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr(dai_oakes_intelligence, "_call_model", _boom)

    dai_oakes_intelligence.run_weekly_dai_oakes_intelligence_sweep()  # must not raise

    report = _latest_report()
    assert report.status == "failed"
    assert "simulated API failure" in report.error


def test_run_weekly_sweep_never_touches_the_dai_oakes_api_directly(monkeypatch):
    # This agent's whole safety property: it has zero network dependency on Dai Oakes --
    # it only ever reads rows Back Office already synced. Proven by never patching
    # daioakes_client at all here and still getting a normal completed report.
    monkeypatch.setattr(dai_oakes_intelligence, "_call_model", lambda client, prompt: _fake_message(_fake_submission()))
    monkeypatch.setattr(dai_oakes_intelligence, "send_telegram_message", lambda text: True)

    dai_oakes_intelligence.run_weekly_dai_oakes_intelligence_sweep()  # must not raise, must not need network

    assert _latest_report().status == "completed"


# --- run_sweep gating --------------------------------------------------------------------

def test_run_sweep_without_credentials_never_calls_model(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def spy(client, prompt):
        raise AssertionError("_call_model must not be called without a provider configured")

    monkeypatch.setattr(dai_oakes_intelligence, "_call_model", spy)

    dai_oakes_intelligence.run_sweep()  # must not raise, must not call the model


# --- start_dai_oakes_intelligence ---------------------------------------------------------

def test_start_dai_oakes_intelligence_does_nothing_without_credentials(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(dai_oakes_intelligence, "_started", False)

    dai_oakes_intelligence.start_dai_oakes_intelligence()

    assert dai_oakes_intelligence._started is False


def test_start_dai_oakes_intelligence_starts_a_thread_when_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr(dai_oakes_intelligence, "_started", False)
    started_threads = []

    class _FakeThread:
        def __init__(self, target, name, daemon):
            started_threads.append((target, name, daemon))

        def start(self):
            pass  # deliberately never actually run the loop -- no real thread, no network

    monkeypatch.setattr(dai_oakes_intelligence.threading, "Thread", _FakeThread)

    dai_oakes_intelligence.start_dai_oakes_intelligence()

    assert dai_oakes_intelligence._started is True
    assert len(started_threads) == 1
    assert started_threads[0][1] == "volt-core-dai-oakes-intelligence"
