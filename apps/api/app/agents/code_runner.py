from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import anthropic

from ..db import session_scope
from ..models import AgentInvestigationRecord, AuditRecord
from .github_tools import TOOL_HANDLERS, TOOL_SCHEMAS, CodeDiagnosisJob
from .tools import SUBMIT_TOOL_NAME, SUBMIT_TOOL_SCHEMA

MODEL = os.getenv("VOLT_DEVDEBUG_MODEL", "claude-sonnet-4-5")
MAX_TURNS = max(1, int(os.getenv("VOLT_DEVDEBUG_MAX_TURNS", "10")))
MAX_TOKENS = 2048

SYSTEM_PROMPT = (
    "You are Volt's Dev/Debug agent, VOLT CORE's code-level incident investigation "
    "agent. You have been triggered because Volt already "
    "investigated this incident from its own data and could not explain it as a known, "
    "repeated pattern. Your job is to go deeper by reading the affected system's actual "
    "source code -- you have read-only tools scoped to exactly one GitHub repository and "
    "no way to take any action. You cannot execute anything, write to the repository, "
    "create branches or commits, or change production or staging. Any recommendation you "
    "make always requires explicit human approval before anyone acts on it; never suggest "
    "bypassing that. Start by reading Volt's prior diagnosis so you are "
    "not starting from zero, then use list_repo_files/read_repo_file/search_repo_code/"
    "get_recent_commits to investigate, then call submit_investigation_result exactly "
    "once, as your final action, with your diagnosis."
)


def _build_prompt(job: CodeDiagnosisJob) -> str:
    return (
        f"A {job.priority} incident on system \"{job.system}\" (environment: "
        f"{job.environment}) could not be explained from VOLT CORE's own data alone. "
        f"You have read-only access to {job.owner}/{job.repo}. Investigate using your "
        f"tools and submit your diagnosis."
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


def run_code_diagnosis(job: CodeDiagnosisJob) -> None:
    if not os.getenv("GITHUB_TOKEN"):
        _persist_failure(job, reason="GITHUB_TOKEN not configured")
        return
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


def _persist_success(job: CodeDiagnosisJob, submitted: dict[str, Any], response: Any, turns_used: int) -> None:
    usage = getattr(response, "usage", None)
    with session_scope() as session:
        session.add(
            AgentInvestigationRecord(
                event_id=job.event_id,
                escalation_id=job.escalation_id,
                investigation_type="code_diagnosis",
                parent_investigation_id=job.parent_investigation_id,
                system=job.system,
                environment=job.environment,
                priority=job.priority,
                status="completed",
                hypothesis=str(submitted.get("hypothesis") or ""),
                recommended_next_step=str(submitted.get("recommended_next_step") or ""),
                confidence=_safe_float(submitted.get("confidence")),
                is_known_pattern=bool(submitted["is_known_pattern"]) if submitted.get("is_known_pattern") is not None else None,
                repo_owner=job.owner,
                repo_name=job.repo,
                model=MODEL,
                turns_used=turns_used,
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                completed_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            AuditRecord(
                type="code_diagnosis_completed",
                reference_id=str(job.event_id),
                detail=f"parent={job.parent_investigation_id} repo={job.owner}/{job.repo} turns={turns_used}",
            )
        )


def _persist_failure(job: CodeDiagnosisJob, reason: str) -> None:
    with session_scope() as session:
        session.add(
            AgentInvestigationRecord(
                event_id=job.event_id,
                escalation_id=job.escalation_id,
                investigation_type="code_diagnosis",
                parent_investigation_id=job.parent_investigation_id,
                system=job.system,
                environment=job.environment,
                priority=job.priority,
                status="failed",
                repo_owner=job.owner,
                repo_name=job.repo,
                model=MODEL,
                error=reason[:2000],
                completed_at=datetime.now(timezone.utc),
            )
        )
        session.add(AuditRecord(type="code_diagnosis_failed", reference_id=str(job.event_id), detail=reason[:500]))
