import html
import os
import secrets
from typing import Protocol


class VoiceProvider(Protocol):
    def place_call(self, to: str, script: str, *, status_callback: str | None = None) -> dict: ...


class MockVoiceProvider:
    def place_call(self, to: str, script: str, *, status_callback: str | None = None) -> dict:
        # A synthetic but unique sid, so a status callback can still be simulated/tested
        # against a mock-dispatched call the same way it would against a real Twilio one.
        return {"provider": "mock", "status": "queued", "to": to, "script": script, "sid": f"MOCKCA{secrets.token_hex(16)}"}


class TwilioVoiceProvider:
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        from twilio.rest import Client

        self.client = Client(account_sid, auth_token)
        self.from_number = from_number

    def place_call(self, to: str, script: str, *, status_callback: str | None = None) -> dict:
        twiml = f"<Response><Say language='en-US'>{html.escape(script)}</Say></Response>"
        create_kwargs = {"to": to, "from_": self.from_number, "twiml": twiml}
        if status_callback:
            create_kwargs.update(
                status_callback=status_callback,
                status_callback_method="POST",
                status_callback_event=["initiated", "ringing", "answered", "completed"],
            )
        call = self.client.calls.create(**create_kwargs)
        return {
            "provider": "twilio",
            "status": call.status or "queued",
            "to": to,
            "script": script,
            "sid": call.sid,
        }


def get_voice_provider() -> VoiceProvider:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER")
    if account_sid and auth_token and from_number:
        return TwilioVoiceProvider(account_sid, auth_token, from_number)
    return MockVoiceProvider()


def status_callback_url() -> str | None:
    base = os.getenv("VOLT_PUBLIC_BASE_URL", "").strip().rstrip("/")
    return f"{base}/api/voice/status" if base else None


def build_voice_script(event: dict) -> str:
    return (
        f"VOLT CORE. Attention required. Priority {event['priority']}. "
        f"System {event['system']} reported: {event['message']}. "
        f"Recommended action: {event['recommended_action']}."
    )
