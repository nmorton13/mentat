import asyncio

from mentat.chat.tools import base
from mentat.chat.tools import capture_thought
from mentat.core.llm import OllamaChatClient


def test_tool_client_supports_native_ollama(monkeypatch):
    monkeypatch.setattr(base, "MENTAT_AVAILABLE", True)
    monkeypatch.setattr(base, "get_chat_provider", lambda: "ollama")
    monkeypatch.setattr(base, "get_chat_base_url", lambda: "http://127.0.0.1:11434")

    client = base.get_openrouter_client()

    assert isinstance(client, OllamaChatClient)


def test_tool_capture_marks_fallback_as_not_ai_analyzed(monkeypatch):
    saved = {}

    class FakeDB:
        def save_memory(self, **kwargs):
            saved.update(kwargs)
            return 1

        def get_memory_by_id(self, memory_id, user_id):
            return {"timestamp": "2026-07-10T12:00:00"}

    monkeypatch.setattr(capture_thought, "get_db", lambda: FakeDB())
    monkeypatch.setattr(capture_thought, "get_openrouter_client", lambda: None)
    monkeypatch.setattr(capture_thought, "MENTAT_AVAILABLE", True)
    monkeypatch.setattr(
        "mentat.core.markdown_export.save_memory_to_markdown",
        lambda **kwargs: None,
    )

    result = asyncio.run(
        capture_thought.handler(
            {"content": "A thought worth keeping"},
            {"user_id": "u1", "channel": "voice"},
        )
    )

    assert result["success"] is True
    assert saved["metadata"]["ai_analyzed"] is False
