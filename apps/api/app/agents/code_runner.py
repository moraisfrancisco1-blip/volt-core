from __future__ import annotations

import inspect
import json
import os
from datetime import datetime, timezone
from typing import Any

from .. import llm_client
from ..db import session_scope
from ..models import AgentInvestigationRecord, AuditRecord
from .github_tools import TOOL_HANDLERS, TOOL_SCHEMAS, CodeDiagnosisJob

MODEL = os.getenv("VOLT_DEVDEBUG_MODEL") or llm_client.default_model()
MAX_TURNS = max(1, int(os.getenv("VOLT_DEVDEBUG_MAX_TURNS", "10")))
MAX_TOKENS = 2048
SANDBOX_TIMEOUT_SECONDS = max(30, int(os.getenv("VOLT_DEVDEBUG_SANDBOX_TIMEOUT", "120")))

# Owns its own submit schema (unlike Volt/Database/Finance, which share tools.py's
# generic one) because Dev/Debug alone can propose a concrete fix -- proposed_files is
# optional and empty/omitted is a normal, common outcome (diagnosis-only).
SUBMIT_TOOL_NAME = "submit_investigation_result"
SUBMIT_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_TOOL_NAME,
    "description": (
        "Submit your final diagnosis of this incident. Call this exactly once, as your "
        "last action, once you have gathered enough context. If you have a concrete code "
        "fix, include it via proposed_files -- it will be applied and tested in an "
        "isolated sandbox before a human reviews it, never against production. This is "
        "the only way to end the investigation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "hypothesis": {
                "type": "string",
                "description": "Your best explanation for what is happening and why the alert call was not confirmed.",
            },
            "recommended_next_step": {
                "type": "string",
                "description": "A concrete next step for a human operator to take. Never recommend an automated production action -- that always requires human approval.",
            },
            "confidence": {
                "type": "number",
                "description": "Your confidence in this hypothesis, from 0.0 (guessing) to 1.0 (certain).",
            },
            "is_known_pattern": {
                "type": "boolean",
                "description": "True if this matches a pattern already visible in the recent event/audit history (e.g. a recurring failure), false if it looks novel.",
            },
            "proposed_files": {
                "type": "array",
                "description": (
                    "Optional. If you have a concrete code fix, list each changed file's "
                    "full new content here (not a diff -- the complete file as it should "
                    "read after the fix). Leave empty or omit entirely if this investigation "
                    "is diagnosis-only, which is the normal, common outcome."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Path relative to the repository root."},
                        "new_content": {"type": "string", "description": "The complete new content of this file."},
                    },
                    "required": ["file_path", "new_content"],
                },
            },
        },
        "required": ["hypothesis", "recommended_next_step", "confidence", "is_known_pattern"],
    },
}

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


def _call_tool_handler(handler: Any, job: CodeDiagnosisJob, raw_input: dict[str, Any]) -> dict:
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


def run_code_diagnosis(job: CodeDiagnosisJob) -> None:
    if not os.getenv("GITHUB_TOKEN"):
        _persist_failure(job, reason="GITHUB_TOKEN not configured")
        return
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
                proposed_files = submitted.get("proposed_files") or []
                sandbox_result = None
                if proposed_files:
                    from .sandbox import run_sandboxed_fix

                    sandbox_result = run_sandboxed_fix(job.owner, job.repo, proposed_files, timeout_seconds=SANDBOX_TIMEOUT_SECONDS)
                _persist_success(job, submitted, response, turns_used=turn + 1, sandbox_result=sandbox_result)
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


def _persist_success(job: CodeDiagnosisJob, submitted: dict[str, Any], response: Any, turns_used: int, sandbox_result: dict[str, Any] | None = None) -> None:
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
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                proposed_files=submitted.get("proposed_files") or None,
                sandbox_status=(sandbox_result or {}).get("status", "not_attempted") if sandbox_result is not None else "not_attempted",
                sandbox_output=(sandbox_result or {}).get("output") if sandbox_result is not None else None,
                sandbox_network_isolated=(sandbox_result or {}).get("network_isolated") if sandbox_result is not None else None,
                sandbox_ran_at=datetime.now(timezone.utc) if sandbox_result is not None else None,
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
