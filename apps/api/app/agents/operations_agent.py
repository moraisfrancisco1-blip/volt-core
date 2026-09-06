from __future__ import annotations

import json
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from ..db import session_scope
from ..models import AuditRecord, DealRecord, OnboardingRecord, OnboardingStepRecord, OperationsActivationRequestRecord, RecurringTaskCheckpointRecord

# Onboarding shouldn't sit untouched for as long as a stale deal can -- a new
# customer/partner is actively waiting. max() floor keeps a misconfigured tiny value
# from turning "stalled" into a false alarm on every read.
STALE_DAYS = max(1, int(os.getenv("VOLT_OPS_ONBOARDING_STALE_DAYS", "5")))

# Fixed checklist, same order for every onboarding -- (step_key, label, requires_activation,
# activation_description_template). requires_activation=True means completing this step is a
# real production change (activating account access) and can only ever be recorded here via
# a human-approved OperationsActivationRequestRecord -- never flipped by the sweep itself.
STEP_DEFINITIONS: list[tuple[str, str, bool]] = [
    ("account_created", "Conta criada", True),
    ("initial_setup", "Configuração inicial", False),
    ("first_data_sync", "Primeira sincronização de dados", False),
    ("customer_confirmation", "Confirmação do cliente/parceiro", False),
]

_DEFAULT_RECURRING_TASKS: list[dict] = []


def recurring_tasks() -> list[dict]:
    # Same "fixed list, editable via env var" convention as market_intelligence's
    # _competitors() and sales_agent's _b2b_prospects() -- never invented, only ever what
    # Francisco has configured. Each entry: {"name": str, "cadence_days": int, "anchor_date": "YYYY-MM-DD"}.
    raw = os.getenv("VOLT_OPS_RECURRING_TASKS", "").strip()
    if not raw:
        return list(_DEFAULT_RECURRING_TASKS)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return list(_DEFAULT_RECURRING_TASKS)
    if not isinstance(payload, list):
        return list(_DEFAULT_RECURRING_TASKS)
    tasks = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        if not entry.get("name") or not entry.get("cadence_days") or not entry.get("anchor_date"):
            continue
        try:
            cadence_days = int(entry["cadence_days"])
            anchor = date.fromisoformat(str(entry["anchor_date"]))
        except (ValueError, TypeError):
            continue
        if cadence_days <= 0:
            continue
        tasks.append({"name": str(entry["name"]), "cadence_days": cadence_days, "anchor_date": anchor})
    return tasks


def _last_completed_at(task_name: str) -> datetime | None:
    with session_scope() as session:
        checkpoint = session.scalar(select(RecurringTaskCheckpointRecord).where(RecurringTaskCheckpointRecord.task_name == task_name))
        return checkpoint.last_completed_at if checkpoint else None


def mark_recurring_task_done(task_name: str) -> None:
    # A human confirming a real checkpoint happened (e.g. a partner call actually took
    # place) -- this is a fact only a human can know, the agent never marks this itself.
    with session_scope() as session:
        checkpoint = session.scalar(select(RecurringTaskCheckpointRecord).where(RecurringTaskCheckpointRecord.task_name == task_name))
        if checkpoint is None:
            checkpoint = RecurringTaskCheckpointRecord(task_name=task_name)
            session.add(checkpoint)
        checkpoint.last_completed_at = datetime.now(timezone.utc)


def recurring_task_status(task: dict, *, now: datetime | None = None) -> dict:
    # Next due date is computed from the last human-confirmed completion (or, if never
    # confirmed, from the configured anchor date) plus the cadence -- never guessed.
    now = now or datetime.now(timezone.utc)
    last_completed = _last_completed_at(task["name"])
    if last_completed is not None:
        if last_completed.tzinfo is None:
            last_completed = last_completed.replace(tzinfo=timezone.utc)
        baseline = last_completed
    else:
        baseline = datetime.combine(task["anchor_date"], datetime.min.time(), tzinfo=timezone.utc)
    next_due = baseline + timedelta(days=task["cadence_days"])
    days_until_due = (next_due - now).days
    return {
        "name": task["name"],
        "cadence_days": task["cadence_days"],
        "last_completed_at": last_completed.isoformat() if last_completed else None,
        "next_due_at": next_due.isoformat(),
        "days_until_due": days_until_due,
        "overdue": next_due < now,
        "due_soon": next_due >= now and days_until_due <= 3,
    }


def _sync_onboardings_from_closed_deals() -> None:
    with session_scope() as session:
        existing_deal_ids = {row for row in session.scalars(select(OnboardingRecord.deal_id)).all()}
        closed_won_deal_ids = session.scalars(select(DealRecord.id).where(DealRecord.stage == "closed_won")).all()

        for deal_id in closed_won_deal_ids:
            if deal_id in existing_deal_ids:
                continue
            onboarding = OnboardingRecord(deal_id=deal_id)
            session.add(onboarding)
            session.flush()
            for index, (step_key, _label, requires_activation) in enumerate(STEP_DEFINITIONS):
                session.add(OnboardingStepRecord(
                    onboarding_id=onboarding.id, step_key=step_key, order_index=index,
                    requires_activation=requires_activation, status="pending",
                ))
            session.add(AuditRecord(type="onboarding_created", reference_id=str(onboarding.id), detail=f"deal_id={deal_id}"))
            existing_deal_ids.add(deal_id)


def _prepare_activation_requests() -> None:
    with session_scope() as session:
        requested_step_ids = {row for row in session.scalars(select(OperationsActivationRequestRecord.onboarding_step_id)).all()}
        candidates = session.scalars(
            select(OnboardingStepRecord).where(OnboardingStepRecord.requires_activation.is_(True), OnboardingStepRecord.status == "pending")
        ).all()

        for step in candidates:
            if step.id in requested_step_ids:
                continue
            onboarding = session.get(OnboardingRecord, step.onboarding_id)
            deal = session.get(DealRecord, onboarding.deal_id) if onboarding else None
            deal_ref = f"deal #{deal.id}" if deal else f"onboarding #{step.onboarding_id}"
            session.add(OperationsActivationRequestRecord(
                onboarding_step_id=step.id,
                description=f"Ativar acesso real na plataforma VoltarisOS para o cliente/parceiro do {deal_ref} (passo: conta criada). Requer aprovação humana explícita -- este pedido nunca é executado automaticamente.",
                status="pending_approval",
            ))
            session.add(AuditRecord(type="operations_activation_requested", reference_id=str(step.id), detail="status=pending_approval"))


def run_operations_sweep() -> None:
    # Deliberately deterministic, no model call: this agent has no real read access to the
    # VoltarisOS platform's actual account state, so it never guesses at onboarding progress --
    # it only reflects real deals data and records real, human-confirmed facts (see the
    # complete-step and approve-activation endpoints in operations_router.py).
    try:
        _sync_onboardings_from_closed_deals()
        _prepare_activation_requests()
    except Exception as exc:
        with session_scope() as session:
            session.add(AuditRecord(type="operations_sweep_failed", detail=f"{type(exc).__name__}: {str(exc)[:500]}"))


_started = False
_lock = threading.Lock()
_sweep_in_progress = False


def is_sweep_in_progress() -> bool:
    return _sweep_in_progress


def _sweep_loop(interval_seconds: int) -> None:
    global _sweep_in_progress
    while True:
        try:
            _sweep_in_progress = True
            run_operations_sweep()
        except Exception as exc:
            print(f"[volt-core-operations] sweep failure: {type(exc).__name__}: {exc}")
        finally:
            _sweep_in_progress = False
        time.sleep(interval_seconds)


def start_operations_agent() -> None:
    # No LLM/external-credential gate needed -- this agent only reads/writes its own
    # database tables, so unlike the other periodic agents it has nothing to be
    # "not configured" for.
    global _started
    if _started:
        return
    with _lock:
        if _started:
            return
        interval_seconds = max(300, int(os.getenv("VOLT_OPS_INTERVAL_SECONDS", "3600")))
        threading.Thread(target=_sweep_loop, args=(interval_seconds,), name="volt-core-operations", daemon=True).start()
        _started = True
