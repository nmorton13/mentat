import json
import types

import pytest

from mentat.core import llm


class DummyResponse:
    def __init__(self, content, reasoning=None):
        self.choices = [
            types.SimpleNamespace(
                message=types.SimpleNamespace(content=content, reasoning=reasoning)
            )
        ]


class CountingCompletions:
    def __init__(self, content, reasoning=None, fail_on_response_format=False):
        self.content = content
        self.reasoning = reasoning
        self.fail_on_response_format = fail_on_response_format
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_on_response_format and "response_format" in kwargs:
            raise TypeError("response_format unsupported")
        return DummyResponse(self.content, self.reasoning)


class CountingClient:
    def __init__(self, content, reasoning=None, fail_on_response_format=False):
        self.completions = CountingCompletions(content, reasoning, fail_on_response_format)
        self.chat = types.SimpleNamespace(completions=self.completions)


def test_complete_returns_message_content():
    client = CountingClient("hello")

    result = llm.complete(client, "test-model", [{"role": "user", "content": "Hi"}])

    assert result == "hello"
    assert client.completions.calls[0]["model"] == "test-model"


def test_complete_json_parses_content():
    client = CountingClient(json.dumps({"ok": True}))

    result = llm.complete_json(client, "test-model", [{"role": "user", "content": "JSON"}])

    assert result == {"ok": True}
    assert client.completions.calls[0]["response_format"] == {"type": "json_object"}


def test_complete_json_parses_reasoning_when_content_empty():
    client = CountingClient(None, reasoning=json.dumps({"ok": True}))

    result = llm.complete_json(client, "test-model", [{"role": "user", "content": "JSON"}])

    assert result == {"ok": True}


def test_complete_json_falls_back_when_response_format_unsupported():
    client = CountingClient('Here is JSON: {"ok": true}', fail_on_response_format=True)

    result = llm.complete_json(client, "local-model", [{"role": "user", "content": "JSON"}])

    assert result == {"ok": True}
    assert "response_format" in client.completions.calls[0]
    assert "response_format" not in client.completions.calls[1]


def test_complete_json_falls_back_on_openai_bad_request(monkeypatch):
    class FakeBadRequestError(Exception):
        pass

    client = CountingClient('Here is JSON: {"ok": true}')
    original_create = client.completions.create

    def create(**kwargs):
        if "response_format" in kwargs:
            client.completions.calls.append(kwargs)
            raise FakeBadRequestError("response_format is not supported")
        return original_create(**kwargs)

    client.completions.create = create
    monkeypatch.setattr(llm, "BadRequestError", FakeBadRequestError)

    result = llm.complete_json(client, "local-model", [{"role": "user", "content": "JSON"}])

    assert result == {"ok": True}
    assert "response_format" in client.completions.calls[0]
    assert "response_format" not in client.completions.calls[1]


def test_complete_json_does_not_retry_unrelated_bad_request(monkeypatch):
    class FakeBadRequestError(Exception):
        body = {"message": "model not found"}

    client = CountingClient('{"ok": true}')

    def create(**kwargs):
        client.completions.calls.append(kwargs)
        raise FakeBadRequestError("model not found")

    client.completions.create = create
    monkeypatch.setattr(llm, "BadRequestError", FakeBadRequestError)

    with pytest.raises(FakeBadRequestError):
        llm.complete_json(client, "missing-model", [{"role": "user", "content": "JSON"}])

    assert len(client.completions.calls) == 1


def test_complete_json_parses_fenced_json_object():
    client = CountingClient('```json\n{"ok": true}\n```')

    result = llm.complete_json(client, "test-model", [{"role": "user", "content": "JSON"}])

    assert result == {"ok": True}


def test_complete_json_parses_fenced_json_array():
    client = CountingClient('Here you go:\n```json\n[{"ok": true}]\n```')

    result = llm.complete_json(client, "test-model", [{"role": "user", "content": "JSON"}])

    assert result == [{"ok": True}]


class FakeOllamaHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_ollama_adapter_posts_native_chat_payload(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeOllamaHTTPResponse({"message": {"content": "final answer"}})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    monkeypatch.setattr(llm.config, "OLLAMA_THINK", False)
    monkeypatch.setattr(llm.config, "OLLAMA_TEMPERATURE", "1.0")
    monkeypatch.setattr(llm.config, "OLLAMA_TOP_P", "0.95")
    monkeypatch.setattr(llm.config, "OLLAMA_TOP_K", "64")
    monkeypatch.setattr(llm.config, "OLLAMA_NUM_PREDICT", "")
    client = llm.OllamaChatClient("http://localhost:11434/api")

    result = llm.complete(
        client,
        "gemma4:12b-mlx",
        [{"role": "user", "content": "Hi"}],
        max_tokens=123,
    )

    assert result == "final answer"
    assert calls[0]["url"] == "http://localhost:11434/api/chat"
    assert calls[0]["json"]["model"] == "gemma4:12b-mlx"
    assert calls[0]["json"]["messages"] == [{"role": "user", "content": "Hi"}]
    assert calls[0]["json"]["stream"] is False
    assert calls[0]["json"]["think"] is False
    assert calls[0]["json"]["options"] == {
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 64,
        "num_predict": 123,
    }


def test_ollama_adapter_per_call_options_override_env(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json)
        return FakeOllamaHTTPResponse({"message": {"content": "{}"}})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    monkeypatch.setattr(llm.config, "OLLAMA_THINK", False)
    monkeypatch.setattr(llm.config, "OLLAMA_TEMPERATURE", "1.0")
    monkeypatch.setattr(llm.config, "OLLAMA_TOP_P", "0.95")
    monkeypatch.setattr(llm.config, "OLLAMA_TOP_K", "64")
    monkeypatch.setattr(llm.config, "OLLAMA_NUM_PREDICT", "999")
    client = llm.OllamaChatClient("http://localhost:11434")

    llm.complete_json(
        client,
        "gemma4:12b-mlx",
        [{"role": "user", "content": "JSON"}],
        temperature=0.2,
        top_p=0.8,
        top_k=40,
        max_tokens=77,
    )

    assert calls[0]["format"] == "json"
    assert calls[0]["options"] == {
        "temperature": 0.2,
        "top_p": 0.8,
        "top_k": 40,
        "num_predict": 77,
    }


def _patch_online_openrouter(monkeypatch, online_client):
    def fake_openai(**kwargs):
        online_client.kwargs = kwargs
        return online_client

    monkeypatch.setattr(llm, "_ONLINE_CLIENT", None)
    monkeypatch.setattr(llm, "OpenAI", fake_openai)
    monkeypatch.setattr(llm.config, "OPENROUTER_API_KEY", "openrouter-key")


def test_complete_online_uses_web_search_tool_and_strips_legacy_suffix(monkeypatch):
    monkeypatch.setattr(llm.config, "ONLINE_MODEL", None)
    monkeypatch.setattr(llm.config, "CHAT_BASE_URL", None)
    monkeypatch.setattr(llm.config, "_runtime_chat_provider", lambda: None)
    online_client = CountingClient("online")
    _patch_online_openrouter(monkeypatch, online_client)
    local_client = CountingClient("local")

    result = llm.complete_online(local_client, "test-model", [{"role": "user", "content": "web"}])
    result_again = llm.complete_online(local_client, "test-model:online", [{"role": "user", "content": "web"}])

    assert result.text == "online"
    assert result_again.text == "online"
    assert local_client.completions.calls == []
    assert online_client.completions.calls[0]["model"] == "test-model"
    assert online_client.completions.calls[1]["model"] == "test-model"
    assert online_client.completions.calls[0]["tools"] == [{"type": "openrouter:web_search"}]


def test_complete_online_uses_configured_online_model(monkeypatch):
    monkeypatch.setattr(llm.config, "ONLINE_MODEL", "openai/gpt-chat-latest")
    online_client = CountingClient("online")
    _patch_online_openrouter(monkeypatch, online_client)
    local_client = CountingClient("local")

    result = llm.complete_online(local_client, "qwen-local", [{"role": "user", "content": "web"}])

    assert result.text == "online"
    assert result.model == "openai/gpt-chat-latest"
    assert local_client.completions.calls == []
    assert online_client.completions.calls[0]["model"] == "openai/gpt-chat-latest"
    assert online_client.completions.calls[0]["tools"] == [{"type": "openrouter:web_search"}]


def test_complete_online_requires_openrouter_api_key(monkeypatch):
    monkeypatch.setattr(llm, "_ONLINE_CLIENT", None)
    monkeypatch.setattr(llm.config, "OPENROUTER_API_KEY", None)
    client = CountingClient("local")

    try:
        llm.complete_online(client, "test-model", [{"role": "user", "content": "web"}])
    except RuntimeError as exc:
        assert "OPENROUTER_API_KEY" in str(exc)
    else:
        raise AssertionError("complete_online should require OPENROUTER_API_KEY")
    assert client.completions.calls == []


def test_complete_online_appends_web_search_to_explicit_tools(monkeypatch):
    monkeypatch.setattr(llm.config, "ONLINE_MODEL", None)
    online_client = CountingClient("online")
    _patch_online_openrouter(monkeypatch, online_client)
    tools = [{"type": "custom_tool"}]

    llm.complete_online(CountingClient("local"), "test-model", [{"role": "user", "content": "web"}], tools=tools)

    assert online_client.completions.calls[0]["tools"] == [*tools, {"type": "openrouter:web_search"}]


def test_complete_online_does_not_duplicate_web_search_tool(monkeypatch):
    monkeypatch.setattr(llm.config, "ONLINE_MODEL", None)
    online_client = CountingClient("online")
    _patch_online_openrouter(monkeypatch, online_client)
    tools = [{"type": "openrouter:web_search"}]

    llm.complete_online(CountingClient("local"), "test-model", [{"role": "user", "content": "web"}], tools=tools)

    assert online_client.completions.calls[0]["tools"] == tools


def test_complete_online_uses_openrouter_client_for_configured_online_model(monkeypatch):
    online_client = CountingClient("online")

    _patch_online_openrouter(monkeypatch, online_client)
    monkeypatch.setattr(llm.config, "ONLINE_MODEL", "openai/gpt-chat-latest")
    local_client = CountingClient("local")

    result = llm.complete_online(local_client, "qwen-local", [{"role": "user", "content": "web"}])

    assert result.text == "online"
    assert result.model == "openai/gpt-chat-latest"
    assert local_client.completions.calls == []
    assert online_client.completions.calls[0]["model"] == "openai/gpt-chat-latest"
    assert online_client.completions.calls[0]["tools"] == [{"type": "openrouter:web_search"}]
    assert online_client.kwargs["api_key"] == "openrouter-key"
    assert online_client.kwargs["base_url"] == llm.config.OPENROUTER_BASE_URL


def test_complete_online_strips_configured_legacy_online_suffix(monkeypatch):
    monkeypatch.setattr(llm.config, "ONLINE_MODEL", "openai/gpt-chat-latest:online")
    online_client = CountingClient("online")
    _patch_online_openrouter(monkeypatch, online_client)

    result = llm.complete_online(CountingClient("local"), "qwen-local", [{"role": "user", "content": "web"}])

    assert result.model == "openai/gpt-chat-latest"
    assert online_client.completions.calls[0]["model"] == "openai/gpt-chat-latest"
