import httpx
import pytest

from app import llm_client


def _clear_all_providers(monkeypatch):
    monkeypatch.delenv("VOLT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# --- provider detection --------------------------------------------------------

def test_no_key_configured_is_not_configured(monkeypatch):
    _clear_all_providers(monkeypatch)
    assert llm_client.is_configured() is False
    assert llm_client._detect_provider_or_none() is None


def test_anthropic_key_alone_is_detected(monkeypatch):
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    assert llm_client._detect_provider_or_none() == "anthropic"


def test_deepseek_key_alone_is_detected(monkeypatch):
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    assert llm_client._detect_provider_or_none() == "deepseek"


def test_openai_key_alone_is_detected(monkeypatch):
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    assert llm_client._detect_provider_or_none() == "openai"


def test_priority_is_anthropic_then_deepseek_then_openai(monkeypatch):
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    assert llm_client._detect_provider_or_none() == "deepseek"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    assert llm_client._detect_provider_or_none() == "anthropic"


def test_volt_llm_provider_forces_a_choice(monkeypatch):
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    monkeypatch.setenv("VOLT_LLM_PROVIDER", "openai")
    assert llm_client._detect_provider_or_none() == "openai"


def test_invalid_volt_llm_provider_raises(monkeypatch):
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("VOLT_LLM_PROVIDER", "not-a-real-provider")
    with pytest.raises(llm_client.LLMConfigError):
        llm_client._detect_provider_or_none()


# --- default_model -- never raises, even with nothing configured ----------------

def test_default_model_without_any_key_falls_back_to_anthropic_default(monkeypatch):
    _clear_all_providers(monkeypatch)
    assert llm_client.default_model() == "claude-sonnet-4-5"


def test_default_model_reflects_active_provider(monkeypatch):
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake")
    assert llm_client.default_model() == "deepseek-chat"


# --- get_client -------------------------------------------------------------------

def test_get_client_without_any_key_raises_config_error(monkeypatch):
    _clear_all_providers(monkeypatch)
    with pytest.raises(llm_client.LLMConfigError):
        llm_client.get_client()


def test_get_client_for_deepseek_uses_deepseek_base_url(monkeypatch):
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")
    client = llm_client.get_client()
    assert client.provider == "deepseek"
    assert client.api_key == "fake-key"
    assert client.base_url == "https://api.deepseek.com"


# --- message/tool translation to the OpenAI-compatible shape --------------------

def test_to_openai_messages_translates_assistant_tool_use_and_tool_result():
    messages = [
        {"role": "user", "content": "investiga o sistema x"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "vou verificar"},
            {"type": "tool_use", "id": "call_1", "name": "get_status", "input": {"limit": 5}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": '{"ok": true}'}]},
    ]
    out = llm_client._to_openai_messages("system prompt", messages)

    assert out[0] == {"role": "system", "content": "system prompt"}
    assert out[1] == {"role": "user", "content": "investiga o sistema x"}
    assert out[2]["role"] == "assistant"
    assert out[2]["content"] == "vou verificar"
    assert out[2]["tool_calls"] == [{"id": "call_1", "type": "function", "function": {"name": "get_status", "arguments": '{"limit": 5}'}}]
    assert out[3] == {"role": "tool", "tool_call_id": "call_1", "content": '{"ok": true}'}


def test_to_openai_tools_wraps_input_schema_as_function_parameters():
    tools = [{"name": "get_status", "description": "reads status", "input_schema": {"type": "object", "properties": {}}}]
    out = llm_client._to_openai_tools(tools)
    assert out == [{"type": "function", "function": {"name": "get_status", "description": "reads status", "parameters": {"type": "object", "properties": {}}}}]


# --- response normalization -------------------------------------------------------

def test_openai_response_with_tool_call_normalizes_correctly():
    data = {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {"content": None, "tool_calls": [
                {"id": "call_9", "type": "function", "function": {"name": "get_status", "arguments": '{"limit": 3}'}},
            ]},
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    result = llm_client._openai_response_to_model_response(data)

    assert result.stop_reason == "tool_use"
    assert result.content == [{"type": "tool_use", "id": "call_9", "name": "get_status", "input": {"limit": 3}}]
    assert result.input_tokens == 100
    assert result.output_tokens == 20


def test_openai_response_with_plain_text_normalizes_stop_reason():
    data = {"choices": [{"finish_reason": "stop", "message": {"content": "olá"}}], "usage": {}}
    result = llm_client._openai_response_to_model_response(data)
    assert result.stop_reason == "end_turn"
    assert result.content == [{"type": "text", "text": "olá"}]


def test_openai_response_with_malformed_tool_arguments_degrades_to_empty_input():
    data = {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {"content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "get_status", "arguments": "not valid json"}},
            ]},
        }],
        "usage": {},
    }
    result = llm_client._openai_response_to_model_response(data)  # must not raise
    assert result.content == [{"type": "tool_use", "id": "call_1", "name": "get_status", "input": {}}]


# --- LLMClient.call -- OpenAI-compatible path, network mocked -------------------

def test_call_openai_compatible_posts_to_the_right_url_and_forces_tool_choice(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "classify", "arguments": "{}"}},
            ]}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    class FakeClient:
        def __init__(self, timeout=None): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(llm_client.httpx, "Client", FakeClient)

    client = llm_client.LLMClient(provider="deepseek", api_key="fake-key", base_url="https://api.deepseek.com")
    result = client.call(model="deepseek-chat", max_tokens=100, system="sys", messages=[{"role": "user", "content": "oi"}], tools=[{"name": "classify", "description": "", "input_schema": {}}], tool_choice="classify")

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["json"]["tool_choice"] == {"type": "function", "function": {"name": "classify"}}
    assert captured["headers"]["Authorization"] == "Bearer fake-key"
    assert result.content[0]["name"] == "classify"


def test_call_openai_compatible_http_error_raises_llm_call_error(monkeypatch):
    class FakeResponse:
        status_code = 401
        text = "invalid api key"
        def raise_for_status(self):
            raise httpx.HTTPStatusError("401", request=None, response=self)

    class FakeClient:
        def __init__(self, timeout=None): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json=None, headers=None):
            return FakeResponse()

    monkeypatch.setattr(llm_client.httpx, "Client", FakeClient)

    client = llm_client.LLMClient(provider="openai", api_key="fake-key", base_url="https://api.openai.com/v1")
    with pytest.raises(llm_client.LLMCallError):
        client.call(model="gpt-4o", max_tokens=100, system="sys", messages=[], tools=[])
