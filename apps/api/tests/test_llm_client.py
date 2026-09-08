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


# --- cheap_model -- the classification/triage tier, same never-raises contract ------

def test_cheap_model_without_any_key_falls_back_to_anthropic_haiku(monkeypatch):
    _clear_all_providers(monkeypatch)
    assert llm_client.cheap_model() == "claude-haiku-4-5-20251001"


def test_cheap_model_reflects_active_provider(monkeypatch):
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    assert llm_client.cheap_model() == "gpt-4o-mini"


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


# --- LLMClient.call -- Anthropic path, prompt-caching system blocks -------------

def test_call_anthropic_passes_system_block_list_through_unchanged():
    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return type("R", (), {"content": [], "stop_reason": "end_turn", "usage": None})()

    class FakeAnthropicClient:
        messages = FakeMessages()

    system_blocks = [
        {"type": "text", "text": "persona"},
        {"type": "text", "text": "big static facts blob", "cache_control": {"type": "ephemeral"}},
    ]
    client = llm_client.LLMClient(provider="anthropic", api_key="fake", _anthropic_client=FakeAnthropicClient())
    client.call(model="claude-haiku-4-5-20251001", max_tokens=100, system=system_blocks, messages=[{"role": "user", "content": "oi"}], tools=[])

    # The cache_control block must reach the real API call byte-for-byte -- this is the
    # whole mechanism prompt caching relies on, so nothing here may rewrap, stringify,
    # or drop the cache_control key.
    assert captured["system"] == system_blocks


def test_to_openai_messages_flattens_cache_control_system_blocks_to_plain_text():
    # OpenAI-compatible providers don't understand cache_control -- a system block list
    # (built for Anthropic's prompt cache) must still degrade to a normal system string
    # rather than erroring or silently dropping content when DeepSeek/OpenAI is active.
    system_blocks = [
        {"type": "text", "text": "persona"},
        {"type": "text", "text": "facts", "cache_control": {"type": "ephemeral"}},
    ]
    messages = llm_client._to_openai_messages(system_blocks, [{"role": "user", "content": "oi"}])
    assert messages[0] == {"role": "system", "content": "persona\n\nfacts"}


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
