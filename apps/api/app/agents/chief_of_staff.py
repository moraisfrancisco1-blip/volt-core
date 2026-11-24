from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .. import usage_ledger
from ..db import session_scope
from ..models import AgentInboxRecord, AuditRecord, DailyBriefingRecord, OutputAuditFindingRecord, ProjectRecord
from . import agent_inbox, approvals_rollup, output_auditor, project_agent

# Chief of Staff: the top of a three-level hierarchy, built on the existing agent inbox.
#   Level 1  chief_of_staff   starts the daily cycle and writes the final briefing
#   Level 2  sub-agents       cost_report, output_audit, approvals_rollup, and one
#                             project_steward per active project ("project:<key>")
#   Level 3  inside output_audit: secret_checker + content_checker
#            inside each steward: repo_health_checker, exposure_checker, kb_sync
# Delegation uses the inbox as-is. The inbox worker is serial and FIFO, so posting the
# three sub-agent messages and THEN "daily_briefing" guarantees the briefing runs only after
# they have finished -- no new scheduler, no waiting, no extra threads.
# Everything is deterministic: no LLM key needed and no API cost.

SUB_AGENT_MESSAGES = ["cost_report", "output_audit", "approvals_rollup"]


def _active_project_keys() -> list[str]:
    with session_scope() as session:
        return list(session.scalars(select(ProjectRecord.key).where(ProjectRecord.status == "active").order_by(ProjectRecord.key)).all())


def start_daily_cycle() -> dict:
    # Stewards run after the department sub-agents and before the briefing.
    steps: list[tuple[str, dict]] = [(m, {}) for m in SUB_AGENT_MESSAGES]
    steps += [("project_steward", {"project_key": key}) for key in _active_project_keys()]
    steps.append(("daily_briefing", {}))
    labels = [m if m != "project_steward" else f"project_steward:{p['project_key']}" for m, p in steps]
    if agent_inbox.is_worker_running():
        for (message_type, payload), label in zip(steps, labels):
            agent_inbox.post_message(sender="chief_of_staff", recipient=message_type, message_type=message_type, payload=payload, content=f"daily cycle: {label}")
        return {"mode": "inbox", "queued": labels}
    # The inbox worker only runs when an LLM key is configured. These agents are
    # deterministic and need no key, so with the API paused run the same steps inline,
    # in the same order, instead of leaving messages nobody will ever read.
    handlers = {"cost_report": run_cost_report, "output_audit": run_output_audit, "approvals_rollup": run_approvals_rollup,
                "project_steward": run_project_steward, "daily_briefing": run_daily_briefing}
    for message_type, payload in steps:
        try:
            handlers[message_type](payload)
        except Exception as exc:  # one failing steward must not stop the briefing
            with session_scope() as session:
                session.add(AuditRecord(type="daily_cycle_step_failed", reference_id=message_type, detail=f"{type(exc).__name__}: {exc}"[:500]))
    return {"mode": "inline", "ran": labels}


def run_project_steward(payload: dict) -> None:
    project_agent.run_project_steward(str(payload.get("project_key", "")))


def run_cost_report(_payload: dict) -> None:
    report = usage_ledger.usage_report(days=1)
    with session_scope() as session:
        session.add(AuditRecord(type="cost_report_completed", detail=f"calls={report['calls']} tokens={report['input_tokens'] + report['output_tokens']}"))


def run_approvals_rollup(_payload: dict) -> None:
    rollup = approvals_rollup.pending_approvals()
    with session_scope() as session:
        session.add(AuditRecord(type="approvals_rollup_completed", detail=f"total={rollup['total']} stale={rollup['stale']}"))


def run_output_audit(_payload: dict) -> None:
    output_auditor.run_output_audit()


def _failed_inbox_last_24h(now: datetime) -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(select(AgentInboxRecord).where(AgentInboxRecord.error.is_not(None), AgentInboxRecord.created_at >= now - timedelta(days=1))).all()
        return [{"message_type": r.message_type, "error": (r.error or "")[:160]} for r in rows]


def build_briefing(*, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    cost = usage_ledger.usage_report(days=1, now=now)
    approvals = approvals_rollup.pending_approvals(now=now)
    with session_scope() as session:
        open_findings = session.scalars(select(OutputAuditFindingRecord).where(OutputAuditFindingRecord.status == "open")).all()
        critical = sum(1 for f in open_findings if f.severity == "critical")
        findings_total = len(open_findings)
    failures = _failed_inbox_last_24h(now)
    budget_reason = usage_ledger.budget_exceeded(now=now)

    projects = project_agent.latest_health_by_project()
    flagged = [p for p in projects if set(p["flags"]) & project_agent.ATTENTION_FLAGS]
    attention: list[str] = []
    for p in flagged:
        attention.append(f"Projeto {p['name']}: " + ", ".join(sorted(set(p["flags"]) & project_agent.ATTENTION_FLAGS)) + ".")
    if critical:
        attention.append(f"{critical} achado(s) crítico(s) do auditor em rascunhos pendentes (segredo ou IBAN): rever antes de aprovar.")
    if budget_reason:
        attention.append(f"Agentes bloqueados pelo orçamento: {budget_reason}.")
    if approvals["stale"]:
        attention.append(f"{approvals['stale']} aprovação(ões) parada(s) há mais de {approvals['stale_after_hours']}h.")
    if failures:
        attention.append(f"{len(failures)} mensagem(ns) de agentes falharam nas últimas 24h.")

    cost_line = (f"{cost['calls']} chamadas LLM, {cost['input_tokens'] + cost['output_tokens']} tokens" +
                 (f", custo {cost['cost']}" if cost["cost"] is not None else (", custo desconhecido (falta VOLT_LLM_PRICES)" if cost["calls"] else "")))
    lines = [
        "Briefing diário do Volt Core",
        f"Atenção: {len(attention)} ponto(s)." if attention else "Atenção: nada urgente.",
        *[f"- {a}" for a in attention],
        f"Aprovações pendentes: {approvals['total']} ({approvals['by_source'] or 'nenhuma'}).",
        f"Auditor: {findings_total} achado(s) em aberto.",
        f"LLM nas últimas 24h: {cost_line}.",
        f"Projetos: {len(projects)} ativos, {sum(1 for p in projects if p['checked'])} verificados, {sum(p['kb_entries'] for p in projects)} entradas na base de conhecimento.",
    ]
    return {"summary": "\n".join(lines), "attention_count": len(attention),
            "data": {"cost": cost, "approvals": {k: approvals[k] for k in ("total", "stale", "by_source")}, "open_findings": findings_total, "open_critical": critical, "failed_messages": failures, "projects": projects}}


def run_daily_briefing(_payload: dict) -> int:
    briefing = build_briefing()
    with session_scope() as session:
        record = DailyBriefingRecord(summary=briefing["summary"], data=briefing["data"], attention_count=briefing["attention_count"])
        session.add(record)
        session.flush()
        session.add(AuditRecord(type="daily_briefing_completed", reference_id=str(record.id), detail=f"attention={record.attention_count}"))
        return record.id
