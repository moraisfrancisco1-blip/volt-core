import html
import os
from typing import Protocol


class VoiceProvider(Protocol):
    def place_call(self, to: str, script: str) -> dict: ...


class MockVoiceProvider:
    def place_call(self, to: str, script: str) -> dict:
        return {"provider": "mock", "status": "queued", "to": to, "script": script}


class TwilioVoiceProvider:
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        from twilio.rest import Client

        self.client = Client(account_sid, auth_token)
        self.from_number = from_number

    def place_call(self, to: str, script: str) -> dict:
        twiml = f"<Response><Say language='en-US'>{html.escape(script)}</Say></Response>"
        call = self.client.calls.create(to=to, from_=self.from_number, twiml=twiml)
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


def build_voice_script(event: dict) -> str:
    return (
        f"VOLT CORE. Attention required. Priority {event['priority']}. "
        f"System {event['system']} reported: {event['message']}. "
        f"Recommended action: {event['recommended_action']}."
    )
