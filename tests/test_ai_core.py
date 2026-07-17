import json
import sys
import types

import pytest

from mentat.core import ai, config
import mentat.core.database as database_module


class DummyDB:
    def __init__(self, return_id=123, fail_first=False):
        self.return_id = return_id
        self.fail_first = fail_first
        self.save_memory_calls = []
        self.save_embedding_calls = []
        self.get_memory_calls = []

    def save_memory(self, **kwargs):
        self.save_memory_calls.append(kwargs)
        if self.fail_first:
            self.fail_first = False
            raise Exception("primary save failed")
        return self.return_id

    def save_embedding(self, memory_id, embedding):
        self.save_embedding_calls.append((memory_id, embedding))

    def get_memory_by_id(self, memory_id, user_id):
        self.get_memory_calls.append((memory_id, user_id))
        return {"timestamp": "2024-01-01"}


def stub_markdown_export(monkeypatch, call_log):
    export_module = types.SimpleNamespace(
        save_memory_to_markdown=lambda *args, **kwargs: call_log.append((args, kwargs))
    )
    monkeypatch.setitem(sys.modules, "mentat.core.markdown_export", export_module)


class DummyResponse:
    def __init__(self, content, reasoning=None):
        self.choices = [
            types.SimpleNamespace(
                message=types.SimpleNamespace(content=content, reasoning=reasoning)
            )
        ]


class CountingCompletions:
    def __init__(self, content, reasoning=None):
        self.content = content
        self.reasoning = reasoning
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return DummyResponse(self.content, self.reasoning)


class CountingClient:
    def __init__(self, content, reasoning=None):
        self.completions = CountingCompletions(content, reasoning)
        self.chat = types.SimpleNamespace(completions=self.completions)


def test_analyze_capture_content_uses_single_call_and_defaults_entities(monkeypatch):
    payload = {
        "type": "note",
        "urls": [],
        "enhanced_content": "Ada built MENTAT in Python.",
        "summary": "Ada built MENTAT in Python.",
        "themes": ["MENTAT", "Python"],
        "actionable_items": [],
        "confidence": 0.91,
    }
    client = CountingClient(json.dumps(payload))

    def fail_entity_call(*args, **kwargs):
        raise AssertionError("entities should come from capture analysis")

    monkeypatch.setattr(config, "CAPTURE_ANALYSIS_PROVIDER", "chat")
    monkeypatch.setattr(config, "CAPTURE_ANALYSIS_MODEL", None)
    monkeypatch.setattr(ai, "extract_structured_entities", fail_entity_call)

    result = ai.analyze_capture_content(
        "Ada built MENTAT in Python.",
        model="fake-model",
        client=client,
    )

    assert len(client.completions.calls) == 1
    assert result["themes"] == ["MENTAT", "Python"]
    assert result["entities"] == {
        "people": [],
        "organizations": [],
        "technologies": [],
        "projects": [],
        "concepts": [],
        "locations": [],
        "dates": [],
    }


def test_analyze_capture_content_parses_reasoning_when_content_empty(monkeypatch):
    payload = {
        "type": "note",
        "urls": [],
        "enhanced_content": "Ada built MENTAT in Python.",
        "summary": "Ada built MENTAT in Python.",
        "themes": ["MENTAT", "Python"],
        "actionable_items": [],
        "entities": {"people": ["Ada"], "technologies": ["Python"]},
        "confidence": 0.91,
    }
    client = CountingClient(None, reasoning=json.dumps(payload))
    monkeypatch.setattr(config, "CAPTURE_ANALYSIS_PROVIDER", "chat")
    monkeypatch.setattr(config, "CAPTURE_ANALYSIS_MODEL", None)

    result = ai.analyze_capture_content(
        "Ada built MENTAT in Python.",
        model="fake-model",
        client=client,
    )

    assert result["type"] == "note"
    assert result["entities"]["people"] == ["Ada"]
    assert result["entities"]["technologies"] == ["Python"]


def test_process_content_with_ai_saves_and_exports(monkeypatch):
    analysis = {
        "type": "idea",
        "enhanced_content": "enhanced content",
        "themes": ["AI", "Research"],
        "actionable_items": ["do things"],
        "entities": {"people": ["Ada"]},
        "confidence": 0.9,
        "summary": "sum",
    }
    dummy_db = DummyDB(return_id=456)
    monkeypatch.setattr(database_module, "db", dummy_db)
    monkeypatch.setattr(ai, "analyze_capture_content", lambda *args, **kwargs: analysis)
    monkeypatch.setattr(ai, "get_embedding_for_content", lambda content: [0.1, 0.2])
    export_calls = []
    stub_markdown_export(monkeypatch, export_calls)

    memory_id, tags, detected, themes, items, metadata = ai.process_content_with_ai(
        "My idea #TagOne with content",
        user_id="u1",
        command_type="note",
        metadata={"source": "test"},
        markdown_extra="more context",
    )

    assert memory_id == 456
    assert tags == ["tagone", "ai", "research", "ada"]
    assert detected == "idea"
    assert themes == ["AI", "Research"]
    assert items == ["do things"]
    assert metadata["ai_confidence"] == 0.9
    assert metadata["source"] == "test"
    assert dummy_db.save_embedding_calls == [(456, [0.1, 0.2])]
    saved = dummy_db.save_memory_calls[0]
    assert saved["command_type"] == "idea"
    assert saved["content"] == "enhanced content"
    assert export_calls  # markdown export attempted


def test_process_content_with_ai_reuses_precomputed_analysis(monkeypatch):
    analysis = {
        "type": "idea",
        "enhanced_content": "already analyzed",
        "themes": ["Performance"],
        "actionable_items": [],
        "entities": {"projects": ["Mentat"]},
        "confidence": 0.8,
        "summary": "sum",
    }
    dummy_db = DummyDB(return_id=321)
    monkeypatch.setattr(database_module, "db", dummy_db)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("analysis should be reused")

    monkeypatch.setattr(ai, "analyze_capture_content", fail_if_called)
    monkeypatch.setattr(ai, "get_embedding_for_content", lambda content: None)
    stub_markdown_export(monkeypatch, [])

    memory_id, tags, detected, themes, items, metadata = ai.process_content_with_ai(
        "Capture this #Mentat",
        user_id="u1",
        command_type="note",
        precomputed_analysis=analysis,
    )

    assert memory_id == 321
    assert tags == ["mentat", "performance"]
    assert detected == "idea"
    assert themes == ["Performance"]
    assert items == []
    assert metadata["ai_summary"] == "sum"


def test_process_content_with_ai_fallback_on_error(monkeypatch):
    analysis = {
        "type": "idea",
        "enhanced_content": "enhanced content",
        "themes": ["AI"],
        "actionable_items": [],
        "entities": {"people": []},
        "confidence": 0.4,
        "summary": "sum",
    }
    dummy_db = DummyDB(return_id=99, fail_first=True)
    monkeypatch.setattr(database_module, "db", dummy_db)
    monkeypatch.setattr(ai, "analyze_capture_content", lambda *args, **kwargs: analysis)
    monkeypatch.setattr(ai, "get_embedding_for_content", lambda content: [1.0])
    stub_markdown_export(monkeypatch, [])

    memory_id, tags, detected, themes, items, metadata = ai.process_content_with_ai(
        "#Tag failure path",
        user_id="u2",
        command_type="note",
    )

    assert memory_id == 99
    assert tags == ["Tag"]
    assert detected == "note"
    assert themes == []
    assert items == []
    assert dummy_db.save_embedding_calls == []  # embedding skipped due to exception path
    assert len(dummy_db.save_memory_calls) == 2  # initial failure + fallback save


def test_process_content_with_ai_cleans_tags(monkeypatch):
    analysis = {
        "type": "idea",
        "enhanced_content": "enhanced",
        "themes": ["AI", "A", "123", "Tag"],
        "actionable_items": [],
        "entities": {"people": ["Bob", ";"]},
        "confidence": 0.6,
        "summary": "",
    }
    dummy_db = DummyDB(return_id=7)
    monkeypatch.setattr(database_module, "db", dummy_db)
    monkeypatch.setattr(ai, "analyze_capture_content", lambda *args, **kwargs: analysis)
    monkeypatch.setattr(ai, "get_embedding_for_content", lambda content: None)
    stub_markdown_export(monkeypatch, [])

    _, tags, _, _, _, metadata = ai.process_content_with_ai(
        "Messy #Tag #x #1 #A",
        user_id="u3",
        command_type="note",
    )

    assert tags == ["tag", "ai", "bob"]
    assert metadata["themes"] == ["AI", "A", "123", "Tag"]


def test_extract_todos_from_content(monkeypatch):
    todo_payload = {
        "todos": [
            {
                "action": "finish draft",
                "context": "project update",
                "priority": "high",
                "time_sensitive": True,
                "project": "alpha",
                "due_date": "tomorrow",
                "dependencies": ["outline"],
            }
        ]
    }

    class DummyResponse:
        def __init__(self, content):
            self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=content))]

    class DummyCompletions:
        def __init__(self, content):
            self.content = content

        def create(self, **kwargs):
            return DummyResponse(self.content)

    class DummyClient:
        def __init__(self, content):
            self.chat = types.SimpleNamespace(completions=DummyCompletions(content))

    client = DummyClient(json.dumps(todo_payload))
    monkeypatch.setattr(config, "TODO_EXTRACTION_PROVIDER", "chat")
    monkeypatch.setattr(config, "TODO_EXTRACTION_MODEL", None)
    todos = ai.extract_todos_from_content("Finish the draft", model="fake-model", client=client)
    assert todos[0]["action"] == "finish draft"

    failing_client = DummyClient(json.dumps(todo_payload))

    def raise_error(**kwargs):
        raise RuntimeError("boom")

    failing_client.chat.completions.create = raise_error
    assert ai.extract_todos_from_content("Do nothing", client=failing_client) == []
    assert ai.extract_todos_from_content("No client provided") == []


def test_handle_capture_preserves_url_note_without_fetching(monkeypatch):
    from mentat.cli import commands

    saved = {}

    def fake_analysis(content, *args, **kwargs):
        return {
            "type": "link",
            "urls": ["https://example.com/post"],
            "enhanced_content": content,
            "summary": "summary",
            "themes": [],
            "actionable_items": [],
            "confidence": 0.9,
        }

    def fake_process(content_to_save, *args, **kwargs):
        saved["content"] = content_to_save
        return 1, ["tag"], "link", [], [], {}

    monkeypatch.setattr(commands, "analyze_capture_content", fake_analysis)
    monkeypatch.setattr(commands, "process_content_with_ai", fake_process)

    class DummyDB:
        pass

    commands.handle_capture(
        "My note about this post https://example.com/post",
        user_id="u1",
        enable_web_search=False,
        current_model="model",
        openrouter_client=None,
        openai_client=None,
        db=DummyDB(),
        last_displayed_items=[],
    )

    assert saved["content"] == "My note about this post https://example.com/post"
