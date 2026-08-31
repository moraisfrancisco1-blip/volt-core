from __future__ import annotations

import json
import os
import re


def resolve_stripe_key_env_var(system: str) -> str | None:
    raw = os.getenv("VOLT_SYSTEM_STRIPE", "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    env_var_name = str(payload.get(system) or "").strip()
    # Refuses to trust a malformed env var name -- fails closed with a clear
    # skip/audit trail instead of a confusing "not configured" failure later.
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", env_var_name):
        return None
    return env_var_name
