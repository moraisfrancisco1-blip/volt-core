from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from .db import session_scope
from .models import LLMUsageRecord

# Cost Governor core. Two jobs: (1) a ledger of every LLM call (tokens are real, from the
# provider response), (2) an optional budget guard. Nothing here is on by default: with no
# budget env var set, behaviour is identical to before this module existed.
#
# Prices are NEVER hard-coded. Providers change them, so they come from VOLT_LLM_PRICES, a
# JSON object like {"model-name": {"input_per_mtok": 1.0, "output_per_mtok": 5.0}} in
# whatever currency you budget in. A model with no configured price reports tokens only and
# cost "unknown" -- never a guessed number.


def caller_agent() -> str:
    # Attribute a call to the module that made it without touching ~25 call sites: walk
    # the stack to the first frame outside llm_client/usage_ledger. "app.agents.sales_agent"
    # -> "sales_agent". Falls back to "unknown" rather than ever raising.
    try:
        frame = sys._getframe(1)
        while frame is not None:
            module = frame.f_globals.get("__name__", "")
            if module and not module.endswith(("llm_client", "usage_ledger")):
                return module.rsplit(".", 1)[-1][:64]
            frame = frame.f_back
    except Exception:
        pass
    return "unknown"


def record_usage(*, agent: str, model: str, input_tokens: int | None, output_tokens: int | None) -> None:
    # Best-effort, same discipline as agent_inbox.post_message: a ledger write failure must
    # never break the LLM call that triggered it.
    try:
        with session_scope() as session:
            session.add(LLMUsageRecord(agent=agent, model=model[:96], input_tokens=int(input_tokens or 0), output_tokens=int(output_tokens or 0)))
    except Exception as exc:
        print(f"[volt-usage] ledger write failed: {type(exc).__name__}: {exc}")


def _prices() -> dict:
    raw = os.getenv("VOLT_LLM_PRICES", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _cost(model: str, input_tokens: int, output_tokens: int, prices: dict) -> float | None:
    entry = prices.get(model)
    if not isinstance(entry, dict):
        return None
    try:
        return input_tokens / 1_000_000 * float(entry["input_per_mtok"]) + output_tokens / 1_000_000 * float(entry["output_per_mtok"])
    except (KeyError, TypeError, ValueError):
        return None


def usage_report(*, days: int = 1, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    prices = _prices()
    with session_scope() as session:
        rows = session.execute(
            select(LLMUsageRecord.agent, LLMUsageRecord.model, func.count(), func.sum(LLMUsageRecord.input_tokens), func.sum(LLMUsageRecord.output_tokens))
            .where(LLMUsageRecord.created_at >= since)
            .group_by(LLMUsageRecord.agent, LLMUsageRecord.model)
        ).all()
    by_agent: dict[str, dict] = {}
    total_in = total_out = calls = 0
    total_cost: float | None = 0.0
    for agent, model, n, tin, tout in rows:
        tin, tout = int(tin or 0), int(tout or 0)
        cost = _cost(model, tin, tout, prices)
        entry = by_agent.setdefault(agent, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0, "cost_known": True})
        entry["calls"] += n; entry["input_tokens"] += tin; entry["output_tokens"] += tout
        if cost is None:
            entry["cost_known"] = False
            total_cost = None
        else:
            entry["cost"] += cost
            if total_cost is not None:
                total_cost += cost
        calls += n; total_in += tin; total_out += tout
    for entry in by_agent.values():
        entry["cost"] = round(entry["cost"], 6) if entry["cost_known"] else None
        del entry["cost_known"]
    return {
        "window_days": days, "calls": calls, "input_tokens": total_in, "output_tokens": total_out,
        "cost": round(total_cost, 6) if total_cost is not None else None,
        "cost_note": None if total_cost is not None or not rows else "preço em falta para pelo menos um modelo (VOLT_LLM_PRICES)",
        "by_agent": dict(sorted(by_agent.items(), key=lambda kv: -(kv[1]["input_tokens"] + kv[1]["output_tokens"]))),
    }


def budget_exceeded(*, now: datetime | None = None) -> str | None:
    # Returns a human reason when today's spend is over a configured budget, else None.
    # Both guards are opt-in. The token budget needs no prices; the money budget needs
    # VOLT_LLM_PRICES and fails OPEN (no block) if a price is missing, so a config typo
    # can't silently take every agent offline.
    token_budget = os.getenv("VOLT_LLM_DAILY_TOKEN_BUDGET", "").strip()
    money_budget = os.getenv("VOLT_LLM_DAILY_BUDGET", "").strip()
    if not token_budget and not money_budget:
        return None
    report = usage_report(days=1, now=now)
    if token_budget:
        try:
            limit = int(token_budget)
        except ValueError:
            limit = 0
        used = report["input_tokens"] + report["output_tokens"]
        if limit > 0 and used >= limit:
            return f"orçamento diário de tokens atingido ({used} de {limit})"
    if money_budget and report["cost"] is not None:
        try:
            limit_money = float(money_budget)
        except ValueError:
            limit_money = 0.0
        if limit_money > 0 and report["cost"] >= limit_money:
            return f"orçamento diário atingido ({report['cost']:.2f} de {limit_money:.2f})"
    return None
