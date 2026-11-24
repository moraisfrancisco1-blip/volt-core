from fastapi.testclient import TestClient

from app.agents import dai_oakes_operations
from app.db import session_scope
from app.main import app
from app.models import AuditRecord, DaiOakesBookingsSnapshotRecord, DaiOakesOperationsInsightRecord


def _snap(**kw):
    d = dict(total_bookings=40, today_count=3, next_7_days_count=20,
             by_status={"confirmed": 35, "cancelled": 5}, by_location={"Rotterdam": 40}, by_deposit_status={"paid": 38, "pending": 2})
    d.update(kw)
    return DaiOakesBookingsSnapshotRecord(**d)


def test_all_clear_when_nothing_is_off():
    assert [i["kind"] for i in dai_oakes_operations.compute_insights(_snap(), None)] == ["all_clear"]


def test_flags_high_cancellation_and_pending_deposit():
    latest = _snap(by_status={"confirmed": 20, "Cancelled": 8, "no_show": 2}, by_deposit_status={"paid": 15, "pending": 15})
    kinds = {i["kind"] for i in dai_oakes_operations.compute_insights(latest, None)}
    assert {"cancellation_rate", "deposit_pending"} <= kinds


def test_small_samples_are_ignored():
    latest = _snap(by_status={"confirmed": 1, "cancelled": 3}, by_deposit_status={"pending": 4})
    assert [i["kind"] for i in dai_oakes_operations.compute_insights(latest, None)] == ["all_clear"]


def test_agenda_drop_and_empty_week():
    kinds = [i["kind"] for i in dai_oakes_operations.compute_insights(_snap(next_7_days_count=4), _snap(next_7_days_count=20))]
    assert "agenda_drop" in kinds
    kinds = [i["kind"] for i in dai_oakes_operations.compute_insights(_snap(next_7_days_count=0), None)]
    assert "empty_week" in kinds


def test_unknown_or_missing_json_fields_never_crash():
    latest = _snap(by_status=None, by_deposit_status={"weird": "x"})
    assert [i["kind"] for i in dai_oakes_operations.compute_insights(latest, None)] == ["all_clear"]


def test_run_without_snapshot_is_skipped_and_audited():
    with session_scope() as s:
        s.query(DaiOakesBookingsSnapshotRecord).delete()
    result = dai_oakes_operations.run_operations_insights()
    assert result["ran"] is False
    with session_scope() as s:
        assert s.query(AuditRecord).filter(AuditRecord.type == "dai_oakes_operations_skipped").count() >= 1


def test_run_endpoint_persists_insights_and_list_returns_them():
    with session_scope() as s:
        s.query(DaiOakesBookingsSnapshotRecord).delete()
        s.add(_snap(next_7_days_count=0))
    with TestClient(app) as client:
        assert client.post("/api/dai-oakes-operations/run").json()["ran"] is True
        items = client.get("/api/dai-oakes-operations-insights").json()
        assert any(i["kind"] == "empty_week" for i in items)
    with session_scope() as s:
        assert s.query(DaiOakesOperationsInsightRecord).count() >= 1
