from app.agents import database_tools
from app.agents.database_tools import DatabaseJob


def _job() -> DatabaseJob:
    return DatabaseJob(event_id=1, escalation_id=2, system="volt-core", environment="production", priority="P2", parent_investigation_id=9)


def test_get_running_queries_success(monkeypatch):
    monkeypatch.setattr(database_tools, "_run_diagnostic_query", lambda name, params: {"rows": [{"pid": 1, "query": "select 1"}]})
    result = database_tools.get_running_queries(_job())
    assert result == {"queries": [{"pid": 1, "query": "select 1"}]}


def test_get_running_queries_clamps_limit(monkeypatch):
    seen = {}

    def fake(name, params):
        seen.update(params)
        return {"rows": []}

    monkeypatch.setattr(database_tools, "_run_diagnostic_query", fake)
    database_tools.get_running_queries(_job(), limit=500)
    assert seen["limit"] == 100
    database_tools.get_running_queries(_job(), limit=-5)
    assert seen["limit"] == 1


def test_get_slow_query_stats_success(monkeypatch):
    monkeypatch.setattr(database_tools, "_run_diagnostic_query", lambda name, params: {"rows": [{"query": "select 2", "mean_exec_time": 12.5}]})
    result = database_tools.get_slow_query_stats(_job())
    assert result["extension_installed"] is True
    assert result["queries"] == [{"query": "select 2", "mean_exec_time": 12.5}]


def test_get_slow_query_stats_missing_extension_is_not_an_exception(monkeypatch):
    monkeypatch.setattr(
        database_tools, "_run_diagnostic_query",
        lambda name, params: {"error": 'relation "pg_stat_statements" does not exist'},
    )
    result = database_tools.get_slow_query_stats(_job())
    assert result["extension_installed"] is False
    assert "get_running_queries" in result["note"]


def test_get_slow_query_stats_other_sql_error_is_not_confused_with_missing_extension(monkeypatch):
    monkeypatch.setattr(database_tools, "_run_diagnostic_query", lambda name, params: {"error": "connection timed out"})
    result = database_tools.get_slow_query_stats(_job())
    assert "extension_installed" not in result
    assert result == {"error": "connection timed out"}


def test_get_table_health_success(monkeypatch):
    monkeypatch.setattr(database_tools, "_run_diagnostic_query", lambda name, params: {"rows": [{"relname": "events", "n_dead_tup": 50}]})
    result = database_tools.get_table_health(_job())
    assert result == {"tables": [{"relname": "events", "n_dead_tup": 50}]}


def test_get_unused_indexes_success(monkeypatch):
    monkeypatch.setattr(database_tools, "_run_diagnostic_query", lambda name, params: {"rows": [{"index_name": "ix_unused", "idx_scan": 0}]})
    result = database_tools.get_unused_indexes(_job())
    assert result == {"indexes": [{"index_name": "ix_unused", "idx_scan": 0}]}


def test_get_connection_health_success(monkeypatch):
    monkeypatch.setattr(
        database_tools, "_run_diagnostic_query",
        lambda name, params: {"rows": [{"current_connections": 5, "max_connections": 100, "long_idle_in_transaction_count": 0}]},
    )
    result = database_tools.get_connection_health(_job(), idle_minutes=10)
    assert result["idle_minutes_threshold"] == 10
    assert result["current_connections"] == 5
    assert result["max_connections"] == 100


def test_get_connection_health_clamps_idle_minutes(monkeypatch):
    seen = {}

    def fake(name, params):
        seen.update(params)
        return {"rows": [{}]}

    monkeypatch.setattr(database_tools, "_run_diagnostic_query", fake)
    database_tools.get_connection_health(_job(), idle_minutes=999999)
    assert seen["idle_minutes"] == 1440
    database_tools.get_connection_health(_job(), idle_minutes=0)
    assert seen["idle_minutes"] == 1


def test_get_backup_status_no_env_vars_returns_not_checked(monkeypatch):
    for var in ("VOLT_DB_RAILWAY_PROJECT_ID", "VOLT_DB_RAILWAY_SERVICE_ID", "VOLT_DB_RAILWAY_ENVIRONMENT_ID", "RAILWAY_TOKEN"):
        monkeypatch.delenv(var, raising=False)

    result = database_tools.get_backup_status(_job())

    assert result["checked"] is False


def test_get_backup_status_network_failure_returns_not_checked(monkeypatch):
    monkeypatch.setenv("VOLT_DB_RAILWAY_PROJECT_ID", "p1")
    monkeypatch.setenv("VOLT_DB_RAILWAY_SERVICE_ID", "s1")
    monkeypatch.setenv("VOLT_DB_RAILWAY_ENVIRONMENT_ID", "e1")
    monkeypatch.setenv("RAILWAY_TOKEN", "fake-token")
    monkeypatch.setattr(database_tools, "_railway_variables_request", lambda p, s, e: None)

    result = database_tools.get_backup_status(_job())

    assert result == {"checked": False, "error": "Railway API request failed"}


def test_get_backup_status_configured_reports_pitr_configured_and_never_leaks_values(monkeypatch):
    monkeypatch.setenv("VOLT_DB_RAILWAY_PROJECT_ID", "p1")
    monkeypatch.setenv("VOLT_DB_RAILWAY_SERVICE_ID", "s1")
    monkeypatch.setenv("VOLT_DB_RAILWAY_ENVIRONMENT_ID", "e1")
    monkeypatch.setenv("RAILWAY_TOKEN", "fake-token")
    secret_value = "super-secret-postgres-password-do-not-leak"
    monkeypatch.setattr(
        database_tools, "_railway_variables_request",
        lambda p, s, e: {"data": {"variables": {"WAL_ARCHIVE_BUCKET": secret_value, "PGPASSWORD": secret_value}}},
    )

    result = database_tools.get_backup_status(_job())

    assert result["checked"] is True
    assert result["pitr_configured"] is True
    # Regression guard: the real variable VALUE must never appear anywhere in the
    # returned dict, only key presence.
    assert secret_value not in str(result)


def test_get_backup_status_configured_without_wal_archive_reports_not_configured(monkeypatch):
    monkeypatch.setenv("VOLT_DB_RAILWAY_PROJECT_ID", "p1")
    monkeypatch.setenv("VOLT_DB_RAILWAY_SERVICE_ID", "s1")
    monkeypatch.setenv("VOLT_DB_RAILWAY_ENVIRONMENT_ID", "e1")
    monkeypatch.setenv("RAILWAY_TOKEN", "fake-token")
    monkeypatch.setattr(database_tools, "_railway_variables_request", lambda p, s, e: {"data": {"variables": {"SOME_OTHER_VAR": "x"}}})

    result = database_tools.get_backup_status(_job())

    assert result["checked"] is True
    assert result["pitr_configured"] is False
