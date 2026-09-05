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
