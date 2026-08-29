from datetime import datetime, timezone
from enum import Enum


class ActionEnvironment(str, Enum):
    STAGING = "staging"
    PRODUCTION = "production"


class ActionStatus(str, Enum):
    BLOCKED = "blocked"
    READY = "ready"
    EXECUTED = "executed"


SAFE_ACTIONS = {
    "restart_service",
    "retry_job",
    "refresh_connector",
}


def evaluate_action(approval: dict, environment: ActionEnvironment) -> dict:
    approved = approval["decision"] == "approved"
    allowed = approved and environment == ActionEnvironment.STAGING and approval["action"] in SAFE_ACTIONS
    return {
        "approval_id": approval["id"],
        "action": approval["action"],
        "environment": environment.value,
        "status": ActionStatus.READY.value if allowed else ActionStatus.BLOCKED.value,
        "reason": None if allowed else "Action requires approved safe action in staging",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
