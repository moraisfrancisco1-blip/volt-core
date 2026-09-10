from app.agents import daioakes_client, external_connector


def test_get_payment_control_calls_the_confirmed_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(external_connector, "get", lambda config, path, **kw: seen.update(config=config, path=path) or {"data": []})
    result = daioakes_client.get_payment_control()
    assert seen["path"] == "/api/service/payment-control"
    assert seen["config"].api_key_env_var == "VOLT_CORE_SERVICE_KEY_DAIOAKES"
    assert seen["config"].api_key_header == "X-Volt-Core-Key"
    assert seen["config"].api_key_scheme is None
    assert result == {"data": []}


# --- Round 2: bookings-summary / clients-summary / system-health -- same key, same
# /api/service/* boundary, still GET-only by construction of external_connector.get() ----

def test_get_bookings_summary_calls_the_service_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(external_connector, "get", lambda config, path, **kw: seen.update(config=config, path=path) or {"data": {}})
    result = daioakes_client.get_bookings_summary()
    assert seen["path"] == "/api/service/bookings-summary"
    assert seen["config"].api_key_env_var == "VOLT_CORE_SERVICE_KEY_DAIOAKES"
    assert result == {"data": {}}


def test_get_clients_summary_calls_the_service_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(external_connector, "get", lambda config, path, **kw: seen.update(config=config, path=path) or {"data": {}})
    daioakes_client.get_clients_summary()
    assert seen["path"] == "/api/service/clients-summary"


def test_get_system_health_calls_the_service_path(monkeypatch):
    seen = {}
    monkeypatch.setattr(external_connector, "get", lambda config, path, **kw: seen.update(config=config, path=path) or {"data": {}})
    daioakes_client.get_system_health()
    assert seen["path"] == "/api/service/system-health"
