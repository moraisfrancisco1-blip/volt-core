from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .models import EventRecord

BASE_PRIORITY = {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4", "info": "P4"}
ACTION_BY_PRIORITY = {"P1": "call", "P2": "call", "P3": "call", "P4": "digest"}
KEYWORD_ESCALATION = {
    "security breach": "P1", "security": "P1", "data loss": "P1", "payment": "P1",
    "database": "P1", "unavailable": "P2", "down": "P2", "health check failed": "P2", "timeout": "P2",
}
PRIORITY_ORDER = {"P4": 1, "P3": 2, "P2": 3, "P1": 4}


@dataclass(frozen=True)
class Decision:
    priority: str
    action: str
    reason: str
    duplicate: bool


def _max_priority(left: str, right: str) -> str:
    return left if PRIORITY_ORDER[left] >= PRIORITY_ORDER[right] else right


def decide_event(session, *, severity: str, system_id: str, environment: str, event_type: str | None, title: str | None, message: str, now: datetime | None = None) -> Decision:
    now = now or datetime.now(timezone.utc)
    priority = BASE_PRIORITY[severity]
    reasons = [f"base severity {severity}"]
    text = " ".join(filter(None, [event_type, title, message])).lower()

    for keyword, candidate in KEYWORD_ESCALATION.items():
        if keyword in text:
            upgraded = _max_priority(priority, candidate)
            if upgraded != priority:
                priority = upgraded
                reasons.append(f"keyword escalation: {keyword}")

    window_start = now - timedelta(minutes=10)
    recent = session.scalars(select(EventRecord).where(EventRecord.system_id == system_id, EventRecord.environment == environment, EventRecord.created_at >= window_start, EventRecord.status != "resolved")).all()
    fingerprint = (event_type or "", (title or "").strip().lower(), message.strip().lower())
    same = [item for item in recent if ((item.event_type or ""), (item.title or "").strip().lower(), item.message.strip().lower()) == fingerprint]
    duplicate = len(same) > 0

    if len(same) >= 2:
        priority = _max_priority(priority, "P2")
        reasons.append(f"repeated active incident ({len(same) + 1} occurrences in 10m)")

    distinct_recent = {(item.event_type or "", (item.title or "").strip().lower()) for item in recent}
    if len(distinct_recent) >= 3:
        priority = _max_priority(priority, "P2")
        reasons.append(f"incident burst ({len(distinct_recent)} active incident types in 10m)")

    if severity == "critical":
        priority = "P1"
        reasons.append("critical incident")

    return Decision(priority=priority, action=ACTION_BY_PRIORITY[priority], reason="; ".join(dict.fromkeys(reasons)), duplicate=duplicate)


def validate_decision_matrix() -> list[dict]:
    cases = [
        ("critical", "routine", "critical service failure", "P1", "call"),
        ("high", "routine", "service unavailable", "P2", "call"),
        ("medium", "routine", "degraded performance", "P3", "call"),
        ("low", "routine", "minor informational notice", "P4", "digest"),
        ("info", "routine", "informational update", "P4", "digest"),
        ("low", "security breach", "access incident", "P1", "call"),
    ]
    results = []
    for severity, event_type, message, expected_priority, expected_action in cases:
        priority = BASE_PRIORITY[severity]
        text = f"{event_type} {message}".lower()
        for keyword, candidate in KEYWORD_ESCALATION.items():
            if keyword in text: priority = _max_priority(priority, candidate)
        if severity == "critical": priority = "P1"
        action = ACTION_BY_PRIORITY[priority]
        results.append({"severity": severity, "expected_priority": expected_priority, "actual_priority": priority, "expected_action": expected_action, "actual_action": action, "ok": priority == expected_priority and action == expected_action})
    return results
