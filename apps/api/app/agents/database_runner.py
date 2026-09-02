from __future__ import annotations

import inspect
import json
import os
from datetime import datetime, timezone
from typing import Any

from .. import llm_client
from ..db import session_scope
from ..models import AgentInvestigationRecord, AuditRecord
from .database_tools import TOOL_HANDLERS, TOOL_SCHEMAS, DatabaseJob
from .tools import SUBMIT_TOOL_NAME, SUBMIT_TOOL_SCHEMA

MODEL = os.getenv("VOLT_DBAGENT_MODEL") or llm_client.default_model()
MAX_TURNS = max(1, int(os.getenv("VOLT_DBAGENT_MAX_TURNS", "8")))
MAX_TOKENS = 2048

SYSTEM_PROMPT = (
    "You are Volt's Database agent, VOLT CORE's read-only investigation agent for its "
    "own Postgres database. You have been triggered because Volt already investigated "
    "an incident from its own data and could not explain it as a known, repeated "
    "pattern. Your job is to check whether the database itself explains or contributes "
    "to what happened -- slow or stuck queries, table bloat, unused indexes, connection "
    "exhaustion, or a backup-configuration gap. You have read-only tools and no way to "
    "take any action: you cannot run DDL or DML, you cannot change schema or data, and "
    "you cannot touch backups. Any change to the database -- schema, data, or backups -- "
    "always requires explicit human approval, without exception; never suggest "
    "bypassing that. When recommending a fix, describe the change in plain language "
    "for a human to review and construct themselves -- for example say 'add an index "
    "on orders.customer_id, currently missing and causing sequential scans,' never a "
    "ready-to-run statement like `CREATE INDEX CONCURRENTLY ...`. A recommendation "
    "that reads as copy-pasteable SQL blurs the line between 'propose' and 'execute' "
    "even though you have no way to run it yourself. Use your tools to investigate, "
    "then call submit_investigation_result exactly once, as your final action, with "
    "your diagnosis."
)


def _build_prompt(job: DatabaseJob) -> str:
    return (
        f"A {job.priority} incident on system \"{job.system}\" (environment: "
        f"{job.environment}) could not be explained from VOLT CORE's own data alone. "
        f"Check whether VOLT CORE's own Postgres database explains or contributes to "
        f"it. Investigate using your tools and submit your diagnosis."
    )


def _call_tool_handler(handler: Any, job: DatabaseJob, raw_input: dict[str, Any]) -> dict:
    # The model can call a tool with an argument beyond what its own schema declares --
    # drop anything the handler doesn't actually accept rather than letting a malformed
    # call abort the whole investigation.
    accepted = set(inspect.signature(handler).parameters) - {"job"}
    filtered = {key: value for key, value in raw_input.items() if key in accepted}
    return handler(job, **filtered)


def _call_model(client: llm_client.LLMClient, messages: list[dict[str, Any]]) -> Any:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    return client.call(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[*TOOL_SCHEMAS, SUBMIT_TOOL_SCHEMA],
        messages=messages,
    )


def run_database_diagnosis(job: DatabaseJob) -> None:
    messages: list[dict[str, Any]] = [{"role": "user", "content": _build_prompt(job)}]
    try:
        client = llm_client.get_client()  # reads whichever provider is configured; never constructed at import
        # time. Inside the try so a missing-provider LLMConfigError degrades to a normal
        # _persist_failure, same as every other exception in this loop.
        for turn in range(MAX_TURNS):
            response = _call_model(client, messages)
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                _persist_failure(job, reason=f"model stopped ({response.stop_reason}) without submitting a result")
                return

            tool_results = []
            submitted = None
            for block in response.content:
                if block.get("type") != "tool_use":
                    continue
                if block["name"] == SUBMIT_TOOL_NAME:
                    submitted = block["input"]
                    continue
                handler = TOOL_HANDLERS.get(block["name"])
                result = _call_tool_handler(handler, job, block["input"]) if handler else {"error": f"unknown tool {block['name']}"}
                tool_results.append({"type": "tool_result", "tool_use_id": block["id"], "content": json.dumps(result)})

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


def _persist_success(job: DatabaseJob, submitted: dict[str, Any], response: Any, turns_used: int) -> None:
    with session_scope() as session:
        session.add(
            AgentInvestigationRecord(
                event_id=job.event_id,
                escalation_id=job.escalation_id,
                investigation_type="database_diagnosis",
                parent_investigation_id=job.parent_investigation_id,
                system=job.system,
                environment=job.environment,
                priority=job.priority,
                status="completed",
                hypothesis=str(submitted.get("hypothesis") or ""),
                recommended_next_step=str(submitted.get("recommended_next_step") or ""),
                confidence=_safe_float(submitted.get("confidence")),
                is_known_pattern=bool(submitted["is_known_pattern"]) if submitted.get("is_known_pattern") is not None else None,
                model=MODEL,
                turns_used=turns_used,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                completed_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            AuditRecord(
                type="database_diagnosis_completed",
                reference_id=str(job.event_id),
                detail=f"parent={job.parent_investigation_id} turns={turns_used}",
            )
        )


def _persist_failure(job: DatabaseJob, reason: str) -> None:
    with session_scope() as session:
        session.add(
            AgentInvestigationRecord(
                event_id=job.event_id,
                escalation_id=job.escalation_id,
                investigation_type="database_diagnosis",
                parent_investigation_id=job.parent_investigation_id,
                system=job.system,
                environment=job.environment,
                priority=job.priority,
                status="failed",
                model=MODEL,
                error=reason[:2000],
                completed_at=datetime.now(timezone.utc),
            )
        )
        session.add(AuditRecord(type="database_diagnosis_failed", reference_id=str(job.event_id), detail=reason[:500]))
