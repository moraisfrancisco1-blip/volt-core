from typing import Protocol


class VoiceProvider(Protocol):
    def place_call(self, to: str, script: str) -> dict: ...


class MockVoiceProvider:
    def place_call(self, to: str, script: str) -> dict:
        return {"provider": "mock", "status": "queued", "to": to, "script": script}


def build_voice_script(event: dict) -> str:
    return (
        f"VOLT CORE. Attention required. Priority {event['priority']}. "
        f"System {event['system']} reported: {event['message']}. "
        f"Recommended action: {event['recommended_action']}."
    )
