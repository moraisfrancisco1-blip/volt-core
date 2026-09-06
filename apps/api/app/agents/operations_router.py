import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import session_scope
from ..models import AuditRecord, DealRecord, OnboardingRecord, OnboardingStepRecord, OperationsActivationRequestRecord
from . import operations_agent

router = APIRouter(prefix="/api", tags=["operations"])

STEP_LABELS = {key: label for key, label, _requires_activation in operations_agent.STEP_DEFINITIONS}
VALID_ACTIVATION_STATUSES = {"pending_approval", "approved"}


class MarkRecurringTaskDoneRequest(BaseModel):
    task_name: str = Field(min_length=1)


def _step_dict(step: OnboardingStepRecord) -> dict:
    return {
        "id": step.id,
        "onboarding_id": step.onboarding_id,
        "step_key": step.step_key,
        "label": STEP_LABELS.get(step.step_key, step.step_key),
        "order_index": step.order_index,
        "requires_activation": step.requires_activation,
        "status": step.status,
        "completed_at": step.completed_at.isoformat() if step.completed_at else None,
    }


def _onboarding_dict(onboarding: OnboardingRecord, steps: list[OnboardingStepRecord]) -> dict:
    last_progress_at = onboarding.last_progress_at
    if last_progress_at is not None and last_progress_at.tzinfo is None:
        last_progress_at = last_progress_at.replace(tzinfo=timezone.utc)
    stalled = onboarding.completed_at is None and last_progress_at is not None and (datetime.now(timezone.utc) - last_progress_at).days > operations_agent.STALE_DAYS
    ordered = sorted(steps, key=lambda s: s.order_index)
    done_count = sum(1 for s in ordered if s.status == "done")
    return {
        "id": onboarding.id,
        "deal_id": onboarding.deal_id,
        "steps": [_step_dict(s) for s in ordered],
        "progress": {"done": done_count, "total": len(ordered)},
        "completed_at": onboarding.completed_at.isoformat() if onboarding.completed_at else None,
        "last_progress_at": onboarding.last_progress_at.isoformat() if onboarding.last_progress_at else None,
        "stalled": stalled,
        "created_at": onboarding.created_at.isoformat() if onboarding.created_at else None,
    }


def _activation_dict(activation: OperationsActivationRequestRecord) -> dict:
    return {
        "id": activation.id,
        "onboarding_step_id": activation.onboarding_step_id,
        "description": activation.description,
        "status": activation.status,
        "created_at": activation.created_at.isoformat() if activation.created_at else None,
        "approved_at": activation.approved_at.isoformat() if activation.approved_at else None,
    }


def _touch_onboarding_progress(session, onboarding: OnboardingRecord, steps: list[OnboardingStepRecord]) -> None:
    onboarding.last_progress_at = datetime.now(timezone.utc)
    if all(s.status == "done" for s in steps):
        onboarding.completed_at = datetime.now(timezone.utc)


@router.get("/onboardings")
def list_onboardings(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    with session_scope() as session:
        onboardings = session.scalars(select(OnboardingRecord).order_by(OnboardingRecord.id.desc()).limit(limit)).all()
        result = []
        for onboarding in onboardings:
            steps = session.scalars(select(OnboardingStepRecord).where(OnboardingStepRecord.onboarding_id == onboarding.id)).all()
            result.append(_onboarding_dict(onboarding, steps))
        return result


@router.get("/onboardings/{onboarding_id}")
def get_onboarding(onboarding_id: int) -> dict:
    with session_scope() as session:
        onboarding = session.get(OnboardingRecord, onboarding_id)
        if onboarding is None:
            raise HTTPException(status_code=404, detail="onboarding not found")
        steps = session.scalars(select(OnboardingStepRecord).where(OnboardingStepRecord.onboarding_id == onboarding_id)).all()
        return _onboarding_dict(onboarding, steps)


@router.post("/operations/run")
def trigger_operations_sweep() -> dict:
    threading.Thread(target=operations_agent.run_operations_sweep, daemon=True).start()
    return {"triggered": True}


@router.get("/operations/recurring-tasks")
def list_recurring_tasks() -> list[dict]:
    return [operations_agent.recurring_task_status(task) for task in operations_agent.recurring_tasks()]


@router.post("/operations/recurring-tasks/mark-done")
def mark_recurring_task_done(payload: MarkRecurringTaskDoneRequest) -> dict:
    # A human confirming a real checkpoint happened -- never inferred or scheduled by
    # the agent itself, matching the "never invents a recurring task or its status" rule.
    valid_names = {task["name"] for task in operations_agent.recurring_tasks()}
    if payload.task_name not in valid_names:
        raise HTTPException(status_code=404, detail="recurring task not configured")
    operations_agent.mark_recurring_task_done(payload.task_name)
    task = next(task for task in operations_agent.recurring_tasks() if task["name"] == payload.task_name)
    return operations_agent.recurring_task_status(task)


@router.post("/onboardings/{onboarding_id}/steps/{step_id}/complete")
def complete_onboarding_step(onboarding_id: int, step_id: int) -> dict:
    # For non-activation steps only -- this records a real-world fact a human has
    # observed/confirmed (e.g. the customer confirmed onboarding is working), it never
    # performs any action against VoltarisOS or any billing/access system itself.
    with session_scope() as session:
        onboarding = session.get(OnboardingRecord, onboarding_id)
        if onboarding is None:
            raise HTTPException(status_code=404, detail="onboarding not found")
        step = session.get(OnboardingStepRecord, step_id)
        if step is None or step.onboarding_id != onboarding_id:
            raise HTTPException(status_code=404, detail="onboarding step not found")
        if step.requires_activation:
            raise HTTPException(status_code=422, detail="this step requires an approved activation request, not a direct complete")
        if step.status != "done":
            step.status = "done"
            step.completed_at = datetime.now(timezone.utc)
            steps = session.scalars(select(OnboardingStepRecord).where(OnboardingStepRecord.onboarding_id == onboarding_id)).all()
            _touch_onboarding_progress(session, onboarding, steps)
            session.add(AuditRecord(type="onboarding_step_completed", reference_id=str(step_id), detail=step.step_key))
        steps = session.scalars(select(OnboardingStepRecord).where(OnboardingStepRecord.onboarding_id == onboarding_id)).all()
        return _onboarding_dict(onboarding, steps)


@router.get("/operations-activations")
def list_operations_activations(limit: int = Query(default=50, ge=1, le=200), status: str | None = None) -> list[dict]:
    with session_scope() as session:
        statement = select(OperationsActivationRequestRecord)
        if status:
            normalized = status.strip().lower()
            if normalized not in VALID_ACTIVATION_STATUSES:
                raise HTTPException(status_code=422, detail="invalid activation status")
            statement = statement.where(OperationsActivationRequestRecord.status == normalized)
        rows = session.scalars(statement.order_by(OperationsActivationRequestRecord.id.desc()).limit(limit)).all()
        return [_activation_dict(row) for row in rows]


@router.get("/operations-activations/{activation_id}")
def get_operations_activation(activation_id: int) -> dict:
    with session_scope() as session:
        activation = session.get(OperationsActivationRequestRecord, activation_id)
        if activation is None:
            raise HTTPException(status_code=404, detail="activation request not found")
        return _activation_dict(activation)


@router.post("/operations-activations/{activation_id}/approve")
def approve_operations_activation(activation_id: int) -> dict:
    # The ONLY place in the whole app that ever marks a requires_activation onboarding
    # step as done -- reached only by an explicit human click on the dashboard. This is a
    # pure internal record-keeping update: there is no real VoltarisOS/billing API call
    # here, because none exists for this agent to call -- the actual account activation
    # happens manually, outside this system, and this endpoint just records that a human
    # has confirmed/performed it. Re-checking status here is what makes a double-click
    # harmless instead of a double-action.
    with session_scope() as session:
        activation = session.get(OperationsActivationRequestRecord, activation_id)
        if activation is None:
            raise HTTPException(status_code=404, detail="activation request not found")
        if activation.status != "pending_approval":
            return _activation_dict(activation)
        step = session.get(OnboardingStepRecord, activation.onboarding_step_id)
        if step is None:
            raise HTTPException(status_code=404, detail="onboarding step for this activation not found")

        activation.status = "approved"
        activation.approved_at = datetime.now(timezone.utc)
        step.status = "done"
        step.completed_at = datetime.now(timezone.utc)

        onboarding = session.get(OnboardingRecord, step.onboarding_id)
        if onboarding is not None:
            steps = session.scalars(select(OnboardingStepRecord).where(OnboardingStepRecord.onboarding_id == onboarding.id)).all()
            _touch_onboarding_progress(session, onboarding, steps)

        session.add(AuditRecord(type="operations_activation_approved", reference_id=str(activation_id), detail=f"step_id={step.id}"))
        return _activation_dict(activation)
