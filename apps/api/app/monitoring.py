from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from .auth import Principal
from .db import session_scope
from .event_history import EventIngestion, create_event
from .models import SystemRecord


@dataclass(frozen=True)
class MonitorTarget:
    system_id: str
    system_name: str
    environment: str
    url: str


@dataclass
class MonitorState:
    consecutive_failures: int = 0
    incident_open: bool = False
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_detail: str | None = None
    last_ok: bool | None = None


_state: dict[str, MonitorState] = {}
_started = False
_lock = threading.Lock()


def _parse_targets() -> list[MonitorTarget]:
    raw = os.getenv("VOLT_MONITOR_TARGETS", "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    targets: list[MonitorTarget] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        system_id = str(item.get("system_id") or "").strip()
        url = str(item.get("url") or "").strip().rstrip("/")
        if not system_id or not url.startswith(("http://", "https://")):
            continue
        targets.append(MonitorTarget(
            system_id=system_id[:120],
            system_name=str(item.get("system_name") or system_id)[:160],
            environment=str(item.get("environment") or "production")[:32],
            url=url,
        ))
    return targets


def monitoring_status() -> dict:
    targets = _parse_targets()
    timeout_seconds = max(1, int(os.getenv("VOLT_MONITOR_TIMEOUT_SECONDS", "8")))
    failure_threshold = max(1, int(os.getenv("VOLT_MONITOR_FAILURE_THRESHOLD", "3")))
    interval_seconds = max(15, int(os.getenv("VOLT_MONITOR_INTERVAL_SECONDS", "60")))
    items = []
    for target in targets:
        state = _state.get(target.system_id)
        items.append({
            "system_id": target.system_id,
            "system_name": target.system_name,
            "environment": target.environment,
            "url": target.url,
            "last_checked_at": state.last_checked_at.isoformat() if state and state.last_checked_at else None,
            "last_success_at": state.last_success_at.isoformat() if state and state.last_success_at else None,
            "last_detail": state.last_detail if state else None,
            "last_ok": state.last_ok if state else None,
            "consecutive_failures": state.consecutive_failures if state else 0,
            "incident_open": state.incident_open if state else False,
        })
    return {
        "started": _started,
        "target_count": len(targets),
        "interval_seconds": interval_seconds,
        "timeout_seconds": timeout_seconds,
        "failure_threshold": failure_threshold,
        "targets": items,
    }


def _check(url: str, timeout_seconds: int) -> tuple[bool, str]:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "VOLT-CORE-Monitor/1.0"})
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", response.getcode())
            return 200 <= status < 300, f"HTTP {status}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:220]}"


def _touch_system(session, target: MonitorTarget, status: str) -> None:
    now = datetime.now(timezone.utc)
    system = session.scalar(select(SystemRecord).where(SystemRecord.name == target.system_id))
    if system is None:
        system = SystemRecord(name=target.system_id, environment=target.environment, status=status, updated_at=now)
        session.add(system)
    else:
        system.environment = target.environment
        system.status = status
        system.updated_at = now


def _principal(target: MonitorTarget) -> Principal:
    return Principal(client_id=0, name="volt-core-monitor", environment=target.environment, scopes={"*"})


def monitor_once() -> None:
    timeout_seconds = max(1, int(os.getenv("VOLT_MONITOR_TIMEOUT_SECONDS", "8")))
    failure_threshold = max(1, int(os.getenv("VOLT_MONITOR_FAILURE_THRESHOLD", "3")))

    for target in _parse_targets():
        ok, detail = _check(target.url, timeout_seconds)
        now = datetime.now(timezone.utc)
        state = _state.setdefault(target.system_id, MonitorState())
        state.last_checked_at = now
        state.last_detail = detail
        state.last_ok = ok

        if ok:
            state.last_success_at = now
            recovered = state.incident_open
            state.consecutive_failures = 0
            state.incident_open = False
            with session_scope() as session:
                _touch_system(session, target, "connected")
                if recovered:
                    create_event(session, EventIngestion(
                        system_id=target.system_id,
                        system_name=target.system_name,
                        environment=target.environment,
                        severity="info",
                        event_type="monitor_recovery",
                        title="System recovered",
                        message=f"Health check recovered: {detail}",
                        source="volt-core-monitor",
                        metadata={"url": target.url},
                    ), _principal(target))
            continue

        state.consecutive_failures += 1
        status = "degraded" if state.consecutive_failures < failure_threshold else "down"
        with session_scope() as session:
            _touch_system(session, target, status)
            if state.consecutive_failures >= failure_threshold and not state.incident_open:
                state.incident_open = True
                create_event(session, EventIngestion(
                    system_id=target.system_id,
                    system_name=target.system_name,
                    environment=target.environment,
                    severity="high",
                    event_type="monitor_health_failure",
                    title="System health check failed",
                    message=f"{failure_threshold} consecutive health-check failures. Latest result: {detail}",
                    source="volt-core-monitor",
                    metadata={"url": target.url, "consecutive_failures": state.consecutive_failures},
                ), _principal(target))


def _monitor_loop() -> None:
    interval_seconds = max(15, int(os.getenv("VOLT_MONITOR_INTERVAL_SECONDS", "60")))
    while True:
        try:
            monitor_once()
        except Exception as exc:
            print(f"[monitor] loop failure: {type(exc).__name__}: {exc}")
        time.sleep(interval_seconds)


def start_monitoring() -> None:
    global _started
    if _started or not _parse_targets():
        return
    with _lock:
        if _started:
            return
        monitor_once()
        thread = threading.Thread(target=_monitor_loop, name="volt-core-monitor", daemon=True)
        thread.start()
        _started = True
