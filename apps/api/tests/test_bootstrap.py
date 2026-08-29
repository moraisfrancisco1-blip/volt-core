from app.bootstrap import bootstrap_admin
from app.db import session_scope
from app.models import ApiClientRecord


def test_bootstrap_creates_least_privilege_watch_client(monkeypatch):
    monkeypatch.setenv("VOLT_WATCH_CLIENT", "daiane-oakes-admin")
    monkeypatch.setenv("VOLT_WATCH_CLIENT_KEY", "watch-test-key")
    monkeypatch.delenv("VOLT_BOOTSTRAP_CLIENT", raising=False)
    monkeypatch.delenv("VOLT_BOOTSTRAP_KEY", raising=False)

    bootstrap_admin()

    with session_scope() as session:
        client = next((row for row in session.query(ApiClientRecord).filter_by(name="daiane-oakes-admin").all()), None)
        assert client is not None
        assert client.scopes == "watch:write"
        assert client.environment == "production"
