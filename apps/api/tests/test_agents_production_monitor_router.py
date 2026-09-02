from app.agents import production_monitor
from app.agents.production_monitor_router import trigger_sweep


def test_trigger_sweep_without_credentials_does_not_start_a_thread(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAILWAY_TOKEN", raising=False)

    def spy():
        raise AssertionError("run_sweep must not be called without both credentials")

    monkeypatch.setattr(production_monitor, "run_sweep", spy)

    result = trigger_sweep()

    assert result["triggered"] is False
    assert "not configured" in result["reason"]


def test_trigger_sweep_with_credentials_starts_a_thread(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key-not-real")
    monkeypatch.setenv("RAILWAY_TOKEN", "fake-token-not-real")
    started_threads = []

    class _FakeThread:
        def __init__(self, target, daemon):
            started_threads.append(target)

        def start(self):
            pass  # deliberately never actually run the sweep -- no real network/LLM calls

    import app.agents.production_monitor_router as production_monitor_router_module
    monkeypatch.setattr(production_monitor_router_module.threading, "Thread", _FakeThread)

    result = trigger_sweep()

    assert result == {"triggered": True}
    assert started_threads == [production_monitor.run_sweep]
