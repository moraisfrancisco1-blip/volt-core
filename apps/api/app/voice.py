import os
from typing import Protocol

from twilio.rest import Client


class VoiceProvider(Protocol):
    def place_call(self, to: str, script: str) -> dict: ...


class MockVoiceProvider:
    def place_call(self, to: str, script: str) -> dict:
        return {"provider": "mock", "status": "queued", "to": to, "script": script}


class TwilioVoiceProvider:
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self.client = Client(account_sid, auth_token)
        self.from_number = from_number

    def place_call(self, to: str, script: str) -> dict:
        call = self.client.calls.create(
            to=to,
            from_=self.from_number,
            twiml=f"<Response><Say voice='alice' language='en-US'>{script}</Say></Response>",
        )
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
    from_number = os.getenv("TWILIO_PHONE_NUMBER") or os.getenv("VOLT_CALLER_NUMBER")
    if account_sid and auth_token and from_number:
        return TwilioVoiceProvider(account_sid, auth_token, from_number)
    return MockVoiceProvider()


def get_operator_phone_number() -> str | None:
    return os.getenv("VOLT_OPERATOR_PHONE_NUMBER") or os.getenv("DIANE_PHONE_NUMBER")


def build_voice_script(event: dict) -> str:
    return (
        f"VOLT CORE. Attention required. Priority {event['priority']}. "
        f"System {event['system']} reported: {event['message']}. "
        "Please check the VOLT dashboard immediately."
    )
