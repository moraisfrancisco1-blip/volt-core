import hashlib
import os
import secrets
from fastapi import Header, HTTPException


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def get_api_keys() -> set[str]:
    raw = os.getenv("VOLT_API_KEYS", "")
    return {_hash(key.strip()) for key in raw.split(",") if key.strip()}


def require_api_key(x_volt_key: str | None = Header(default=None)) -> str:
    keys = get_api_keys()
    if not keys:
        raise HTTPException(status_code=503, detail="VOLT API authentication is not configured")
    if not x_volt_key or not any(secrets.compare_digest(_hash(x_volt_key), key) for key in keys):
        raise HTTPException(status_code=401, detail="invalid VOLT API key")
    return x_volt_key
