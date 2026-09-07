import httpx

from app.agents import external_connector
from app.agents.external_connector import ExternalConnectorConfig


def _config() -> ExternalConnectorConfig:
    return ExternalConnectorConfig(name="test-system", base_url="https://example.test", api_key_env_var="TEST_CONNECTOR_KEY")


class FakeResponse:
    def __init__(self, status_code, payload=None, raise_on_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_on_json = raise_on_json

    def json(self):
        if self._raise_on_json:
            raise ValueError("not json")
        return self._payload


def test_get_missing_api_key_returns_error_without_any_network_call(monkeypatch):
    monkeypatch.delenv("TEST_CONNECTOR_KEY", raising=False)

    def _forbidden(*args, **kwargs):
        raise AssertionError("must not attempt a network call without an API key configured")

    monkeypatch.setattr(httpx, "Client", _forbidden)

    result = external_connector.get(_config(), "/api/thing")
    assert result == {"error": "TEST_CONNECTOR_KEY not configured"}


def test_get_success_returns_data(monkeypatch):
    monkeypatch.setenv("TEST_CONNECTOR_KEY", "secret123")
    seen = {}

    class FakeClient:
        def __init__(self, base_url, timeout):
            seen["base_url"] = base_url

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, path, headers=None, params=None):
            seen["path"] = path
            seen["headers"] = headers
            seen["params"] = params
            return FakeResponse(200, {"ok": True})

    monkeypatch.setattr(httpx, "Client", FakeClient)
    result = external_connector.get(_config(), "/api/thing", params={"a": 1})

    assert result == {"data": {"ok": True}}
    assert seen["base_url"] == "https://example.test"
    assert seen["path"] == "/api/thing"
    assert seen["headers"] == {"Authorization": "Bearer secret123"}
    assert seen["params"] == {"a": 1}


def test_get_http_error_status_surfaces_as_error(monkeypatch):
    monkeypatch.setenv("TEST_CONNECTOR_KEY", "secret123")

    class FakeClient:
        def __init__(self, base_url, timeout): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, path, headers=None, params=None): return FakeResponse(401)

    monkeypatch.setattr(httpx, "Client", FakeClient)
    result = external_connector.get(_config(), "/api/thing")
    assert result == {"error": "test-system API returned 401"}


def test_get_network_failure_surfaces_as_error(monkeypatch):
    monkeypatch.setenv("TEST_CONNECTOR_KEY", "secret123")

    class FakeClient:
        def __init__(self, base_url, timeout): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, path, headers=None, params=None): raise httpx.ConnectTimeout("boom")

    monkeypatch.setattr(httpx, "Client", FakeClient)
    result = external_connector.get(_config(), "/api/thing")
    assert "network/transport error" in result["error"]


def test_get_non_json_response_surfaces_as_error(monkeypatch):
    monkeypatch.setenv("TEST_CONNECTOR_KEY", "secret123")

    class FakeClient:
        def __init__(self, base_url, timeout): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, path, headers=None, params=None): return FakeResponse(200, raise_on_json=True)

    monkeypatch.setattr(httpx, "Client", FakeClient)
    result = external_connector.get(_config(), "/api/thing")
    assert "non-JSON response" in result["error"]
