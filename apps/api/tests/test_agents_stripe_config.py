from app.agents.stripe_config import resolve_stripe_key_env_var


def test_resolves_configured_system(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '{"daiane-oakes-admin":"STRIPE_SECRET_KEY_DAIANE_OAKES","voltaris-os":"STRIPE_SECRET_KEY_VOLTARIS_OS"}')
    assert resolve_stripe_key_env_var("daiane-oakes-admin") == "STRIPE_SECRET_KEY_DAIANE_OAKES"
    assert resolve_stripe_key_env_var("voltaris-os") == "STRIPE_SECRET_KEY_VOLTARIS_OS"


def test_missing_var_returns_none(monkeypatch):
    monkeypatch.delenv("VOLT_SYSTEM_STRIPE", raising=False)
    assert resolve_stripe_key_env_var("daiane-oakes-admin") is None


def test_unmapped_system_returns_none(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '{"daiane-oakes-admin":"STRIPE_SECRET_KEY_DAIANE_OAKES"}')
    assert resolve_stripe_key_env_var("some-other-system") is None


def test_malformed_json_returns_none(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", "{not valid json")
    assert resolve_stripe_key_env_var("daiane-oakes-admin") is None


def test_non_dict_payload_returns_none(monkeypatch):
    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '["daiane-oakes-admin"]')
    assert resolve_stripe_key_env_var("daiane-oakes-admin") is None


def test_malformed_env_var_name_returns_none(monkeypatch):
    # Lowercase, contains a dash, or looks like a key fragment rather than a var name --
    # all must fail closed rather than being passed blindly to os.getenv.
    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '{"daiane-oakes-admin":"stripe_secret_key"}')
    assert resolve_stripe_key_env_var("daiane-oakes-admin") is None

    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '{"daiane-oakes-admin":"STRIPE-SECRET-KEY"}')
    assert resolve_stripe_key_env_var("daiane-oakes-admin") is None

    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '{"daiane-oakes-admin":"sk_live_abc123"}')
    assert resolve_stripe_key_env_var("daiane-oakes-admin") is None

    monkeypatch.setenv("VOLT_SYSTEM_STRIPE", '{"daiane-oakes-admin":""}')
    assert resolve_stripe_key_env_var("daiane-oakes-admin") is None
