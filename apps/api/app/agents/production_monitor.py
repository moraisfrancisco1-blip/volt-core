from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .. import llm_client
from ..db import session_scope
from ..models import AuditRecord, MonitoringSweepRecord
from .monitoring_alerts import RAISE_ALERT_SCHEMA, raise_monitoring_alert
from .railway_config import resolve_railway_service, sweep_system_ids
from .railway_tools import TOOL_HANDLERS, TOOL_SCHEMAS, ProductionSweepJob

SWEEP_INTERVAL_SECONDS = max(60, int(os.getenv("VOLT_PRODMON_INTERVAL_SECONDS", "600")))
MODEL = os.getenv("VOLT_PRODMON_MODEL") or llm_client.default_model()
MAX_TURNS = max(1, int(os.getenv("VOLT_PRODMON_MAX_TURNS", "8")))
MAX_TOKENS = 2048

SUBMIT_TOOL_NAME = "submit_sweep_result"
SUBMIT_TOOL_SCHEMA: dict[str, Any] = {
    "name": SUBMIT_TOOL_NAME,
    "description": "Submit your final summary of this sweep. Call this exactly once, as your last action, whether or not you raised an alert. This is the only way to end the sweep.",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string", "description": "One or two sentences on what you found, or that nothing was concerning."}},
        "required": ["summary"],
    },
}

SYSTEM_PROMPT = (
    "You are Volt's Production Monitor. You run on your own schedule, not triggered by "
    "any existing incident. You have read-only tools against one system's real Railway "
    "telemetry (HTTP error rate, latency, resource usage, recent deployments). Your job "
    "is to decide whether anything is genuinely concerning enough to raise as an alert -- "
    "a single noisy data point is not enough, look for a real trend across the window. "
    "You cannot execute anything, scale, restart, redeploy, or reconfigure any service. "
    "Raising an alert (via raise_monitoring_alert) is the only write action you have, and "
    "it only creates an event for a human to see -- it never changes production by "
    "itself. If you already raised an alert for this category and it's still open, "
    "raise_monitoring_alert will tell you and you should not try again. Call "
    "submit_sweep_result exactly once, as your final action, whether or not you raised "
    "an alert."
)

_started = False
_lock = threading.Lock()
_sweep_in_progress = False


def _build_prompt(job: ProductionSweepJob) -> str:
    return (
        f"Sweep system \"{job.system}\" (environment: {job.environment}). Check its "
        f"Railway telemetry and raise an alert only if something is genuinely wrong."
    )


def _call_model(client: llm_client.LLMClient, messages: list[dict[str, Any]]) -> Any:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    return client.call(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[*TOOL_SCHEMAS, RAISE_ALERT_SCHEMA, SUBMIT_TOOL_SCHEMA],
        messages=messages,
    )


def run_system_sweep(job: ProductionSweepJob) -> None:
    messages: list[dict[str, Any]] = [{"role": "user", "content": _build_prompt(job)}]
    # Sweep-scoped, not turn-scoped: raise_monitoring_alert and submit_sweep_result can
    # land on different turns, and the alert's outcome must survive until the submit.
    event_action = None
    created_event_id = None
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
                if block["name"] == "raise_monitoring_alert":
                    result = raise_monitoring_alert(job, **block["input"])
                    if result.get("created"):
                        event_action = "created"
                    elif "event_id" in result:
                        event_action = "deduped"
                    created_event_id = result.get("event_id")
                else:
                    handler = TOOL_HANDLERS.get(block["name"])
                    result = handler(job, **block["input"]) if handler else {"error": f"unknown tool {block['name']}"}
                tool_results.append({"type": "tool_result", "tool_use_id": block["id"], "content": json.dumps(result)})

            if submitted is not None:
                _persist_success(job, submitted, response, event_action or "none", created_event_id, turns_used=turn + 1)
                return
            if not tool_results:
                _persist_failure(job, reason="model made a tool_use turn with no recognizable tool calls")
                return
            messages.append({"role": "user", "content": tool_results})

        _persist_failure(job, reason=f"exceeded {MAX_TURNS} turns without submitting a result")
    except Exception as exc:
        _persist_failure(job, reason=f"{type(exc).__name__}: {str(exc)[:500]}")


def _persist_success(job: ProductionSweepJob, submitted: dict[str, Any], response: Any, event_action: str, created_event_id: int | None, turns_used: int) -> None:
    with session_scope() as session:
        session.add(
            MonitoringSweepRecord(
                system=job.system,
                environment=job.environment,
                status="completed",
                event_action=event_action,
                created_event_id=created_event_id,
                summary=str(submitted.get("summary") or ""),
                model=MODEL,
                turns_used=turns_used,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                completed_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            AuditRecord(
                type="monitoring_sweep_completed",
                reference_id=job.system,
                detail=f"event_action={event_action} event_id={created_event_id} turns={turns_used}",
            )
        )


def _persist_failure(job: ProductionSweepJob, reason: str) -> None:
    with session_scope() as session:
        session.add(
            MonitoringSweepRecord(
                system=job.system,
                environment=job.environment,
                status="failed",
                model=MODEL,
                error=reason[:2000],
                completed_at=datetime.now(timezone.utc),
            )
        )
        session.add(AuditRecord(type="monitoring_sweep_run_failed", reference_id=job.system, detail=reason[:500]))


def run_sweep() -> None:
    if not (llm_client.is_configured() and os.getenv("RAILWAY_TOKEN")):
        return
    for system in sweep_system_ids():
        target = resolve_railway_service(system)
        if target is None:
            continue
        try:
            run_system_sweep(ProductionSweepJob(
                system=system, environment=target.environment,
                project_id=target.project_id, service_id=target.service_id, environment_id=target.environment_id,
            ))
        except Exception as exc:
            # One system's failure must never abort the sweep of the rest.
            with session_scope() as session:
                session.add(AuditRecord(type="monitoring_sweep_failed", reference_id=system, detail=str(exc)[:500]))


def is_sweep_in_progress() -> bool:
    # The dashboard's signal that a sweep is actively running right now -- sweep
    # records are only written once a sweep completes (success or failure), so this
    # is the only way to distinguish "idle between sweeps" from "sweeping now".
    return _sweep_in_progress


def _sweep_loop() -> None:
    global _sweep_in_progress
    while True:
        try:
            _sweep_in_progress = True
            run_sweep()
        except Exception as exc:
            print(f"[volt-core-prodmon] sweep failure: {type(exc).__name__}: {exc}")
        finally:
            _sweep_in_progress = False
        time.sleep(SWEEP_INTERVAL_SECONDS)


def start_production_monitor() -> None:
    global _started
    # Double-gated, combining both existing precedents: this guards thread startup
    # (mirrors start_investigation_worker's llm_client.is_configured() gate), and
    # run_sweep() independently re-checks both vars at call time (mirrors code_runner's
    # GITHUB_TOKEN fail-fast) -- so any future manual "run a sweep now" path is protected
    # the same way.
    if _started or not (llm_client.is_configured() and os.getenv("RAILWAY_TOKEN")):
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_sweep_loop, name="volt-core-production-monitor", daemon=True).start()
        _started = True
