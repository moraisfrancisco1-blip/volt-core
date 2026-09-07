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


def _fake_http_metrics_request(status_data=None, duration_data=None, status_error=None, duration_error=None):
    # httpMetricsGroupedByStatus and httpDurationMetrics are two separate queries --
    # dispatch on which one is being asked for, same as the real two-call implementation.
    def fake(query, variables):
        if "httpMetricsGroupedByStatus" in query:
            if status_error:
                return status_error
            return {"data": {"httpMetricsGroupedByStatus": status_data or []}}
        if "httpDurationMetrics" in query:
            if duration_error:
                return duration_error
            return {"data": {"httpDurationMetrics": duration_data or {"samples": []}}}
        raise AssertionError(f"unexpected query: {query}")
    return fake


def test_get_service_http_metrics_success_computes_error_rate_from_status_breakdown(monkeypatch):
    monkeypatch.setattr(railway_tools, "_railway_request", _fake_http_metrics_request(
        status_data=[
            {"statusCode": 200, "samples": [{"ts": 1, "value": 90}, {"ts": 2, "value": 5}]},
            {"statusCode": 500, "samples": [{"ts": 1, "value": 5}]},
        ],
        duration_data={"samples": [{"ts": 1, "p50": 5, "p90": 11, "p95": 13, "p99": 20}, {"ts": 2, "p50": 6, "p90": 12, "p95": 14, "p99": 22}]},
    ))
    result = railway_tools.get_service_http_metrics(_job())
    assert "error" not in result
    assert result["total_requests"] == 100
    assert result["error_requests"] == 5
    assert result["error_rate"] == 0.05
    # Latency reflects the most recent sample, not an average across the window.
    assert result["latest_latency_p50_ms"] == 6
    assert result["latest_latency_p99_ms"] == 22


def test_get_service_http_metrics_no_traffic_reports_zero_rate_not_a_crash(monkeypatch):
    monkeypatch.setattr(railway_tools, "_railway_request", _fake_http_metrics_request(status_data=[], duration_data={"samples": []}))
    result = railway_tools.get_service_http_metrics(_job())
    assert result["total_requests"] == 0
    assert result["error_rate"] == 0.0
    assert result["latest_latency_p50_ms"] is None


def test_get_service_http_metrics_auth_failure_surfaces_error(monkeypatch):
    monkeypatch.setattr(railway_tools, "_railway_request", _fake_http_metrics_request(status_error={"errors": [{"message": "Not Authorized"}]}))
    result = railway_tools.get_service_http_metrics(_job())
    assert result == {"error": "Not Authorized"}


def test_get_service_http_metrics_network_failure(monkeypatch):
    monkeypatch.setattr(railway_tools, "_railway_request", _fake_http_metrics_request(status_error=None, status_data=None))
    monkeypatch.setattr(railway_tools, "_railway_request", lambda query, variables: None)
    result = railway_tools.get_service_http_metrics(_job())
    assert "network/transport error" in result["error"]


def test_get_service_http_metrics_duration_query_failure_also_surfaces(monkeypatch):
    monkeypatch.setattr(railway_tools, "_railway_request", _fake_http_metrics_request(
        status_data=[{"statusCode": 200, "samples": [{"ts": 1, "value": 10}]}],
        duration_error={"errors": [{"message": "Not Authorized"}]},
    ))
    result = railway_tools.get_service_http_metrics(_job())
    assert result == {"error": "Not Authorized"}


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
