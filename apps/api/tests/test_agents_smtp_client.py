import smtplib

from app.agents import smtp_client


def test_send_email_returns_false_without_credentials(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)

    def spy(*args, **kwargs):
        raise AssertionError("smtplib.SMTP must not be constructed without full credentials")

    monkeypatch.setattr(smtp_client.smtplib, "SMTP", spy)

    assert smtp_client.send_email("prospect@example.com", "Subject", "Body") is False


class _FakeSMTP:
    sent_messages = []

    def __init__(self, host, port, timeout=None):
        _FakeSMTP.sent_messages.append(("connected", host, port))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, message):
        _FakeSMTP.sent_messages.append(("sent", message["To"], message["Subject"]))


def _configure_smtp_env(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "bot@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "fake-password")
    monkeypatch.setenv("SMTP_FROM", "sales@example.com")


def test_send_email_success(monkeypatch):
    _configure_smtp_env(monkeypatch)
    _FakeSMTP.sent_messages = []
    monkeypatch.setattr(smtp_client.smtplib, "SMTP", _FakeSMTP)

    result = smtp_client.send_email("prospect@example.com", "Parceria VoltarisOS", "Corpo do email")

    assert result is True
    assert ("sent", "prospect@example.com", "Parceria VoltarisOS") in _FakeSMTP.sent_messages


class _FailingSMTP:
    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        raise smtplib.SMTPConnectError(421, "simulated connection failure")

    def __exit__(self, *args):
        return False


def test_send_email_returns_false_on_smtp_failure(monkeypatch):
    _configure_smtp_env(monkeypatch)
    monkeypatch.setattr(smtp_client.smtplib, "SMTP", _FailingSMTP)

    assert smtp_client.send_email("prospect@example.com", "Subject", "Body") is False


def test_force_ipv4_resolution_filters_out_ipv6_results(monkeypatch):
    import socket

    fake_results = [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 587, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 587)),
    ]

    def fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        assert family == socket.AF_INET  # the whole point of the wrapper
        return [r for r in fake_results if r[0] == family]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with smtp_client._force_ipv4_resolution():
        results = socket.getaddrinfo("smtp.example.com", 587)

    assert results == [fake_results[1]]


def test_force_ipv4_resolution_restores_original_getaddrinfo_after_use():
    import socket

    original = socket.getaddrinfo
    with smtp_client._force_ipv4_resolution():
        assert socket.getaddrinfo is not original
    assert socket.getaddrinfo is original
