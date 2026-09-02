from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import anthropic
import httpx

# Priority: Anthropic first (the 6 call sites' historical model-name references),
# DeepSeek before OpenAI (the key actually held right now). VOLT_LLM_PROVIDER forces
# a specific choice if more than one key is ever configured at once.
_VALID_PROVIDERS = {"anthropic", "deepseek", "openai"}
_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    # deepseek-chat, not deepseek-reasoner -- the reasoning model has no reliable
    # tool-use support, and every one of the 6 call sites depends on it.
    "deepseek": "deepseek-chat",
    "openai": "gpt-4o",
}
_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "openai": "https://api.openai.com/v1",
}
_KEY_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
}


class LLMError(RuntimeError):
    """Base class for all llm_client failures."""


class LLMConfigError(LLMError):
    """No provider API key configured, or an invalid VOLT_LLM_PROVIDER override."""


class LLMCallError(LLMError):
    """The underlying provider HTTP call failed (network error, non-2xx, bad JSON)."""


def _detect_provider_or_none() -> str | None:
    # Never cached -- re-reads env vars every call, so monkeypatch.setenv/delenv in
    # tests behaves exactly like it does for every other credential check in this
    # codebase (e.g. os.getenv("GITHUB_TOKEN") checked fresh each time).
    override = os.getenv("VOLT_LLM_PROVIDER", "").strip()
    if override:
        if override not in _VALID_PROVIDERS:
            raise LLMConfigError(f"VOLT_LLM_PROVIDER={override!r} is not one of {sorted(_VALID_PROVIDERS)}")
        return override
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("DEEPSEEK_API_KEY"):
        return "deepseek"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return None


def is_configured() -> bool:
    return _detect_provider_or_none() is not None


def default_model() -> str:
    # Never raises -- safe to call at module import time. Degrades to the same
    # "claude-sonnet-4-5" string that was already hardcoded everywhere when no
    # provider is configured; harmless, since get_client() is what actually raises
    # if a real call is attempted without a key.
    return _DEFAULT_MODELS[_detect_provider_or_none() or "anthropic"]


def _to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for msg in messages:
        role, content = msg["role"], msg["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            text = "\n".join(b["text"] for b in content if b.get("type") == "text")
            tool_calls = [
                {"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b["input"])}}
                for b in content if b.get("type") == "tool_use"
            ]
            entry: dict[str, Any] = {"role": "assistant", "content": text or None}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)
        else:  # role == "user": tool_result blocks (each becomes its own "tool" message) or plain text
            for b in content:
                if b.get("type") == "tool_result":
                    result = b["content"]
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": result if isinstance(result, str) else json.dumps(result)})
                elif b.get("type") == "text":
                    out.append({"role": "user", "content": b["text"]})
    return out


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]}}
        for t in tools
    ]


_FINISH_REASON_MAP = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens", "content_filter": "end_turn"}


@dataclass
class ModelResponse:
    content: list[dict]  # {"type": "text", "text": ...} | {"type": "tool_use", "id": ..., "name": ..., "input": {...}}
    stop_reason: str  # Anthropic's vocabulary: "tool_use" | "end_turn" | "max_tokens" | ...
    input_tokens: int | None = None
    output_tokens: int | None = None


def _anthropic_response_to_model_response(resp: Any) -> ModelResponse:
    content = []
    for block in resp.content:
        if block.type == "text":
            content.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            content.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
    usage = getattr(resp, "usage", None)
    return ModelResponse(
        content=content,
        stop_reason=resp.stop_reason,
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
    )


def _openai_response_to_model_response(data: dict) -> ModelResponse:
    choice = data["choices"][0]
    msg = choice["message"]
    content: list[dict] = []
    if msg.get("content"):
        content.append({"type": "text", "text": msg["content"]})
    for tc in msg.get("tool_calls") or []:
        try:
            args = json.loads(tc["function"]["arguments"])
        except (json.JSONDecodeError, TypeError):
            # A flaky/malformed response degrades to an empty input dict, not a crash --
            # the caller's handler(job, **block["input"]) will then raise a normal
            # TypeError for missing kwargs, caught by the existing outer try/except in
            # every entrypoint. Matches the graceful-degradation posture used everywhere
            # else in this codebase rather than special-casing it here.
            args = {}
        content.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"], "input": args})
    usage = data.get("usage") or {}
    finish_reason = choice.get("finish_reason")
    return ModelResponse(
        content=content,
        stop_reason=_FINISH_REASON_MAP.get(finish_reason, finish_reason),
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
    )


@dataclass
class LLMClient:
    provider: str
    api_key: str
    base_url: str | None = None
    _anthropic_client: Any = None

    def call(self, *, model: str, max_tokens: int, system: str, messages: list[dict], tools: list[dict], tool_choice: str | None = None) -> ModelResponse:
        if self.provider == "anthropic":
            return self._call_anthropic(model, max_tokens, system, messages, tools, tool_choice)
        return self._call_openai_compatible(model, max_tokens, system, messages, tools, tool_choice)

    def _call_anthropic(self, model: str, max_tokens: int, system: str, messages: list[dict], tools: list[dict], tool_choice: str | None) -> ModelResponse:
        kwargs: dict[str, Any] = dict(model=model, max_tokens=max_tokens, system=system, tools=tools, messages=messages)
        if tool_choice:
            kwargs["tool_choice"] = {"type": "tool", "name": tool_choice}
        resp = self._anthropic_client.messages.create(**kwargs)
        return _anthropic_response_to_model_response(resp)

    def _call_openai_compatible(self, model: str, max_tokens: int, system: str, messages: list[dict], tools: list[dict], tool_choice: str | None) -> ModelResponse:
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": _to_openai_messages(system, messages),
            "tools": _to_openai_tools(tools),
            "tool_choice": {"type": "function", "function": {"name": tool_choice}} if tool_choice else "auto",
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=120) as client:
                resp = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMCallError(f"{self.provider} API error {exc.response.status_code}: {exc.response.text[:500]}") from exc
        except httpx.HTTPError as exc:
            raise LLMCallError(f"{self.provider} API request failed: {exc}") from exc
        return _openai_response_to_model_response(resp.json())


def get_client() -> LLMClient:
    # Only ever called inside an agent's entrypoint function, never at import time --
    # same discipline anthropic.Anthropic() already had.
    provider = _detect_provider_or_none()
    if provider is None:
        raise LLMConfigError("No LLM provider configured: set ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, or OPENAI_API_KEY.")
    if provider == "anthropic":
        return LLMClient(provider="anthropic", api_key=os.environ["ANTHROPIC_API_KEY"], _anthropic_client=anthropic.Anthropic())
    key_env = _KEY_ENV_VARS[provider]
    return LLMClient(provider=provider, api_key=os.environ[key_env], base_url=_BASE_URLS[provider])
