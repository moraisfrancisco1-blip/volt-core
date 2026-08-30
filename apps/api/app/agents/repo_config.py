from __future__ import annotations

import json
import os


def resolve_repo(system: str) -> tuple[str, str] | None:
    raw = os.getenv("VOLT_SYSTEM_REPOS", "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    repo_ref = str(payload.get(system) or "").strip()
    if repo_ref.count("/") != 1:
        return None
    owner, _, repo = repo_ref.partition("/")
    return (owner, repo) if owner and repo else None
