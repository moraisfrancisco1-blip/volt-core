from app.integrations_router import integrations_status


def _by_name(results):
    return {row["name"]: row for row in results}


def test_all_configured_when_every_env_var_is_set(monkeypatch):
    monkeypatch.setenv("RAILWAY_TOKEN", "fake-railway-token")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-github-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "fake-sid")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "fake-auth-token")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+10000000000")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")

    results = _by_name(integrations_status())

    assert results["railway"]["configured"] is True
    assert results["github"]["configured"] is True
    assert results["postgres"]["configured"] is True
    assert results["twilio"]["configured"] is True
    assert results["anthropic"]["configured"] is True
    # Vercel is always derived from the hardcoded CORS origins list, not an env var.
    assert results["vercel"]["configured"] is True


def test_none_configured_when_every_env_var_is_unset(monkeypatch):
    for var in ("RAILWAY_TOKEN", "GITHUB_TOKEN", "DATABASE_URL", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    results = _by_name(integrations_status())

    assert results["railway"]["configured"] is False
    assert results["github"]["configured"] is False
    assert results["postgres"]["configured"] is False
    assert results["twilio"]["configured"] is False
    assert results["anthropic"]["configured"] is False
    # Vercel is unaffected by env vars -- always derived from CORS origins.
    assert results["vercel"]["configured"] is True


def test_twilio_requires_all_three_vars(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "fake-sid")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "fake-auth-token")
    monkeypatch.delenv("TWILIO_PHONE_NUMBER", raising=False)

    results = _by_name(integrations_status())

    assert results["twilio"]["configured"] is False


def test_response_never_leaks_secret_values(monkeypatch):
    secret_markers = {
        "RAILWAY_TOKEN": "MARKER_RAILWAY_SECRET",
        "GITHUB_TOKEN": "MARKER_GITHUB_SECRET",
        "DATABASE_URL": "postgresql://user:MARKER_DB_SECRET@host/db",
        "TWILIO_ACCOUNT_SID": "MARKER_TWILIO_SID",
        "TWILIO_AUTH_TOKEN": "MARKER_TWILIO_SECRET",
        "TWILIO_PHONE_NUMBER": "+1MARKER5550100",
        "ANTHROPIC_API_KEY": "MARKER_ANTHROPIC_SECRET",
    }
    for var, value in secret_markers.items():
        monkeypatch.setenv(var, value)

    results = integrations_status()

    combined = str(results)
    for marker in secret_markers.values():
        assert marker not in combined, f"secret value leaked into integrations status: {marker}"
