import os
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import usage_ledger
from app.agents import agent_inbox, approvals_rollup, chief_of_staff, output_auditor
from app.db import session_scope
from app.main import app
from app.models import (DailyBriefingRecord, LLMUsageRecord, MarketingContentRecord, OutputAuditFindingRecord, SalesLeadRecord,
                        SalesOutreachDraftRecord)


def _clear():
    # The test DB is shared across the whole suite and other departments' tests leave
    # pending drafts behind, so isolate: clear every approval source plus this layer's tables.
    with session_scope() as s:
        for m in (LLMUsageRecord, OutputAuditFindingRecord, *[model for _, model, _ in approvals_rollup.SOURCES]):
            s.query(m).delete()


def _lead() -> int:
    with session_scope() as s:
        lead = SalesLeadRecord(lead_type="b2b_partner", name="Gov Test", email="gov@example.com", status="qualified", consent_basis="test")
        s.add(lead); s.flush()
        return lead.id


def _draft(body, subject="Olá", status="pending_approval", created_at=None):
    with session_scope() as s:
        d = SalesOutreachDraftRecord(lead_id=_lead(), subject=subject, body=body, status=status)
        if created_at:
            d.created_at = created_at
        s.add(d); s.flush()
        return d.id


# ---- usage ledger / cost governor
def test_usage_report_derives_cost_only_when_price_known(monkeypatch):
    _clear()
    usage_ledger.record_usage(agent="sales_agent", model="m-known", input_tokens=1_000_000, output_tokens=500_000)
    usage_ledger.record_usage(agent="customer_agent", model="m-unknown", input_tokens=10, output_tokens=5)
    monkeypatch.setenv("VOLT_LLM_PRICES", '{"m-known": {"input_per_mtok": 2.0, "output_per_mtok": 4.0}}')
    report = usage_ledger.usage_report(days=1)
    assert report["by_agent"]["sales_agent"]["cost"] == 4.0
    assert report["by_agent"]["customer_agent"]["cost"] is None
    assert report["cost"] is None and "preço em falta" in report["cost_note"]


def test_budget_guard_is_off_by_default_and_blocks_when_set(monkeypatch):
    _clear()
    monkeypatch.delenv("VOLT_LLM_DAILY_TOKEN_BUDGET", raising=False)
    usage_ledger.record_usage(agent="a", model="m", input_tokens=900, output_tokens=200)
    assert usage_ledger.budget_exceeded() is None
    monkeypatch.setenv("VOLT_LLM_DAILY_TOKEN_BUDGET", "1000")
    assert "orçamento diário de tokens" in usage_ledger.budget_exceeded()


def test_money_budget_fails_open_when_price_missing(monkeypatch):
    _clear()
    usage_ledger.record_usage(agent="a", model="m", input_tokens=10**9, output_tokens=0)
    monkeypatch.setenv("VOLT_LLM_DAILY_BUDGET", "1")
    monkeypatch.delenv("VOLT_LLM_PRICES", raising=False)
    assert usage_ledger.budget_exceeded() is None


def test_llm_client_records_usage_and_respects_budget(monkeypatch):
    from app import llm_client
    _clear()
    client = llm_client.LLMClient(provider="deepseek", api_key="x", base_url="http://x")
    fake = llm_client.ModelResponse(content=[], stop_reason="end_turn", input_tokens=7, output_tokens=3)
    monkeypatch.setattr(client, "_call_openai_compatible", lambda *a, **k: fake)
    client.call(model="m1", max_tokens=10, system="s", messages=[], tools=[])
    with session_scope() as s:
        row = s.query(LLMUsageRecord).one()
        assert (row.model, row.input_tokens, row.output_tokens) == ("m1", 7, 3)
        assert row.agent == "test_governance_layer"
    monkeypatch.setenv("VOLT_LLM_DAILY_TOKEN_BUDGET", "5")
    try:
        client.call(model="m1", max_tokens=10, system="s", messages=[], tools=[])
        assert False, "expected budget error"
    except llm_client.LLMBudgetError:
        pass


# ---- approvals rollup
def test_rollup_flags_stale_items_across_sources():
    _clear()
    old = datetime.now(timezone.utc) - timedelta(hours=100)
    _draft("corpo", subject="Velho", created_at=old)
    _draft("corpo", subject="Novo")
    _draft("corpo", subject="Já aprovado", status="approved")
    with session_scope() as s:
        s.add(MarketingContentRecord(content_type="post", format="linkedin", audience="b2b", title="T", body="b", status="pending_approval"))
    r = approvals_rollup.pending_approvals()
    assert r["total"] == 3 and r["stale"] == 1
    assert r["by_source"] == {"sales_outreach": 2, "marketing": 1}
    assert r["items"][0]["summary"] == "Velho"


# ---- output auditor (parent) + sub-checkers
def test_secret_checker_flags_and_redacts():
    f = output_auditor.secret_checker("a chave é sk-abcdefghijklmnopqrstuvwx e password: hunter2hunter2")
    assert {x["rule"] for x in f} == {"secret_api_key", "secret_assignment"}
    assert all(x["excerpt"] == "[redacted]" and x["severity"] == "critical" for x in f)


def test_content_checker_rules():
    rules = {x["rule"] for x in output_auditor.content_checker("Custa €1.200, resultado garantido. IBAN NL91 ABNA 0417 1643 00, ligue +31 6 1234 5678")}
    assert rules == {"price_mentioned", "absolute_claim", "iban_present", "phone_present"}
    assert output_auditor.content_checker("Texto neutro sem nada de especial.") == []


def test_audit_run_is_idempotent_and_ignores_non_pending():
    _clear()
    _draft("Use esta chave sk-abcdefghijklmnopqrstuvwx já")
    _draft("sk-abcdefghijklmnopqrstuvwx", status="approved")
    first = output_auditor.run_output_audit()
    second = output_auditor.run_output_audit()
    assert first["new_findings"] == 1 and first["open_critical"] == 1
    assert second["new_findings"] == 0 and second["open"] == 1
    with session_scope() as s:
        assert s.query(OutputAuditFindingRecord).one().excerpt == "[redacted]"


# ---- chief of staff
def test_briefing_surfaces_attention_items(monkeypatch):
    _clear()
    _draft("segredo sk-abcdefghijklmnopqrstuvwx")
    output_auditor.run_output_audit()
    b = chief_of_staff.build_briefing()
    assert b["attention_count"] >= 1 and "crítico" in b["summary"]
    assert b["data"]["open_critical"] == 1


def test_daily_cycle_runs_inline_when_inbox_worker_is_not_running(monkeypatch):
    _clear()
    monkeypatch.setattr(agent_inbox, "_started", False)
    with TestClient(app) as client:
        result = client.post("/api/governance/daily-cycle").json()
        assert result["mode"] == "inline" and result["ran"][-1] == "daily_briefing"
        briefings = client.get("/api/governance/briefings").json()
        assert briefings and briefings[0]["summary"].startswith("Briefing diário")


def test_daily_cycle_posts_in_order_when_worker_running(monkeypatch):
    posted = []
    monkeypatch.setattr(agent_inbox, "_started", True)
    monkeypatch.setattr(agent_inbox, "post_message", lambda **kw: posted.append(kw["message_type"]))
    result = chief_of_staff.start_daily_cycle()
    assert result["mode"] == "inbox" and posted == ["cost_report", "output_audit", "approvals_rollup", "daily_briefing"]


def test_inbox_dispatch_routes_governance_types():
    _clear()
    agent_inbox._dispatch("daily_briefing", {})
    with session_scope() as s:
        assert s.query(DailyBriefingRecord).count() >= 1


def test_dismiss_finding_endpoint():
    _clear()
    _draft("sk-abcdefghijklmnopqrstuvwx")
    output_auditor.run_output_audit()
    with TestClient(app) as client:
        fid = client.get("/api/governance/audit-findings").json()[0]["id"]
        assert client.post(f"/api/governance/audit-findings/{fid}/dismiss").json()["status"] == "dismissed"
        assert client.get("/api/governance/audit-findings").json() == []
        assert client.post("/api/governance/audit-findings/999999/dismiss").status_code == 404
