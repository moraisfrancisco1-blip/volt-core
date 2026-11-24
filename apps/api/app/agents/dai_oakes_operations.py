from __future__ import annotations

from sqlalchemy import select

from ..db import session_scope
from ..models import AuditRecord, DaiOakesBookingsSnapshotRecord, DaiOakesOperationsInsightRecord

# Deterministic, zero-LLM, zero-network agent. It only reads the aggregate bookings
# snapshots the Back Office sweep already stored (counts by status/location/deposit) and
# writes advisory insights. It cannot act on anything: no approvals, no sends, no writes
# outside its own table. Thresholds are env-free constants on purpose -- easy to review.
CANCELLED_SHARE_ATTENTION = 0.20
DEPOSIT_PENDING_SHARE_ATTENTION = 0.30
NEXT_7_DAYS_DROP_ATTENTION = 0.50  # next-7-days count fell by half or more vs previous snapshot
MIN_SAMPLE = 10  # below this many bookings, ratios are noise -- say nothing


def _sum_matching(counts: dict | None, needles: tuple[str, ...]) -> int:
    # Status/deposit key names come from the clinic admin panel, which this repo does not
    # control, so match by substring (case-insensitive) rather than assume exact keys.
    if not isinstance(counts, dict):
        return 0
    total = 0
    for key, value in counts.items():
        if any(n in str(key).lower() for n in needles) and isinstance(value, (int, float)):
            total += int(value)
    return total


def _total(counts: dict | None) -> int:
    if not isinstance(counts, dict):
        return 0
    return sum(int(v) for v in counts.values() if isinstance(v, (int, float)))


def compute_insights(latest: DaiOakesBookingsSnapshotRecord, previous: DaiOakesBookingsSnapshotRecord | None) -> list[dict]:
    insights: list[dict] = []

    status_total = _total(latest.by_status)
    if status_total >= MIN_SAMPLE:
        cancelled = _sum_matching(latest.by_status, ("cancel", "no_show", "noshow", "no-show"))
        share = cancelled / status_total
        if share >= CANCELLED_SHARE_ATTENTION:
            insights.append({"kind": "cancellation_rate", "severity": "attention",
                             "message": f"{cancelled} de {status_total} marcações ({share:.0%}) estão canceladas ou em falta."})

    deposit_total = _total(latest.by_deposit_status)
    if deposit_total >= MIN_SAMPLE:
        pending = _sum_matching(latest.by_deposit_status, ("pending", "unpaid", "not_paid", "awaiting"))
        share = pending / deposit_total
        if share >= DEPOSIT_PENDING_SHARE_ATTENTION:
            insights.append({"kind": "deposit_pending", "severity": "attention",
                             "message": f"{pending} de {deposit_total} marcações ({share:.0%}) com sinal por pagar."})

    if previous is not None and previous.next_7_days_count >= MIN_SAMPLE:
        if latest.next_7_days_count <= previous.next_7_days_count * (1 - NEXT_7_DAYS_DROP_ATTENTION):
            insights.append({"kind": "agenda_drop", "severity": "attention",
                             "message": f"Marcações nos próximos 7 dias caíram de {previous.next_7_days_count} para {latest.next_7_days_count} desde a leitura anterior."})

    if latest.next_7_days_count == 0 and latest.total_bookings > 0:
        insights.append({"kind": "empty_week", "severity": "attention", "message": "Não há marcações nos próximos 7 dias."})

    if not insights:
        insights.append({"kind": "all_clear", "severity": "info", "message": "Sem sinais de atenção na última leitura da agenda."})
    return insights


def run_operations_insights() -> dict:
    with session_scope() as session:
        rows = session.scalars(select(DaiOakesBookingsSnapshotRecord).order_by(DaiOakesBookingsSnapshotRecord.id.desc()).limit(2)).all()
        if not rows:
            session.add(AuditRecord(type="dai_oakes_operations_skipped", detail="no bookings snapshot yet"))
            return {"ran": False, "reason": "no bookings snapshot yet (Back Office sweep must run first)", "insights": []}
        latest, previous = rows[0], (rows[1] if len(rows) > 1 else None)
        insights = compute_insights(latest, previous)
        for item in insights:
            session.add(DaiOakesOperationsInsightRecord(snapshot_id=latest.id, **item))
        session.add(AuditRecord(type="dai_oakes_operations_completed", detail=f"snapshot={latest.id} insights={len(insights)}"))
        return {"ran": True, "snapshot_id": latest.id, "insights": insights}
