from __future__ import annotations

import os
import queue
import threading

from ..db import session_scope
from ..models import AuditRecord
from .tools import InvestigationJob

_queue: "queue.Queue[InvestigationJob]" = queue.Queue(maxsize=int(os.getenv("VOLT_JARVIS_QUEUE_MAXSIZE", "50")))
_started = False
_lock = threading.Lock()


def enqueue_investigation(*, event_id: int, escalation_id: int, system: str, environment: str, priority: str) -> None:
    job = InvestigationJob(event_id=event_id, escalation_id=escalation_id, system=system, environment=environment, priority=priority)
    try:
        _queue.put_nowait(job)
    except Exception as exc:
        # Best-effort: a full queue or any other enqueue failure must never propagate
        # back into the escalation state machine that called this.
        with session_scope() as session:
            session.add(AuditRecord(type="investigation_enqueue_failed", reference_id=str(event_id), detail=str(exc)[:500]))


def _worker_loop() -> None:
    from . import runner  # imported lazily so importing this module never constructs an Anthropic client

    while True:
        job = _queue.get()
        try:
            runner.run_investigation(job)
        except Exception as exc:
            print(f"[jarvis] investigation failure: {type(exc).__name__}: {exc}")
        finally:
            _queue.task_done()


def start_investigation_worker() -> None:
    global _started
    # Mirrors monitoring.py's start_monitoring(): only run the background worker when
    # there's actually something for it to do. Without a key, jobs still enqueue fine
    # (harmless, bounded by VOLT_JARVIS_QUEUE_MAXSIZE) but nothing ever consumes them --
    # this specifically keeps every existing test that exercises the escalation/voice
    # flow (and therefore calls enqueue_investigation) from spinning up a thread that
    # would try to construct a real Anthropic client in the background.
    if _started or not os.getenv("ANTHROPIC_API_KEY"):
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_worker_loop, name="volt-core-jarvis", daemon=True).start()
        _started = True
