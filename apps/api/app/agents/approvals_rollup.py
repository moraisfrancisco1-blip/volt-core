from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import select

from ..db import session_scope
from ..models import (CustomerResponseDraftRecord, DaiOakesMarketingContentRecord, DealProposalRecord, MarketingContentRecord,
                      OperationsActivationRequestRecord, SalesOutreachDraftRecord)

# Read-only. Every department parks its output in its own *_pending_approval table; this
# gives Francisco ONE list instead of six endpoints. It approves nothing and sends nothing.
# (source key, model, summary builder) -- summaries are short and built only from fields the
# draft already holds.
SOURCES = [
    ("sales_outreach", SalesOutreachDraftRecord, lambda r: r.subject),
    ("deal_proposal", DealProposalRecord, lambda r: r.price_summary),
    ("marketing", MarketingContentRecord, lambda r: r.title),
    ("dai_oakes_marketing", DaiOakesMarketingContentRecord, lambda r: r.title),
    ("customer_response", CustomerResponseDraftRecord, lambda r: r.subject),
    ("operations_activation", OperationsActivationRequestRecord, lambda r: r.description),
]


def stale_hours() -> int:
    try:
        return max(1, int(os.getenv("VOLT_APPROVALS_STALE_HOURS", "48")))
    except ValueError:
        return 48


def pending_approvals(*, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    limit = stale_hours()
    items: list[dict] = []
    with session_scope() as session:
        for source, model, summarize in SOURCES:
            for row in session.scalars(select(model).where(model.status == "pending_approval")).all():
                created = row.created_at
                if created is not None and created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age = (now - created).total_seconds() / 3600 if created else 0.0
                items.append({"source": source, "id": row.id, "summary": (summarize(row) or "")[:140],
                              "age_hours": round(age, 1), "stale": age >= limit})
    items.sort(key=lambda i: -i["age_hours"])
    by_source: dict[str, int] = {}
    for item in items:
        by_source[item["source"]] = by_source.get(item["source"], 0) + 1
    return {"total": len(items), "stale": sum(1 for i in items if i["stale"]), "stale_after_hours": limit, "by_source": by_source, "items": items}
