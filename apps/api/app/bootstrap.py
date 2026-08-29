import os
from .auth import hash_key
from .db import session_scope
from .models import ApiClientRecord


def _ensure_client(name: str, key: str, environment: str, scopes: str) -> None:
    with session_scope() as session:
        existing = next((row for row in session.query(ApiClientRecord).filter_by(name=name).all()), None)
        if existing is None:
            session.add(ApiClientRecord(
                name=name,
                key_hash=hash_key(key),
                environment=environment,
                scopes=scopes,
                enabled=True,
            ))


def bootstrap_admin() -> None:
    name = os.getenv("VOLT_BOOTSTRAP_CLIENT")
    key = os.getenv("VOLT_BOOTSTRAP_KEY")
    if name and key:
        _ensure_client(name, key, "production", "*")

    watch_name = os.getenv("VOLT_WATCH_CLIENT")
    watch_key = os.getenv("VOLT_WATCH_CLIENT_KEY")
    if watch_name and watch_key:
        _ensure_client(watch_name, watch_key, "production", "watch:write")
