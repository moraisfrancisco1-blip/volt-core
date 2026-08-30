from app.agents import railway_tools
from app.agents.railway_tools import ProductionSweepJob


def _job() -> ProductionSweepJob:
    return ProductionSweepJob(system="voltaris-os", environment="production", project_id="p1", service_id="s1", environment_id="e1")


def test_graphql_errors_none_on_transport_failure():
    assert railway_tools._graphql_errors(None) == "Railway API request failed (network/transport error)"


def test_graphql_errors_extracts_errors_array():
    # CRITICAL Railway quirk: an auth failure comes back as HTTP 200 with a populated
    # "errors" array, never a 401/403 -- every caller must check this, not just status.
    payload = {"errors": [{"message": "Not Authorized"}], "data": None}
    assert railway_tools._graphql_errors(payload) == "Not Authorized"


def test_graphql_errors_none_when_clean():
    assert railway_tools._graphql_errors({"data": {"foo": "bar"}}) is None


def test_get_service_http_metrics_success(monkeypatch):
    monkeypatch.setattr(railway_tools, "_railway_request", lambda query, variables: {"data": {"metrics": [{"measurement": "HTTP_ERROR_RATE", "values": [{"ts": 1, "value": 0.0}]}]}})
    result = railway_tools.get_service_http_metrics(_job())
    assert "error" not in result
    assert result["series"][0]["measurement"] == "HTTP_ERROR_RATE"


def test_get_service_http_metrics_auth_failure_surfaces_error(monkeypatch):
    monkeypatch.setattr(railway_tools, "_railway_request", lambda query, variables: {"errors": [{"message": "Not Authorized"}]})
    result = railway_tools.get_service_http_metrics(_job())
    assert result == {"error": "Not Authorized"}


def test_get_service_http_metrics_network_failure(monkeypatch):
    monkeypatch.setattr(railway_tools, "_railway_request", lambda query, variables: None)
    result = railway_tools.get_service_http_metrics(_job())
    assert "network/transport error" in result["error"]


def test_get_service_resource_usage_success(monkeypatch):
    monkeypatch.setattr(railway_tools, "_railway_request", lambda query, variables: {"data": {"metrics": [{"measurement": "CPU_USAGE", "values": []}]}})
    result = railway_tools.get_service_resource_usage(_job())
    assert result["series"][0]["measurement"] == "CPU_USAGE"


def test_get_recent_deployments_success(monkeypatch):
    monkeypatch.setattr(railway_tools, "_railway_request", lambda query, variables: {
        "data": {"deployments": {"edges": [{"node": {"id": "d1", "status": "SUCCESS", "createdAt": "2026-08-30T00:00:00Z"}}]}}
    })
    result = railway_tools.get_recent_deployments(_job())
    assert result["deployments"] == [{"id": "d1", "status": "SUCCESS", "createdAt": "2026-08-30T00:00:00Z"}]


def test_get_recent_deployments_empty(monkeypatch):
    monkeypatch.setattr(railway_tools, "_railway_request", lambda query, variables: {"data": {"deployments": {"edges": []}}})
    result = railway_tools.get_recent_deployments(_job())
    assert result["deployments"] == []


def test_get_recent_deployments_malformed_response_does_not_raise(monkeypatch):
    monkeypatch.setattr(railway_tools, "_railway_request", lambda query, variables: {"data": {}})
    result = railway_tools.get_recent_deployments(_job())
    assert result["deployments"] == []
