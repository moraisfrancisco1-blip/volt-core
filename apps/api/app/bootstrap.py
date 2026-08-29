import os
from .auth import hash_key
from .db import session_scope
from .models import ApiClientRecord


def bootstrap_admin() -> None:
    name = os.getenv("VOLT_BOOTSTRAP_CLIENT")
    key = os.getenv("VOLT_BOOTSTRAP_KEY")
    if not name or not key:
        return
    with session_scope() as session:
        existing = next((row for row in session.query(ApiClientRecord).filter_by(name=name).all()), None)
        if existing is None:
            session.add(ApiClientRecord(
                name=name,
                key_hash=hash_key(key),
                environment="production",
                scopes="*",
                enabled=True,
            ))
