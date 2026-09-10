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
        "VOLTARIS_SERVICE_KEY": "MARKER_VOLTARIS_SECRET",
        "VOLT_CORE_SERVICE_KEY_DAIOAKES": "MARKER_DAIOAKES_SECRET",
        "DAIOAKES_BASE_URL": "https://MARKER_DAIOAKES_HOST.example",
        "ENTSOE_API_TOKEN": "MARKER_ENTSOE_SECRET",
        "RESEND_API_KEY": "MARKER_RESEND_SECRET",
        "VOLT_SYSTEM_STRIPE": "MARKER_STRIPE_MAP_SECRET",
        "VOLT_SYSTEM_REPOS": "MARKER_REPOS_MAP_SECRET",
        "VOLT_SYSTEM_RAILWAY": "MARKER_RAILWAY_MAP_SECRET",
    }
    for var, value in secret_markers.items():
        monkeypatch.setenv(var, value)

    results = integrations_status()

    combined = str(results)
    for marker in secret_markers.values():
        assert marker not in combined, f"secret value leaked into integrations status: {marker}"


# --- external-system credentials (VoltarisOS, Dai Oakes, ENTSO-E, Resend, per-system maps) -

def test_voltaris_only_needs_the_service_key(monkeypatch):
    monkeypatch.delenv("VOLTARIS_BASE_URL", raising=False)
    monkeypatch.setenv("VOLTARIS_SERVICE_KEY", "fake-key")
    assert _by_name(integrations_status())["voltaris"]["configured"] is True


def test_daioakes_requires_both_key_and_base_url(monkeypatch):
    monkeypatch.setenv("VOLT_CORE_SERVICE_KEY_DAIOAKES", "fake-key")
    monkeypatch.delenv("DAIOAKES_BASE_URL", raising=False)
    assert _by_name(integrations_status())["daioakes"]["configured"] is False

    monkeypatch.setenv("DAIOAKES_BASE_URL", "https://admin.studiodaioakes.com")
    assert _by_name(integrations_status())["daioakes"]["configured"] is True


def test_daioakes_key_alone_without_base_url_is_not_configured(monkeypatch):
    monkeypatch.setenv("VOLT_CORE_SERVICE_KEY_DAIOAKES", "fake-key")
    monkeypatch.delenv("DAIOAKES_BASE_URL", raising=False)
    assert _by_name(integrations_status())["daioakes"]["configured"] is False


def test_entsoe_resend_and_system_maps_report_presence(monkeypatch):
    monkeypatch.setenv("ENTSOE_API_TOKEN", "fake-token")
    monkeypatch.setenv("RESEND_API_KEY", "fake-key")
    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '{"voltaris-os": "STRIPE_SECRET_KEY_VOLTARISOS"}')
    monkeypatch.setenv("VOLT_SYSTEM_REPOS", '{"voltaris-os": {"owner": "x", "repo": "y"}}')
    monkeypatch.setenv("VOLT_SYSTEM_RAILWAY", '{"voltaris-os": "svc-id"}')

    results = _by_name(integrations_status())

    assert results["entsoe"]["configured"] is True
    assert results["resend"]["configured"] is True
    assert results["stripe"]["configured"] is True
    assert results["system_repos"]["configured"] is True
    assert results["system_railway"]["configured"] is True
