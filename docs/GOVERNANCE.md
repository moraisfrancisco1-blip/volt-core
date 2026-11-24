# Governance layer

Deterministic agents (no LLM, no API cost) that watch the other agents.

| Level | Agent | What it does |
|---|---|---|
| 1 | Chief of Staff | `POST /api/governance/daily-cycle` starts the cycle and writes the daily briefing (`GET /api/governance/briefings`). |
| 2 | Cost Governor | Ledger of every LLM call (`llm_usage`) plus optional budget guard. `GET /api/governance/usage?days=N`. |
| 2 | Approvals Rollup | One list of everything waiting for approval across 6 departments, with stale flags. `GET /api/governance/approvals`. |
| 2 | Output Auditor | Scans pending drafts. `POST /api/governance/audit/run`, `GET /api/governance/audit-findings`. |
| 3 | secret_checker, content_checker | Sub-checkers inside the Output Auditor. Secret and IBAN matches are never stored, only the rule name. |

With an LLM key configured the cycle goes through the agent inbox (FIFO, so the briefing runs after the sub-agents). Without one, the inbox worker is not running, so the cycle runs inline in the same order.

## Environment variables (all optional)
- `VOLT_LLM_PRICES`: JSON like `{"model": {"input_per_mtok": 1.0, "output_per_mtok": 5.0}}`. No prices are hard-coded; a model without a price reports tokens and cost "unknown".
- `VOLT_LLM_DAILY_TOKEN_BUDGET`: blocks new LLM calls once today's tokens reach this number.
- `VOLT_LLM_DAILY_BUDGET`: same, in money (needs `VOLT_LLM_PRICES`). Fails open if a price is missing.
- `VOLT_APPROVALS_STALE_HOURS` (default 48).

Nothing is enabled by default: with none of these set, existing agents behave exactly as before, apart from one extra row written per LLM call.
