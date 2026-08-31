from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import anthropic

from ..db import session_scope
from ..models import AgentInvestigationRecord, AuditRecord
from .tools import SUBMIT_TOOL_NAME, SUBMIT_TOOL_SCHEMA, TOOL_HANDLERS, TOOL_SCHEMAS, InvestigationJob

MODEL = os.getenv("VOLT_MONITOR_MODEL", "claude-sonnet-4-5")
MAX_TURNS = max(1, int(os.getenv("VOLT_MONITOR_MAX_TURNS", "6")))
MAX_TOKENS = 2048

SYSTEM_PROMPT = (
    "You are Volt, VOLT CORE's incident investigation agent. You have been triggered "
    "because a P1/P2/P3 alert phone call to a human operator failed to be confirmed "
    "(no answer, busy, failed, or the call was never confirmed before its SLA window "
    "passed). Your job is only to investigate and explain -- you have read-only tools "
    "and no way to take any action. You cannot execute anything, you cannot change "
    "production or staging, and you cannot approve or dispatch anything. Any "
    "recommendation you make always requires explicit human approval before anyone "
    "acts on it; never suggest bypassing that. Use the tools available to gather "
    "context (the incident event, recent events on the same system, the escalation "
    "and call trail, monitoring status, and the audit log), then call "
    "submit_investigation_result exactly once, as your final action, with your "
    "diagnosis."
)


def _build_prompt(job: InvestigationJob) -> str:
    return (
        f"A voice call for a {job.priority} incident on system \"{job.system}\" "
        f"(environment: {job.environment}) failed to be confirmed. Investigate using "
        f"your tools and submit your diagnosis."
    )


def _call_model(client: anthropic.Anthropic, messages: list[dict[str, Any]]) -> Any:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    return client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[*TOOL_SCHEMAS, SUBMIT_TOOL_SCHEMA],
        messages=messages,
    )


def run_investigation(job: InvestigationJob) -> None:
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment; never constructed at import time
    messages: list[dict[str, Any]] = [{"role": "user", "content": _build_prompt(job)}]
    try:
        for turn in range(MAX_TURNS):
            response = _call_model(client, messages)
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                _persist_failure(job, reason=f"model stopped ({response.stop_reason}) without submitting a result")
                return

            tool_results = []
            submitted = None
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if block.name == SUBMIT_TOOL_NAME:
                    submitted = block.input
                    continue
                handler = TOOL_HANDLERS.get(block.name)
                result = handler(job, **block.input) if handler else {"error": f"unknown tool {block.name}"}
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)})

            if submitted is not None:
                _persist_success(job, submitted, response, turns_used=turn + 1)
                return
            if not tool_results:
                _persist_failure(job, reason="model made a tool_use turn with no recognizable tool calls")
                return
            messages.append({"role": "user", "content": tool_results})

        _persist_failure(job, reason=f"exceeded {MAX_TURNS} turns without submitting a result")
    except Exception as exc:
        _persist_failure(job, reason=f"{type(exc).__name__}: {str(exc)[:500]}")


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _persist_success(job: InvestigationJob, submitted: dict[str, Any], response: Any, turns_used: int) -> None:
    usage = getattr(response, "usage", None)
    is_known_pattern = bool(submitted["is_known_pattern"]) if submitted.get("is_known_pattern") is not None else None
    with session_scope() as session:
        record = AgentInvestigationRecord(
            event_id=job.event_id,
            escalation_id=job.escalation_id,
            system=job.system,
            environment=job.environment,
            priority=job.priority,
            status="completed",
            hypothesis=str(submitted.get("hypothesis") or ""),
            recommended_next_step=str(submitted.get("recommended_next_step") or ""),
            confidence=_safe_float(submitted.get("confidence")),
            is_known_pattern=is_known_pattern,
            model=MODEL,
            turns_used=turns_used,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            completed_at=datetime.now(timezone.utc),
        )
        session.add(record)
        session.flush()  # session_scope uses autoflush=False -- need record.id before the block exits
        session.add(
            AuditRecord(
                type="investigation_completed",
                reference_id=str(job.event_id),
                detail=f"escalation={job.escalation_id} turns={turns_used}",
            )
        )
        investigation_id = record.id

    if is_known_pattern is False:
        _maybe_chain_to_code_diagnosis(job, parent_investigation_id=investigation_id)
        _maybe_chain_to_database_diagnosis(job, parent_investigation_id=investigation_id)
        _maybe_chain_to_finance_diagnosis(job, parent_investigation_id=investigation_id)


def _maybe_chain_to_code_diagnosis(job: InvestigationJob, *, parent_investigation_id: int) -> None:
    # Chaining logic lives ONLY here. code_runner.py's run_code_diagnosis has no
    # equivalent call -- there is no structural path from a completed code_diagnosis
    # investigation back into this function. Do not "fix" that by adding chaining there.
    try:
        from .dispatcher import enqueue_code_diagnosis
        from .repo_config import resolve_repo

        mapping = resolve_repo(job.system)
        if mapping is None:
            with session_scope() as session:
                session.add(
                    AuditRecord(
                        type="investigation_chain_skipped_no_repo_mapping",
                        reference_id=str(job.event_id),
                        detail=f"system={job.system} has no VOLT_SYSTEM_REPOS mapping",
                    )
                )
            return
        owner, repo = mapping
        enqueue_code_diagnosis(
            event_id=job.event_id,
            escalation_id=job.escalation_id,
            system=job.system,
            environment=job.environment,
            priority=job.priority,
            owner=owner,
            repo=repo,
            parent_investigation_id=parent_investigation_id,
        )
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="investigation_chain_failed", reference_id=str(job.event_id), detail=str(exc)[:500]))


def _maybe_chain_to_database_diagnosis(job: InvestigationJob, *, parent_investigation_id: int) -> None:
    # Unlike Dev/Debug, there's no mapping to resolve -- the target is always VOLT
    # CORE's own Postgres. Fires unconditionally, no skip condition.
    try:
        from .dispatcher import enqueue_database_diagnosis

        enqueue_database_diagnosis(
            event_id=job.event_id,
            escalation_id=job.escalation_id,
            system=job.system,
            environment=job.environment,
            priority=job.priority,
            parent_investigation_id=parent_investigation_id,
        )
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="investigation_chain_failed", reference_id=str(job.event_id), detail=str(exc)[:500]))


def _maybe_chain_to_finance_diagnosis(job: InvestigationJob, *, parent_investigation_id: int) -> None:
    # Like Dev/Debug (not like the Database Agent): there's a per-system mapping to
    # resolve, and without it this skips with an audit record, it doesn't fail.
    try:
        from .dispatcher import enqueue_finance_diagnosis
        from .stripe_config import resolve_stripe_key_env_var

        env_var = resolve_stripe_key_env_var(job.system)
        if env_var is None:
            with session_scope() as session:
                session.add(
                    AuditRecord(
                        type="investigation_chain_skipped_no_stripe_mapping",
                        reference_id=str(job.event_id),
                        detail=f"system={job.system} has no VOLT_SYSTEM_STRIPE mapping",
                    )
                )
            return
        enqueue_finance_diagnosis(
            event_id=job.event_id,
            escalation_id=job.escalation_id,
            system=job.system,
            environment=job.environment,
            priority=job.priority,
            stripe_key_env_var=env_var,
            parent_investigation_id=parent_investigation_id,
        )
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="investigation_chain_failed", reference_id=str(job.event_id), detail=str(exc)[:500]))


def _persist_failure(job: InvestigationJob, reason: str) -> None:
    with session_scope() as session:
        session.add(
            AgentInvestigationRecord(
                event_id=job.event_id,
                escalation_id=job.escalation_id,
                system=job.system,
                environment=job.environment,
                priority=job.priority,
                status="failed",
                model=MODEL,
                error=reason[:2000],
                completed_at=datetime.now(timezone.utc),
            )
        )
        session.add(AuditRecord(type="investigation_failed", reference_id=str(job.event_id), detail=reason[:500]))
