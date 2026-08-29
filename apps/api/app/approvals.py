from datetime import datetime, timezone
from enum import Enum


class ApprovalDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPLAIN = "explain"
    CANCELLED = "cancelled"


def create_approval(approval_id: int, event: dict, action: str) -> dict:
    return {
        "id": approval_id,
        "event_id": event["id"],
        "system": event["system"],
        "action": action,
        "decision": ApprovalDecision.PENDING.value,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decided_at": None,
    }


def apply_decision(approval: dict, decision: ApprovalDecision) -> dict:
    approval["decision"] = decision.value
    approval["decided_at"] = datetime.now(timezone.utc).isoformat()
    return approval
