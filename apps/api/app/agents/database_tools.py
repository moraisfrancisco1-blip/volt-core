from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..db import session_scope

_RAILWAY_API_BASE = "https://backboard.railway.com/graphql/v2"


@dataclass(frozen=True)
class DatabaseJob:
    event_id: int
    escalation_id: int
    system: str
    environment: str
    priority: str
    parent_investigation_id: int


_QUERIES: dict[str, str] = {
    "running_queries": """
        SELECT pid, usename, application_name, state,
               EXTRACT(EPOCH FROM (now() - query_start)) AS duration_seconds,
               wait_event_type, wait_event, left(query, 500) AS query
        FROM pg_stat_activity
        WHERE state != 'idle' AND pid != pg_backend_pid()
        ORDER BY query_start ASC
        LIMIT :limit
    """,
    "slow_queries": """
        SELECT left(query, 500) AS query, calls, total_exec_time, mean_exec_time, rows
        FROM pg_stat_statements
        ORDER BY mean_exec_time DESC
        LIMIT :limit
    """,
    "table_health": """
        SELECT schemaname, relname, n_live_tup, n_dead_tup, seq_scan, idx_scan,
               last_vacuum, last_autovacuum, last_analyze, last_autoanalyze
        FROM pg_stat_user_tables
        ORDER BY n_dead_tup DESC
        LIMIT :limit
    """,
    "unused_indexes": """
        SELECT s.schemaname, s.relname AS table_name, s.indexrelname AS index_name,
               s.idx_scan, pg_relation_size(s.indexrelid) AS index_size_bytes
        FROM pg_stat_user_indexes s
        JOIN pg_index i ON s.indexrelid = i.indexrelid
        WHERE s.idx_scan = 0 AND NOT i.indisunique AND NOT i.indisprimary
        ORDER BY pg_relation_size(s.indexrelid) DESC
        LIMIT :limit
    """,
    "connection_health": """
        SELECT
          (SELECT count(*) FROM pg_stat_activity) AS current_connections,
          (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') AS max_connections,
          (SELECT count(*) FROM pg_stat_activity
             WHERE state = 'idle in transaction'
               AND now() - state_change > (:idle_minutes * INTERVAL '1 minute')
          ) AS long_idle_in_transaction_count
    """,
}


def _run_diagnostic_query(query_name: str, params: dict) -> dict:
    # The single seam tests substitute -- never touches the real database once
    # monkeypatched. A missing extension (e.g. pg_stat_statements) surfaces here as a
    # normal {"error": ...} result for the caller to interpret, never an exception.
    try:
        with session_scope() as session:
            rows = session.execute(text(_QUERIES[query_name]), params).mappings().all()
            return {"rows": [dict(row) for row in rows]}
    except SQLAlchemyError as exc:
        return {"error": str(exc)[:500]}


def get_running_queries(job: DatabaseJob, limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 100))
    result = _run_diagnostic_query("running_queries", {"limit": limit})
    if "error" in result:
        return {"error": result["error"]}
    return {"queries": result["rows"]}


def get_slow_query_stats(job: DatabaseJob, limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 100))
    result = _run_diagnostic_query("slow_queries", {"limit": limit})
    if "error" in result:
        if "pg_stat_statements" in result["error"]:
            return {
                "extension_installed": False,
                "note": "pg_stat_statements is not installed -- historical query stats are unavailable. Use get_running_queries instead.",
            }
        return {"error": result["error"]}
    return {"extension_installed": True, "queries": result["rows"]}


def get_table_health(job: DatabaseJob, limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 100))
    result = _run_diagnostic_query("table_health", {"limit": limit})
    if "error" in result:
        return {"error": result["error"]}
    return {"tables": result["rows"]}


def get_unused_indexes(job: DatabaseJob, limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 100))
    result = _run_diagnostic_query("unused_indexes", {"limit": limit})
    if "error" in result:
        return {"error": result["error"]}
    return {"indexes": result["rows"]}


def get_connection_health(job: DatabaseJob, idle_minutes: int = 5) -> dict:
    idle_minutes = max(1, min(int(idle_minutes), 1440))
    result = _run_diagnostic_query("connection_health", {"idle_minutes": idle_minutes})
    if "error" in result:
        return {"error": result["error"]}
    return {"idle_minutes_threshold": idle_minutes, **(result["rows"][0] if result["rows"] else {})}


def _railway_variables_request(project_id: str, service_id: str, environment_id: str) -> dict | None:
    # Minimal, deliberately duplicated copy of railway_tools.py's seam -- each agent
    # file owns its full seam rather than sharing private helpers across modules.
    # Returns None only on a transport-level failure (DNS/timeout/connection refused).
    token = os.getenv("RAILWAY_TOKEN")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    query = """
    query databaseAgentVariables($projectId: String!, $serviceId: String!, $environmentId: String!) {
      variables(projectId: $projectId, serviceId: $serviceId, environmentId: $environmentId)
    }
    """
    try:
        with httpx.Client(timeout=15) as client:
            response = client.post(
                _RAILWAY_API_BASE,
                json={"query": query, "variables": {"projectId": project_id, "serviceId": service_id, "environmentId": environment_id}},
                headers=headers,
            )
    except httpx.HTTPError:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def get_backup_status(job: DatabaseJob) -> dict:
    project_id = os.getenv("VOLT_DB_RAILWAY_PROJECT_ID")
    service_id = os.getenv("VOLT_DB_RAILWAY_SERVICE_ID")
    environment_id = os.getenv("VOLT_DB_RAILWAY_ENVIRONMENT_ID")
    token = os.getenv("RAILWAY_TOKEN")
    if not (project_id and service_id and environment_id and token):
        return {"checked": False, "reason": "RAILWAY_TOKEN or VOLT_DB_RAILWAY_* not configured"}
    payload = _railway_variables_request(project_id, service_id, environment_id)
    if payload is None or payload.get("errors"):
        return {"checked": False, "error": "Railway API request failed"}
    variable_names = list((payload.get("data", {}).get("variables") or {}).keys())
    # Variable VALUES from this query are never read past this line -- only the
    # presence of keys survives. See the plan's security note: Railway's `variables`
    # query returns real secret values, not just names.
    pitr_configured = any(name.startswith("WAL_ARCHIVE_") for name in variable_names)
    return {
        "checked": True,
        "pitr_configured": pitr_configured,
        "note": (
            "Indicates PITR-related env vars are present, not whether the WAL archiver is "
            "currently healthy -- live archiver status is only visible via `railway postgres "
            "pitr status`, which this agent cannot run."
        ),
    }


# Read-only. No tool here can ever change schema, data, or backups -- that always
# requires explicit human approval, without exception.
TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "get_running_queries": get_running_queries,
    "get_slow_query_stats": get_slow_query_stats,
    "get_table_health": get_table_health,
    "get_unused_indexes": get_unused_indexes,
    "get_connection_health": get_connection_health,
    "get_backup_status": get_backup_status,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_running_queries",
        "description": "Read currently active (non-idle) queries on VOLT CORE's own Postgres: pid, user, state, how long each has been running, and what it's waiting on.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Max queries to return (default 20, max 100)"}},
            "required": [],
        },
    },
    {
        "name": "get_slow_query_stats",
        "description": "Read historical slow-query statistics (call count, total/mean execution time) if the pg_stat_statements extension is installed. If it isn't, this returns extension_installed: false rather than an error -- fall back to get_running_queries for live activity instead.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Max queries to return, ordered by mean execution time (default 20, max 100)"}},
            "required": [],
        },
    },
    {
        "name": "get_table_health",
        "description": "Read per-table health: live/dead row counts, sequential vs index scan counts, and last vacuum/analyze times. High dead-row counts or heavy sequential scanning on a large table are signals worth flagging.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Max tables to return, ordered by dead row count (default 20, max 100)"}},
            "required": [],
        },
    },
    {
        "name": "get_unused_indexes",
        "description": "Read non-unique, non-primary-key indexes that have never been scanned, with their size. A candidate list for removal, never acted on automatically.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Max indexes to return, ordered by size (default 20, max 100)"}},
            "required": [],
        },
    },
    {
        "name": "get_connection_health",
        "description": "Read current connection count against max_connections, and how many sessions are stuck in 'idle in transaction' past a threshold.",
        "input_schema": {
            "type": "object",
            "properties": {"idle_minutes": {"type": "integer", "description": "Minutes a session must have been idle-in-transaction to count as stuck (default 5, max 1440)"}},
            "required": [],
        },
    },
    {
        "name": "get_backup_status",
        "description": "Check whether Point-in-Time Recovery (PITR) backup env vars are configured for VOLT CORE's own Postgres service on Railway. Requires RAILWAY_TOKEN and the VOLT_DB_RAILWAY_* IDs to be configured -- returns checked: false if they aren't, which is not itself evidence of a problem.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]
