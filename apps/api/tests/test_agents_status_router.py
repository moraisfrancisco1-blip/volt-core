from app.agents import agent_inbox, deals_agent, market_intelligence, production_monitor, sales_agent
from app.agents.status_router import agents_status
from app.db import session_scope
from app.models import AgentInvestigationRecord, AuditRecord, MarketIntelligenceReportRecord, MonitoringSweepRecord


def _seed_investigation(investigation_type: str, status: str, system: str) -> None:
    with session_scope() as session:
        session.add(AgentInvestigationRecord(
            event_id=1, escalation_id=1, investigation_type=investigation_type,
            system=system, environment="production", priority="P2", status=status,
        ))


def _seed_sweep(status: str, system: str) -> None:
    with session_scope() as session:
        session.add(MonitoringSweepRecord(system=system, environment="production", status=status))


def _seed_report(status: str) -> None:
    with session_scope() as session:
        session.add(MarketIntelligenceReportRecord(status=status))


def test_agents_status_returns_all_eight_agents_with_valid_states(monkeypatch):
    monkeypatch.setattr(agent_inbox, "_current_message_type", None)
    monkeypatch.setattr(production_monitor, "_sweep_in_progress", False)
    monkeypatch.setattr(market_intelligence, "_sweep_in_progress", False)
    monkeypatch.setattr(sales_agent, "_sweep_in_progress", False)
    monkeypatch.setattr(deals_agent, "_sweep_in_progress", False)

    results = {row["agent"]: row for row in agents_status()}

    # Other tests in the same run seed their own investigation/sweep/report/lead/deal
    # rows, so this doesn't assert "no history" -- only that every agent is represented
    # with a well-formed state, which is what a genuinely empty VOLT CORE instance
    # would also see (idle, null last_activity_at) before any incident ever occurs.
    assert set(results.keys()) == {"volt", "dev_debug", "database", "finance", "production_monitor", "market_intelligence", "sales", "deals"}
    for row in results.values():
        assert row["state"] in {"idle", "error", "working"}


def test_latest_failed_investigation_reports_error(monkeypatch):
    monkeypatch.setattr(agent_inbox, "_current_message_type", None)
    monkeypatch.setattr(production_monitor, "_sweep_in_progress", False)
    _seed_investigation("code_diagnosis", "failed", "status-router-dev-debug-error")

    results = {row["agent"]: row for row in agents_status()}

    assert results["dev_debug"]["state"] == "error"
    assert results["dev_debug"]["last_status"] == "failed"
    assert results["dev_debug"]["last_activity_at"] is not None


def test_latest_completed_investigation_after_a_failure_reports_idle(monkeypatch):
    monkeypatch.setattr(agent_inbox, "_current_message_type", None)
    monkeypatch.setattr(production_monitor, "_sweep_in_progress", False)
    _seed_investigation("database_diagnosis", "failed", "status-router-db-idle")
    _seed_investigation("database_diagnosis", "completed", "status-router-db-idle")

    results = {row["agent"]: row for row in agents_status()}

    # Only the MOST RECENT record decides the state -- an old failure must not persist.
    assert results["database"]["state"] == "idle"
    assert results["database"]["last_status"] == "completed"


def test_current_job_type_reports_working(monkeypatch):
    monkeypatch.setattr(agent_inbox, "_current_message_type", "finance_diagnosis")
    monkeypatch.setattr(production_monitor, "_sweep_in_progress", False)

    results = {row["agent"]: row for row in agents_status()}

    assert results["finance"]["state"] == "working"


def test_sweep_in_progress_reports_production_monitor_working(monkeypatch):
    monkeypatch.setattr(agent_inbox, "_current_message_type", None)
    monkeypatch.setattr(production_monitor, "_sweep_in_progress", True)

    results = {row["agent"]: row for row in agents_status()}

    assert results["production_monitor"]["state"] == "working"


def test_latest_failed_sweep_reports_error_when_not_in_progress(monkeypatch):
    monkeypatch.setattr(agent_inbox, "_current_message_type", None)
    monkeypatch.setattr(production_monitor, "_sweep_in_progress", False)
    _seed_sweep("failed", "status-router-sweep-error")

    results = {row["agent"]: row for row in agents_status()}

    assert results["production_monitor"]["state"] == "error"
    assert results["production_monitor"]["last_status"] == "failed"


def test_market_intel_sweep_in_progress_reports_working(monkeypatch):
    monkeypatch.setattr(agent_inbox, "_current_message_type", None)
    monkeypatch.setattr(production_monitor, "_sweep_in_progress", False)
    monkeypatch.setattr(market_intelligence, "_sweep_in_progress", True)

    results = {row["agent"]: row for row in agents_status()}

    assert results["market_intelligence"]["state"] == "working"


def test_latest_failed_report_reports_error_when_not_in_progress(monkeypatch):
    monkeypatch.setattr(agent_inbox, "_current_message_type", None)
    monkeypatch.setattr(production_monitor, "_sweep_in_progress", False)
    monkeypatch.setattr(market_intelligence, "_sweep_in_progress", False)
    _seed_report("failed")

    results = {row["agent"]: row for row in agents_status()}

    assert results["market_intelligence"]["state"] == "error"
    assert results["market_intelligence"]["last_status"] == "failed"


def test_sales_sweep_in_progress_reports_working(monkeypatch):
    monkeypatch.setattr(agent_inbox, "_current_message_type", None)
    monkeypatch.setattr(production_monitor, "_sweep_in_progress", False)
    monkeypatch.setattr(sales_agent, "_sweep_in_progress", True)

    results = {row["agent"]: row for row in agents_status()}

    assert results["sales"]["state"] == "working"


def test_sales_failed_audit_reports_error_when_not_in_progress(monkeypatch):
    monkeypatch.setattr(agent_inbox, "_current_message_type", None)
    monkeypatch.setattr(production_monitor, "_sweep_in_progress", False)
    monkeypatch.setattr(sales_agent, "_sweep_in_progress", False)
    with session_scope() as session:
        session.add(AuditRecord(type="sales_sweep_failed", detail="boom"))

    results = {row["agent"]: row for row in agents_status()}

    assert results["sales"]["state"] == "error"
    assert results["sales"]["last_status"] == "failed"


def test_deals_sweep_in_progress_reports_working(monkeypatch):
    monkeypatch.setattr(agent_inbox, "_current_message_type", None)
    monkeypatch.setattr(production_monitor, "_sweep_in_progress", False)
    monkeypatch.setattr(deals_agent, "_sweep_in_progress", True)

    results = {row["agent"]: row for row in agents_status()}

    assert results["deals"]["state"] == "working"


def test_deals_failed_audit_reports_error_when_not_in_progress(monkeypatch):
    monkeypatch.setattr(agent_inbox, "_current_message_type", None)
    monkeypatch.setattr(production_monitor, "_sweep_in_progress", False)
    monkeypatch.setattr(deals_agent, "_sweep_in_progress", False)
    with session_scope() as session:
        session.add(AuditRecord(type="deals_sweep_failed", detail="boom"))

    results = {row["agent"]: row for row in agents_status()}

    assert results["deals"]["state"] == "error"
    assert results["deals"]["last_status"] == "failed"
