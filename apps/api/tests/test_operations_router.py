from fastapi.testclient import TestClient

from app.agents import operations_agent
from app.db import session_scope
from app.main import app
from app.models import DealRecord, OnboardingRecord, OnboardingStepRecord, OperationsActivationRequestRecord, SalesLeadRecord


def _seed_lead(**overrides) -> int:
    defaults = dict(lead_type="tenant_signup", status="qualified", name="Bram Jansen", email="ops-router-test@example.com", consent_basis="existing_customer_tenant")
    defaults.update(overrides)
    with session_scope() as session:
        lead = SalesLeadRecord(**defaults)
        session.add(lead)
        session.flush()
        return lead.id


def _seed_deal(lead_id: int, **overrides) -> int:
    defaults = dict(lead_id=lead_id, stage="closed_won")
    defaults.update(overrides)
    with session_scope() as session:
        deal = DealRecord(**defaults)
        session.add(deal)
        session.flush()
        return deal.id


def _seed_onboarding_with_steps(deal_id: int) -> tuple[int, dict]:
    with session_scope() as session:
        onboarding = OnboardingRecord(deal_id=deal_id)
        session.add(onboarding)
        session.flush()
        step_ids = {}
        for index, (step_key, _label, requires_activation) in enumerate(operations_agent.STEP_DEFINITIONS):
            step = OnboardingStepRecord(onboarding_id=onboarding.id, step_key=step_key, order_index=index, requires_activation=requires_activation, status="pending")
            session.add(step)
            session.flush()
            step_ids[step_key] = step.id
        return onboarding.id, step_ids


# --- onboarding listing / detail -----------------------------------------------------------

def test_list_and_get_onboarding():
    lead_id = _seed_lead(email="list-onboarding@example.com")
    deal_id = _seed_deal(lead_id)
    onboarding_id, _steps = _seed_onboarding_with_steps(deal_id)

    with TestClient(app) as client:
        list_response = client.get("/api/onboardings")
        assert list_response.status_code == 200
        assert any(item["id"] == onboarding_id for item in list_response.json())

        get_response = client.get(f"/api/onboardings/{onboarding_id}")
        assert get_response.status_code == 200
        payload = get_response.json()
        assert payload["deal_id"] == deal_id
        assert payload["progress"] == {"done": 0, "total": 4}
        assert payload["stalled"] is False


def test_get_onboarding_missing_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/onboardings/999999")
        assert response.status_code == 404


# --- completing a non-activation step ------------------------------------------------------

def test_complete_step_advances_a_test_onboarding_through_two_steps():
    # Mirrors the verification checklist: show a test onboarding pass through at least
    # 2 checklist steps.
    lead_id = _seed_lead(email="two-steps@example.com")
    deal_id = _seed_deal(lead_id)
    onboarding_id, step_ids = _seed_onboarding_with_steps(deal_id)

    with TestClient(app) as client:
        first = client.post(f"/api/onboardings/{onboarding_id}/steps/{step_ids['initial_setup']}/complete")
        assert first.status_code == 200
        assert first.json()["progress"] == {"done": 1, "total": 4}

        second = client.post(f"/api/onboardings/{onboarding_id}/steps/{step_ids['first_data_sync']}/complete")
        assert second.status_code == 200
        assert second.json()["progress"] == {"done": 2, "total": 4}
        step_statuses = {s["step_key"]: s["status"] for s in second.json()["steps"]}
        assert step_statuses["initial_setup"] == "done"
        assert step_statuses["first_data_sync"] == "done"
        assert step_statuses["account_created"] == "pending"  # untouched -- requires activation


def test_complete_step_rejects_activation_requiring_step():
    lead_id = _seed_lead(email="reject-activation-complete@example.com")
    deal_id = _seed_deal(lead_id)
    onboarding_id, step_ids = _seed_onboarding_with_steps(deal_id)

    with TestClient(app) as client:
        response = client.post(f"/api/onboardings/{onboarding_id}/steps/{step_ids['account_created']}/complete")
        assert response.status_code == 422

    with session_scope() as session:
        step = session.get(OnboardingStepRecord, step_ids["account_created"])
        assert step.status == "pending"  # no real change happened


def test_complete_step_missing_onboarding_or_step_returns_404():
    lead_id = _seed_lead(email="missing-404@example.com")
    deal_id = _seed_deal(lead_id)
    onboarding_id, step_ids = _seed_onboarding_with_steps(deal_id)

    with TestClient(app) as client:
        assert client.post(f"/api/onboardings/999999/steps/{step_ids['initial_setup']}/complete").status_code == 404
        assert client.post(f"/api/onboardings/{onboarding_id}/steps/999999/complete").status_code == 404


def test_completing_all_non_activation_steps_leaves_onboarding_incomplete_until_activation_approved():
    lead_id = _seed_lead(email="incomplete-until-activation@example.com")
    deal_id = _seed_deal(lead_id)
    onboarding_id, step_ids = _seed_onboarding_with_steps(deal_id)

    with TestClient(app) as client:
        for key in ("initial_setup", "first_data_sync", "customer_confirmation"):
            client.post(f"/api/onboardings/{onboarding_id}/steps/{step_ids[key]}/complete")
        response = client.get(f"/api/onboardings/{onboarding_id}")
        assert response.json()["progress"] == {"done": 3, "total": 4}
        assert response.json()["completed_at"] is None


# --- activation requests: prepare via sweep, approve via dashboard --------------------------

def test_approve_activation_is_the_only_path_that_completes_account_created_step():
    lead_id = _seed_lead(email="approve-activation@example.com")
    deal_id = _seed_deal(lead_id)
    onboarding_id, step_ids = _seed_onboarding_with_steps(deal_id)
    with session_scope() as session:
        activation = OperationsActivationRequestRecord(onboarding_step_id=step_ids["account_created"], description="Ativar acesso para deal de teste.")
        session.add(activation)
        session.flush()
        activation_id = activation.id

    with TestClient(app) as client:
        list_response = client.get("/api/operations-activations?status=pending_approval")
        assert any(item["id"] == activation_id for item in list_response.json())

        approve_response = client.post(f"/api/operations-activations/{activation_id}/approve")
        assert approve_response.status_code == 200
        assert approve_response.json()["status"] == "approved"

    with session_scope() as session:
        step = session.get(OnboardingStepRecord, step_ids["account_created"])
        assert step.status == "done"
        assert step.completed_at is not None


def test_approve_activation_is_idempotent_against_double_click():
    lead_id = _seed_lead(email="double-click-activation@example.com")
    deal_id = _seed_deal(lead_id)
    onboarding_id, step_ids = _seed_onboarding_with_steps(deal_id)
    with session_scope() as session:
        activation = OperationsActivationRequestRecord(onboarding_step_id=step_ids["account_created"], description="Ativar acesso.")
        session.add(activation)
        session.flush()
        activation_id = activation.id

    with TestClient(app) as client:
        first = client.post(f"/api/operations-activations/{activation_id}/approve")
        second = client.post(f"/api/operations-activations/{activation_id}/approve")
        assert first.json()["status"] == "approved"
        assert second.json()["status"] == "approved"
        # SQLite (used in tests) doesn't round-trip tzinfo the way Postgres (production)
        # does, so compare only the naive timestamp portion, not the raw string.
        assert first.json()["approved_at"][:19] == second.json()["approved_at"][:19]


def test_approve_activation_missing_returns_404():
    with TestClient(app) as client:
        response = client.post("/api/operations-activations/999999/approve")
        assert response.status_code == 404


def test_full_onboarding_completes_only_after_activation_approved():
    lead_id = _seed_lead(email="full-completion@example.com")
    deal_id = _seed_deal(lead_id)
    onboarding_id, step_ids = _seed_onboarding_with_steps(deal_id)
    with session_scope() as session:
        activation = OperationsActivationRequestRecord(onboarding_step_id=step_ids["account_created"], description="Ativar acesso.")
        session.add(activation)
        session.flush()
        activation_id = activation.id

    with TestClient(app) as client:
        for key in ("initial_setup", "first_data_sync", "customer_confirmation"):
            client.post(f"/api/onboardings/{onboarding_id}/steps/{step_ids[key]}/complete")

        pre_response = client.get(f"/api/onboardings/{onboarding_id}")
        assert pre_response.json()["completed_at"] is None

        client.post(f"/api/operations-activations/{activation_id}/approve")

        post_response = client.get(f"/api/onboardings/{onboarding_id}")
        assert post_response.json()["progress"] == {"done": 4, "total": 4}
        assert post_response.json()["completed_at"] is not None


def test_end_to_end_sweep_then_approval_never_executes_a_real_activation_by_itself(monkeypatch):
    # Confirms the full pipeline (sweep prepares, human approves) never calls any real
    # external system -- there is no VoltarisOS/Stripe/billing client imported or used
    # anywhere in operations_agent.py or operations_router.py to begin with, so this test
    # asserts the observable contract: the sweep alone never marks the step done.
    lead_id = _seed_lead(email="e2e-no-auto-activation@example.com")
    deal_id = _seed_deal(lead_id)

    operations_agent.run_operations_sweep()

    with session_scope() as session:
        onboarding = session.query(OnboardingRecord).filter_by(deal_id=deal_id).one()
        account_step = session.query(OnboardingStepRecord).filter_by(onboarding_id=onboarding.id, step_key="account_created").one()
        assert account_step.status == "pending"
        activation = session.query(OperationsActivationRequestRecord).filter_by(onboarding_step_id=account_step.id).one()
        assert activation.status == "pending_approval"


# --- recurring tasks ------------------------------------------------------------------------

def test_list_recurring_tasks_reflects_env_configuration(monkeypatch):
    monkeypatch.setenv("VOLT_OPS_RECURRING_TASKS", '[{"name": "Checkpoint router test", "cadence_days": 14, "anchor_date": "2026-01-01"}]')
    with TestClient(app) as client:
        response = client.get("/api/operations/recurring-tasks")
        assert response.status_code == 200
        assert any(item["name"] == "Checkpoint router test" for item in response.json())


def test_list_recurring_tasks_empty_without_configuration(monkeypatch):
    monkeypatch.delenv("VOLT_OPS_RECURRING_TASKS", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/operations/recurring-tasks")
        assert response.status_code == 200
        assert response.json() == []


def test_mark_recurring_task_done_rejects_unconfigured_task(monkeypatch):
    monkeypatch.setenv("VOLT_OPS_RECURRING_TASKS", '[{"name": "Checkpoint real", "cadence_days": 14, "anchor_date": "2026-01-01"}]')
    with TestClient(app) as client:
        response = client.post("/api/operations/recurring-tasks/mark-done", json={"task_name": "Tarefa inventada"})
        assert response.status_code == 404


def test_mark_recurring_task_done_updates_status(monkeypatch):
    monkeypatch.setenv("VOLT_OPS_RECURRING_TASKS", '[{"name": "Checkpoint mark done", "cadence_days": 14, "anchor_date": "2020-01-01"}]')
    with TestClient(app) as client:
        response = client.post("/api/operations/recurring-tasks/mark-done", json={"task_name": "Checkpoint mark done"})
        assert response.status_code == 200
        assert response.json()["overdue"] is False


# --- run trigger -----------------------------------------------------------------------------

def test_trigger_operations_sweep_starts_without_any_llm_credentials(monkeypatch):
    # Unlike Sales/Deals/Marketing, Operations has no LLM dependency -- the trigger must
    # never be gated on ANTHROPIC_API_KEY/DEEPSEEK_API_KEY/OPENAI_API_KEY.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(app) as client:
        response = client.post("/api/operations/run")
        assert response.status_code == 200
        assert response.json()["triggered"] is True
