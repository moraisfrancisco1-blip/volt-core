from app.action_gate import ActionEnvironment, ActionStatus, evaluate_action


def approval(decision="approved", action="restart_service"):
    return {"id": 1, "decision": decision, "action": action}


def test_approved_safe_action_is_ready_in_staging():
    result = evaluate_action(approval(), ActionEnvironment.STAGING)
    assert result["status"] == ActionStatus.READY.value
    assert result["reason"] is None


def test_production_is_blocked_even_with_approval():
    result = evaluate_action(approval(), ActionEnvironment.PRODUCTION)
    assert result["status"] == ActionStatus.BLOCKED.value
    assert result["reason"] is not None


def test_unapproved_action_is_blocked():
    result = evaluate_action(approval(decision="pending"), ActionEnvironment.STAGING)
    assert result["status"] == ActionStatus.BLOCKED.value


def test_unknown_action_is_blocked():
    result = evaluate_action(approval(action="delete_database"), ActionEnvironment.STAGING)
    assert result["status"] == ActionStatus.BLOCKED.value
