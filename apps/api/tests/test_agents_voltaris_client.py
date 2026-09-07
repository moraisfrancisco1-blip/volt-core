from app.agents import external_connector, voltaris_client


def test_get_system_health_calls_the_real_confirmed_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(external_connector, "get", lambda config, path, **kw: seen.update(config=config, path=path) or {"data": {"status": "ok"}})
    result = voltaris_client.get_system_health()
    assert seen["path"] == "/api/admin/system-health"
    assert seen["config"].api_key_env_var == "VOLTARIS_SERVICE_KEY"
    assert result == {"data": {"status": "ok"}}


def test_get_production_readiness_calls_the_real_confirmed_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(external_connector, "get", lambda config, path, **kw: seen.update(path=path) or {"data": {}})
    voltaris_client.get_production_readiness()
    assert seen["path"] == "/api/admin/production-readiness"


def test_get_alerts_calls_the_real_confirmed_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(external_connector, "get", lambda config, path, **kw: seen.update(path=path) or {"data": []})
    voltaris_client.get_alerts()
    assert seen["path"] == "/api/alerts"


def test_get_tenants_calls_the_real_confirmed_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(external_connector, "get", lambda config, path, **kw: seen.update(path=path) or {"data": []})
    voltaris_client.get_tenants()
    assert seen["path"] == "/api/admin/tenants"


def test_config_uses_the_real_confirmed_base_url_by_default(monkeypatch):
    monkeypatch.delenv("VOLTARIS_BASE_URL", raising=False)
    # Re-import-free check: the module-level _CONFIG is built once at import time from
    # the env var read above, so this asserts the fallback baked in at that point.
    import importlib
    from app.agents import voltaris_client as vc
    importlib.reload(vc)
    assert vc._CONFIG.base_url == "https://voltarisos-production.up.railway.app"
    importlib.reload(vc)  # restore a clean module state for any test that runs after this one
