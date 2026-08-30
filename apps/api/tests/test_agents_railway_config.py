from app.agents.railway_config import RailwaySweepTarget, resolve_railway_service, sweep_system_ids


def test_resolve_railway_service_missing_env(monkeypatch):
    monkeypatch.delenv("VOLT_SYSTEM_RAILWAY", raising=False)
    assert resolve_railway_service("voltaris-os") is None


def test_resolve_railway_service_malformed_json(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_RAILWAY", "not-json")
    assert resolve_railway_service("voltaris-os") is None


def test_resolve_railway_service_not_a_dict(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_RAILWAY", "[1, 2, 3]")
    assert resolve_railway_service("voltaris-os") is None


def test_resolve_railway_service_missing_system(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_RAILWAY", '{"other-system": {"projectId": "p", "serviceId": "s", "environmentId": "e"}}')
    assert resolve_railway_service("voltaris-os") is None


def test_resolve_railway_service_missing_required_keys(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_RAILWAY", '{"voltaris-os": {"projectId": "p"}}')
    assert resolve_railway_service("voltaris-os") is None


def test_resolve_railway_service_well_formed(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_RAILWAY", '{"voltaris-os": {"projectId": "p1", "serviceId": "s1", "environmentId": "e1", "environment": "staging"}}')
    result = resolve_railway_service("voltaris-os")
    assert result == RailwaySweepTarget(project_id="p1", service_id="s1", environment_id="e1", environment="staging")


def test_resolve_railway_service_environment_defaults_to_production(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_RAILWAY", '{"voltaris-os": {"projectId": "p1", "serviceId": "s1", "environmentId": "e1"}}')
    result = resolve_railway_service("voltaris-os")
    assert result.environment == "production"


def test_sweep_system_ids_empty_when_unset(monkeypatch):
    monkeypatch.delenv("VOLT_SYSTEM_RAILWAY", raising=False)
    assert sweep_system_ids() == []


def test_sweep_system_ids_returns_keys(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_RAILWAY", '{"voltaris-os": {}, "daiane-oakes-admin": {}}')
    assert sorted(sweep_system_ids()) == ["daiane-oakes-admin", "voltaris-os"]


def test_sweep_system_ids_malformed_json(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_RAILWAY", "{broken")
    assert sweep_system_ids() == []
