from __future__ import annotations

import contextlib
import os
import smtplib
import socket
import threading
from email.message import EmailMessage

# Railway's network only routes IPv4 -- if the SMTP host's DNS record also has an AAAA
# entry, the stdlib's default dual-stack resolution can hand smtplib an unroutable IPv6
# address ("Network is unreachable"). Forcing getaddrinfo to IPv4-only for the duration
# of the connection fixes this without resolving the hostname ourselves, which would
# break TLS server-hostname verification in starttls() (the certificate is issued for
# the domain, not the IP). Scoped with a lock since this mutates process-global state.
_ipv4_only_lock = threading.Lock()


@contextlib.contextmanager
def _force_ipv4_resolution():
    original_getaddrinfo = socket.getaddrinfo

    def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
        return original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    with _ipv4_only_lock:
        socket.getaddrinfo = _ipv4_only
        try:
            yield
        finally:
            socket.getaddrinfo = original_getaddrinfo


def send_email(to_address: str, subject: str, body: str) -> bool:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    # Returns False on any missing config or transport/auth failure rather than raising,
    # matching send_telegram_message's degrade-gracefully contract. This is the ONLY
    # function in the whole app that ever sends a real email, and it is only ever called
    # from the approve-and-send endpoint handler -- never from the agent's own sweep.
    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    from_address = os.getenv("SMTP_FROM")
    if not host or not user or not password or not from_address:
        return False
    port = int(os.getenv("SMTP_PORT", "587"))

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = to_address
    message.set_content(body)

    try:
        with _force_ipv4_resolution(), smtplib.SMTP(host, port, timeout=15) as client:
            client.starttls()
            client.login(user, password)
            client.send_message(message)
        return True
    except (smtplib.SMTPException, OSError, socket.error) as exc:
        # Never leak the password, but the exception type/message alone (e.g. "auth
        # failed", "connection refused") is the only way to diagnose a real SMTP
        # provider from Railway's deploy logs without exposing credentials.
        print(f"[volt-core-sales] SMTP send failed: {type(exc).__name__}: {exc}")
        return False
