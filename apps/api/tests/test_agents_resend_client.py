from types import SimpleNamespace

from app.agents import resend_client


def _fake_response(status_code=200, text=""):
    return SimpleNamespace(status_code=status_code, text=text)


def test_send_email_returns_false_without_api_key(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("RESEND_FROM", "sales@example.com")

    def spy(*args, **kwargs):
        raise AssertionError("httpx.Client must not be constructed without RESEND_API_KEY")

    monkeypatch.setattr(resend_client.httpx, "Client", spy)

    assert resend_client.send_email("prospect@example.com", "Subject", "Body") is False


def test_send_email_returns_false_without_from_address(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "fake-key")
    monkeypatch.delenv("RESEND_FROM", raising=False)

    def spy(*args, **kwargs):
        raise AssertionError("_resend_request must not be called without RESEND_FROM")

    monkeypatch.setattr(resend_client, "_resend_request", spy)

    assert resend_client.send_email("prospect@example.com", "Subject", "Body") is False


def test_send_email_success(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "fake-key")
    monkeypatch.setenv("RESEND_FROM", "sales@example.com")
    captured = {}

    def fake_request(payload):
        captured.update(payload)
        return _fake_response(200)

    monkeypatch.setattr(resend_client, "_resend_request", fake_request)

    result = resend_client.send_email("prospect@example.com", "Parceria VoltarisOS", "Corpo do email")

    assert result is True
    assert captured == {"from": "sales@example.com", "to": ["prospect@example.com"], "subject": "Parceria VoltarisOS", "text": "Corpo do email"}


def test_send_email_returns_false_on_non_2xx(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "fake-key")
    monkeypatch.setenv("RESEND_FROM", "sales@example.com")
    monkeypatch.setattr(resend_client, "_resend_request", lambda payload: _fake_response(422, "domain not verified"))

    assert resend_client.send_email("prospect@example.com", "Subject", "Body") is False


def test_send_email_returns_false_on_transport_failure(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "fake-key")
    monkeypatch.setenv("RESEND_FROM", "sales@example.com")
    monkeypatch.setattr(resend_client, "_resend_request", lambda payload: None)

    assert resend_client.send_email("prospect@example.com", "Subject", "Body") is False


def test_resend_request_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert resend_client._resend_request({}) is None
