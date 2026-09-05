from __future__ import annotations

import os

import httpx

_API_BASE = "https://api.resend.com"


def _resend_request(payload: dict) -> httpx.Response | None:
    # The single seam tests substitute -- never touches the network once monkeypatched.
    # Returns None only on a transport-level failure; non-2xx statuses (e.g. an
    # unverified sender domain) come back as a normal Response for the caller to
    # interpret, same discipline as every other HTTP client seam in this codebase.
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        return None
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        with httpx.Client(base_url=_API_BASE, timeout=15) as client:
            return client.post("/emails", json=payload, headers=headers)
    except httpx.HTTPError:
        return None


def send_email(to_address: str, subject: str, body: str) -> bool:
    # Returns False on any missing config or transport/API failure rather than raising,
    # matching send_telegram_message's degrade-gracefully contract. This is the ONLY
    # function in the whole app that ever sends a real email, and it is only ever
    # called from the approve-and-send endpoint handler -- never from the agent's own
    # sweep. Uses Resend's HTTPS API instead of raw SMTP because Railway blocks
    # outbound SMTP entirely below its Pro plan (confirmed via Railway's own docs);
    # an HTTPS API works on every plan.
    from_address = os.getenv("RESEND_FROM")
    if not from_address:
        return False

    response = _resend_request({"from": from_address, "to": [to_address], "subject": subject, "text": body})
    if response is None:
        print("[volt-core-sales] Resend send failed: network/transport error")
        return False
    if response.status_code >= 300:
        print(f"[volt-core-sales] Resend send failed: HTTP {response.status_code}: {response.text[:500]}")
        return False
    return True
