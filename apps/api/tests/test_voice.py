from app.voice import MockVoiceProvider, build_voice_script, get_voice_provider


def sample_event():
    return {
        "priority": "P1",
        "system": "payments",
        "message": "Payment processing is unavailable",
        "recommended_action": "call",
    }


def test_voice_script_contains_critical_context():
    script = build_voice_script(sample_event())
    assert "Priority P1" in script
    assert "payments" in script
    assert "Payment processing is unavailable" in script


def test_mock_voice_provider_never_places_real_call():
    result = MockVoiceProvider().place_call("+31000000000", "Test call")
    assert result["provider"] == "mock"
    assert result["status"] == "queued"
    assert result["to"] == "+31000000000"


def test_provider_falls_back_to_mock_without_twilio_config(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWILIO_PHONE_NUMBER", raising=False)
    assert isinstance(get_voice_provider(), MockVoiceProvider)
