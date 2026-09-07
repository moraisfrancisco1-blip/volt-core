from datetime import date, datetime, timezone

from app.agents import operations_agent
from app.db import session_scope
from app.models import DealRecord, OnboardingRecord, OnboardingStepRecord, OperationsActivationRequestRecord, SalesLeadRecord


def _seed_lead(**overrides) -> int:
    defaults = dict(lead_type="tenant_signup", status="qualified", name="Anke Visser", email="ops-agent-test@example.com", consent_basis="existing_customer_tenant")
    defaults.update(overrides)
    with session_scope() as session:
        lead = SalesLeadRecord(**defaults)
        session.add(lead)
        session.flush()
        return lead.id


def _seed_deal(lead_id: int, **overrides) -> int:
    defaults = dict(lead_id=lead_id, stage="qualified")
    defaults.update(overrides)
    with session_scope() as session:
        deal = DealRecord(**defaults)
        session.add(deal)
        session.flush()
        return deal.id


# --- syncing onboardings from closed_won deals -------------------------------------------------

def test_sweep_creates_onboarding_only_for_closed_won_deals():
    lead_id = _seed_lead(email="closed-won-sync@example.com")
    won_deal_id = _seed_deal(lead_id, stage="closed_won")
    open_deal_id = _seed_deal(lead_id, stage="negotiating")

    operations_agent.run_operations_sweep()

    with session_scope() as session:
        onboardings_by_deal = {o.deal_id: o for o in session.query(OnboardingRecord).all()}
        assert won_deal_id in onboardings_by_deal
        assert open_deal_id not in onboardings_by_deal


def test_sweep_creates_all_four_checklist_steps_in_order():
    lead_id = _seed_lead(email="checklist-steps@example.com")
    deal_id = _seed_deal(lead_id, stage="closed_won")

    operations_agent.run_operations_sweep()

    with session_scope() as session:
        onboarding = session.query(OnboardingRecord).filter_by(deal_id=deal_id).one()
        steps = sorted(session.query(OnboardingStepRecord).filter_by(onboarding_id=onboarding.id).all(), key=lambda s: s.order_index)
        assert [s.step_key for s in steps] == ["account_created", "initial_setup", "first_data_sync", "customer_confirmation"]
        assert all(s.status == "pending" for s in steps)
        assert [s.requires_activation for s in steps] == [True, False, False, False]


def test_sweep_is_idempotent_and_does_not_duplicate_onboardings():
    lead_id = _seed_lead(email="idempotent-onboarding@example.com")
    deal_id = _seed_deal(lead_id, stage="closed_won")

    operations_agent.run_operations_sweep()
    operations_agent.run_operations_sweep()

    with session_scope() as session:
        count = session.query(OnboardingRecord).filter_by(deal_id=deal_id).count()
        assert count == 1


# --- preparing activation requests -- never flips the step itself ------------------------------

def test_sweep_prepares_pending_activation_request_for_account_created_step():
    lead_id = _seed_lead(email="activation-request@example.com")
    deal_id = _seed_deal(lead_id, stage="closed_won")

    operations_agent.run_operations_sweep()

    with session_scope() as session:
        onboarding = session.query(OnboardingRecord).filter_by(deal_id=deal_id).one()
        account_step = session.query(OnboardingStepRecord).filter_by(onboarding_id=onboarding.id, step_key="account_created").one()
        activation = session.query(OperationsActivationRequestRecord).filter_by(onboarding_step_id=account_step.id).one()
        assert activation.status == "pending_approval"
        # The sweep must never flip the step to done by itself -- only a human approval does.
        assert account_step.status == "pending"
        assert str(deal_id) in activation.description or f"deal #{deal_id}" in activation.description


def test_sweep_does_not_duplicate_activation_requests():
    lead_id = _seed_lead(email="no-duplicate-activation@example.com")
    deal_id = _seed_deal(lead_id, stage="closed_won")

    operations_agent.run_operations_sweep()
    operations_agent.run_operations_sweep()

    with session_scope() as session:
        onboarding = session.query(OnboardingRecord).filter_by(deal_id=deal_id).one()
        account_step = session.query(OnboardingStepRecord).filter_by(onboarding_id=onboarding.id, step_key="account_created").one()
        count = session.query(OperationsActivationRequestRecord).filter_by(onboarding_step_id=account_step.id).count()
        assert count == 1


def test_sweep_never_requests_activation_for_non_activation_steps():
    lead_id = _seed_lead(email="only-account-created-activation@example.com")
    deal_id = _seed_deal(lead_id, stage="closed_won")

    operations_agent.run_operations_sweep()

    with session_scope() as session:
        onboarding = session.query(OnboardingRecord).filter_by(deal_id=deal_id).one()
        non_activation_step_ids = {
            s.id for s in session.query(OnboardingStepRecord).filter_by(onboarding_id=onboarding.id).all() if not s.requires_activation
        }
        requested_step_ids = {row for row, in session.query(OperationsActivationRequestRecord.onboarding_step_id).all()}
        assert not (non_activation_step_ids & requested_step_ids)


def test_sweep_failure_in_one_phase_is_isolated(monkeypatch):
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(operations_agent, "_prepare_activation_requests", _boom)
    operations_agent.run_operations_sweep()  # must not raise

    from app.models import AuditRecord
    with session_scope() as session:
        audit = session.query(AuditRecord).filter_by(type="operations_sweep_failed").order_by(AuditRecord.id.desc()).first()
        assert audit is not None
        assert "boom" in audit.detail


# --- recurring tasks -- purely computed from env-configured schedule, nothing invented ----------

def test_recurring_tasks_empty_by_default(monkeypatch):
    monkeypatch.delenv("VOLT_OPS_RECURRING_TASKS", raising=False)
    assert operations_agent.recurring_tasks() == []


def test_recurring_tasks_parses_valid_json(monkeypatch):
    monkeypatch.setenv("VOLT_OPS_RECURRING_TASKS", '[{"name": "Checkpoint trimestral", "cadence_days": 90, "anchor_date": "2026-01-01"}]')
    tasks = operations_agent.recurring_tasks()
    assert len(tasks) == 1
    assert tasks[0]["name"] == "Checkpoint trimestral"


def test_recurring_tasks_ignores_malformed_entries(monkeypatch):
    monkeypatch.setenv("VOLT_OPS_RECURRING_TASKS", '[{"name": "sem cadencia"}, {"name": "valido", "cadence_days": 30, "anchor_date": "2026-01-01"}]')
    tasks = operations_agent.recurring_tasks()
    assert len(tasks) == 1
    assert tasks[0]["name"] == "valido"


def test_recurring_task_status_reports_overdue_when_never_confirmed_past_cadence():
    task = {"name": "checkpoint-overdue", "cadence_days": 30, "anchor_date": date(2026, 1, 1)}
    status = operations_agent.recurring_task_status(task, now=datetime(2026, 3, 15, tzinfo=timezone.utc))
    assert status["overdue"] is True
    assert status["days_until_due"] < 0


def test_recurring_task_status_reports_due_soon_not_overdue():
    task = {"name": "checkpoint-due-soon", "cadence_days": 30, "anchor_date": date(2026, 1, 1)}
    status = operations_agent.recurring_task_status(task, now=datetime(2026, 1, 29, tzinfo=timezone.utc))
    assert status["overdue"] is False
    assert status["due_soon"] is True


def test_recurring_task_status_reports_neither_when_far_out():
    task = {"name": "checkpoint-far-out", "cadence_days": 30, "anchor_date": date(2026, 1, 1)}
    status = operations_agent.recurring_task_status(task, now=datetime(2026, 1, 5, tzinfo=timezone.utc))
    assert status["overdue"] is False
    assert status["due_soon"] is False


def test_recurring_task_status_uses_last_confirmed_completion_not_the_anchor():
    task = {"name": "checkpoint-confirmed", "cadence_days": 30, "anchor_date": date(2020, 1, 1)}
    operations_agent.mark_recurring_task_done("checkpoint-confirmed")
    status = operations_agent.recurring_task_status(task)
    # A recent confirmation must push the next due date far into the future, regardless
    # of how old the original anchor_date is.
    assert status["overdue"] is False
    assert status["days_until_due"] > 20


def test_mark_recurring_task_done_is_a_pure_record_update_not_invented_by_the_agent():
    from app.models import RecurringTaskCheckpointRecord
    task_name = "checkpoint-manual-unique-test-name"
    operations_agent.mark_recurring_task_done(task_name)
    with session_scope() as session:
        checkpoint = session.query(RecurringTaskCheckpointRecord).filter_by(task_name=task_name).one()
        assert checkpoint.last_completed_at is not None
