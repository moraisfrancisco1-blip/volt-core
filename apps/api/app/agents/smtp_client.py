from __future__ import annotations

import os
import smtplib
import socket
from email.message import EmailMessage


def send_email(to_address: str, subject: str, body: str) -> bool:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    # Returns False on any missing config or transport/auth failure rather than raising,
    # matching send_telegram_message's degrade-gracefully contract. This is the ONLY
    # function in the whole app that ever sends a real email, and it is only ever called
    # from the approve-and-send endpoint handler -- never from the agent's own sweep.
    host = os.getenv("VOLT_SMTP_HOST")
    user = os.getenv("VOLT_SMTP_USER")
    password = os.getenv("VOLT_SMTP_PASSWORD")
    from_address = os.getenv("VOLT_SMTP_FROM")
    if not host or not user or not password or not from_address:
        return False
    port = int(os.getenv("VOLT_SMTP_PORT", "587"))

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = to_address
    message.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=15) as client:
            client.starttls()
            client.login(user, password)
            client.send_message(message)
        return True
    except (smtplib.SMTPException, OSError, socket.error):
        return False
