from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx

_API_BASE = "https://backboard.railway.com/graphql/v2"


@dataclass(frozen=True)
class ProductionSweepJob:
    system: str
    environment: str
    project_id: str
    service_id: str
    environment_id: str


def _railway_request(query: str, variables: dict) -> dict | None:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    # Returns None only on a transport-level failure (DNS/timeout/connection refused).
    token = os.getenv("RAILWAY_TOKEN")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(_API_BASE, json={"query": query, "variables": variables}, headers=headers)
    except httpx.HTTPError:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _graphql_errors(payload: dict | None) -> str | None:
    # CRITICAL, confirmed from Railway's docs: an auth failure comes back as HTTP 200
    # with a populated "errors" array (message "Not Authorized"), never a 401/403. Every
    # caller of _railway_request must check this, not just get this far.
    if payload is None:
        return "Railway API request failed (network/transport error)"
    errors = payload.get("errors")
    if errors:
        return "; ".join(e.get("message", "unknown error") for e in errors)[:500]
    return None


def _window(hours: int) -> tuple[str, str]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    return start.isoformat(), end.isoformat()


# NOTE ON VERIFICATION STATUS: both queries below are now confirmed against the live API
# via schema introspection with a real RAILWAY_TOKEN (2026-09-07). get_service_resource_usage's
# shape was already correct -- CPU_USAGE/MEMORY_USAGE_GB are real MetricMeasurement enum
# values. get_service_http_metrics was NOT: the MetricMeasurement enum has no HTTP-related
# values at all (only CPU/memory/disk/network/agent-spend) -- HTTP metrics live under their
# own dedicated queries (httpMetricsGroupedByStatus, httpDurationMetrics), confirmed working
# below. Both still fail closed (a GraphQL validation error surfaces as a normal
# {"error": ...} tool result, never an exception).

_METRICS_QUERY = """
query sweepMetrics($projectId: String!, $serviceId: String!, $environmentId: String!, $measurements: [MetricMeasurement!]!, $startDate: DateTime!, $endDate: DateTime!, $sampleRateSeconds: Int) {
  metrics(projectId: $projectId, serviceId: $serviceId, environmentId: $environmentId, measurements: $measurements, startDate: $startDate, endDate: $endDate, sampleRateSeconds: $sampleRateSeconds) {
    measurement
    values { ts value }
  }
}
"""

_HTTP_METRICS_BY_STATUS_QUERY = """
query sweepHttpMetricsByStatus($startDate: DateTime!, $endDate: DateTime!, $environmentId: String!, $serviceId: String!, $stepSeconds: Int) {
  httpMetricsGroupedByStatus(startDate: $startDate, endDate: $endDate, environmentId: $environmentId, serviceId: $serviceId, stepSeconds: $stepSeconds) {
    statusCode
    samples { ts value }
  }
}
"""

_HTTP_DURATION_QUERY = """
query sweepHttpDuration($startDate: DateTime!, $endDate: DateTime!, $environmentId: String!, $serviceId: String!, $stepSeconds: Int) {
  httpDurationMetrics(startDate: $startDate, endDate: $endDate, environmentId: $environmentId, serviceId: $serviceId, stepSeconds: $stepSeconds) {
    samples { ts p50 p90 p95 p99 }
  }
}
"""


def get_service_http_metrics(job: ProductionSweepJob, window_hours: int = 6) -> dict:
    window_hours = max(1, min(int(window_hours), 168))
    start, end = _window(window_hours)
    variables = {
        "startDate": start, "endDate": end,
        "environmentId": job.environment_id, "serviceId": job.service_id,
        "stepSeconds": 900,
    }

    status_payload = _railway_request(_HTTP_METRICS_BY_STATUS_QUERY, variables)
    error = _graphql_errors(status_payload)
    if error:
        return {"error": error}

    duration_payload = _railway_request(_HTTP_DURATION_QUERY, variables)
    error = _graphql_errors(duration_payload)
    if error:
        return {"error": error}

    by_status = (status_payload or {}).get("data", {}).get("httpMetricsGroupedByStatus") or []
    total_requests = 0
    error_requests = 0
    for series in by_status:
        status_code = series.get("statusCode")
        count = sum((sample.get("value") or 0) for sample in series.get("samples") or [])
        total_requests += count
        if isinstance(status_code, int) and status_code >= 500:
            error_requests += count
    error_rate = round(error_requests / total_requests, 4) if total_requests else 0.0

    duration_samples = (duration_payload or {}).get("data", {}).get("httpDurationMetrics", {}).get("samples") or []
    latest = duration_samples[-1] if duration_samples else {}

    return {
        "window_hours": window_hours,
        "total_requests": total_requests,
        "error_requests": error_requests,
        "error_rate": error_rate,
        "latest_latency_p50_ms": latest.get("p50"),
        "latest_latency_p90_ms": latest.get("p90"),
        "latest_latency_p95_ms": latest.get("p95"),
        "latest_latency_p99_ms": latest.get("p99"),
    }


def get_service_resource_usage(job: ProductionSweepJob, window_hours: int = 6) -> dict:
    window_hours = max(1, min(int(window_hours), 168))
    start, end = _window(window_hours)
    payload = _railway_request(_METRICS_QUERY, {
        "projectId": job.project_id, "serviceId": job.service_id, "environmentId": job.environment_id,
        "measurements": ["CPU_USAGE", "MEMORY_USAGE_GB"],
        "startDate": start, "endDate": end, "sampleRateSeconds": 300,
    })
    error = _graphql_errors(payload)
    if error:
        return {"error": error}
    series = (payload or {}).get("data", {}).get("metrics") or []
    return {"window_hours": window_hours, "series": series}


# This one IS confirmed against Railway's own documented API Cookbook (deployments
# query with a DeploymentListInput, edges/node pagination) -- safe to trust as-is.
_DEPLOYMENTS_QUERY = """
query sweepDeployments($input: DeploymentListInput!, $first: Int!) {
  deployments(input: $input, first: $first) {
    edges { node { id status createdAt } }
  }
}
"""


def get_recent_deployments(job: ProductionSweepJob, limit: int = 5) -> dict:
    limit = max(1, min(int(limit), 20))
    payload = _railway_request(_DEPLOYMENTS_QUERY, {
        "input": {"projectId": job.project_id, "serviceId": job.service_id, "environmentId": job.environment_id},
        "first": limit,
    })
    error = _graphql_errors(payload)
    if error:
        return {"error": error}
    edges = (payload or {}).get("data", {}).get("deployments", {}).get("edges") or []
    return {"deployments": [edge.get("node", {}) for edge in edges]}


TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "get_service_http_metrics": get_service_http_metrics,
    "get_service_resource_usage": get_service_resource_usage,
    "get_recent_deployments": get_recent_deployments,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_service_http_metrics",
        "description": "Read this system's real HTTP error rate (5xx share) and latency percentiles (p50/p95/p99) over a recent time window. A single elevated data point is normal noise -- look for a sustained trend across the window.",
        "input_schema": {
            "type": "object",
            "properties": {"window_hours": {"type": "integer", "description": "Hours of history to look at (default 6, max 168)."}},
            "required": [],
        },
    },
    {
        "name": "get_service_resource_usage",
        "description": "Read this system's real CPU and memory usage over a recent time window.",
        "input_schema": {
            "type": "object",
            "properties": {"window_hours": {"type": "integer", "description": "Hours of history to look at (default 6, max 168)."}},
            "required": [],
        },
    },
    {
        "name": "get_recent_deployments",
        "description": "Read recent deployment status for this system -- useful to check whether a recent deploy correlates with a change in behavior.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Max deployments to return (default 5, max 20)."}},
            "required": [],
        },
    },
]
