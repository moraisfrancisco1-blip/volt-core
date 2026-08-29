import hashlib
import secrets
from dataclasses import dataclass
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from .db import session_scope
from .models import ApiClientRecord


@dataclass(frozen=True)
class Principal:
    client_id: int
    name: str
    environment: str
    scopes: set[str]


def hash_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def authenticate(x_volt_key: str | None = Header(default=None)) -> Principal:
    if not x_volt_key:
        raise HTTPException(status_code=401, detail="missing VOLT API key")
    key_hash = hash_key(x_volt_key)
    with session_scope() as session:
        client = session.scalar(select(ApiClientRecord).where(ApiClientRecord.key_hash == key_hash, ApiClientRecord.enabled.is_(True)))
        if client is None or not secrets.compare_digest(client.key_hash, key_hash):
            raise HTTPException(status_code=401, detail="invalid VOLT API key")
        scopes = {scope.strip() for scope in client.scopes.split(",") if scope.strip()}
        return Principal(client_id=client.id, name=client.name, environment=client.environment, scopes=scopes)


def require_scope(scope: str):
    def dependency(principal: Principal = Depends(authenticate)) -> Principal:
        if scope not in principal.scopes and "*" not in principal.scopes:
            raise HTTPException(status_code=403, detail=f"missing scope: {scope}")
        return principal
    return dependency
